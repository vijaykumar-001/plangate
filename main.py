import os
import secrets
import httpx
from fastapi import FastAPI, Request, Header
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles

import database
import engine
from demo_app import demo_app

app = FastAPI(
    title="PlanGate Entitlement Gateway",
    description="Zero-code drop-in entitlement gateway with explainable blocks and burn-rate forecasting."
)

# Initialize SQLite tables and seed Free & Pro customer keys on startup
database.init_db()

# Also mount the untouched upstream app under /direct so you can demo it side-by-side
app.mount("/direct", demo_app)


@app.get("/health")
def health_check():
    return {"status": "ok", "service": "PlanGate Entitlement Gateway"}


@app.get("/forecast")
def get_forecast(
    endpoint: str = "/export",
    x_api_key: str = Header(default="pg_free_key_123", alias="X-API-Key")
):
    """Phase 5: Return burn-rate forecast for a customer and endpoint."""
    customer = database.get_customer_by_api_key(x_api_key)
    if not customer:
        return JSONResponse(
            status_code=401,
            content={"error": "Invalid API Key", "message": "Provide a valid X-API-Key header."}
        )
    current_usage = database.get_usage(customer["customer_id"], endpoint)
    forecast_data = engine.calculate_burn_rate_forecast(
        plan_name=customer["plan_name"],
        endpoint=endpoint,
        current_usage=current_usage
    )
    forecast_data["customer_id"] = customer["customer_id"]
    forecast_data["customer_name"] = customer["name"]
    return forecast_data


@app.get("/logs")
def get_audit_logs():
    """Phase 6: Return recent audit logs and usage summary for the dashboard."""
    free_export = database.get_usage("cust_free_01", "/export")
    pro_export = database.get_usage("cust_pro_02", "/export")
    free_notes = database.get_usage("cust_free_01", "/notes")
    pro_notes = database.get_usage("cust_pro_02", "/notes")

    return {
        "usage_summary": {
            "Free": {
                "customer_name": "Acme Startup (Free)",
                "api_key_sample": "pg_free_key_123",
                "/export": {"used": free_export, "limit": engine.PLANS["Free"]["limits"]["/export"]},
                "/notes": {"used": free_notes, "limit": engine.PLANS["Free"]["limits"]["/notes"]},
                "forecast_export": engine.calculate_burn_rate_forecast("Free", "/export", free_export)
            },
            "Pro": {
                "customer_name": "Enterprise Corp (Pro)",
                "api_key_sample": "pg_pro_key_999",
                "/export": {"used": pro_export, "limit": engine.PLANS["Pro"]["limits"]["/export"]},
                "/notes": {"used": pro_notes, "limit": engine.PLANS["Pro"]["limits"]["/notes"]},
                "forecast_export": engine.calculate_burn_rate_forecast("Pro", "/export", pro_export)
            }
        },
        "logs": database.get_recent_logs(30)
    }


ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN")


@app.post("/admin/reset")
def reset_demo_data(x_admin_token: str = Header(default="", alias="X-Admin-Token")):
    """Reset all counters and logs. Requires X-Admin-Token when ADMIN_TOKEN is set."""
    if ADMIN_TOKEN and not secrets.compare_digest(
        x_admin_token.encode(), ADMIN_TOKEN.encode()
    ):
        return JSONResponse(
            status_code=401,
            content={"error": "Unauthorized", "message": "Valid X-Admin-Token required."}
        )
    database.reset_all_usage()
    return {"status": "reset_complete", "message": "All usage counters and audit logs cleared."}


@app.api_route("/gateway/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def gateway_proxy(
    path: str,
    request: Request,
    x_api_key: str = Header(default=None, alias="X-API-Key")
):
    """
    Phases 2, 3 & 4: Zero-code gateway proxy.
    1. Authenticates customer via SHA-256 hashed API key.
    2. Evaluates plan rules (<80% ALLOW, >=80% WARN, 100% Explainable BLOCK).
    3. Logs decision to SQLite audit log.
    4. Forwards request via httpx to the untouched upstream app if allowed.
    """
    endpoint = f"/{path.strip('/')}"

    # 1. Authenticate API Key
    if not x_api_key:
        return JSONResponse(
            status_code=401,
            content={
                "decision": "BLOCK",
                "reason": "Missing 'X-API-Key' header.",
                "action_required": "Pass a valid API key in the 'X-API-Key' request header (e.g., pg_free_key_123)."
            }
        )

    customer = database.get_customer_by_api_key(x_api_key)
    if not customer:
        database.log_decision("unknown", "Unknown", endpoint, "BLOCK", "Invalid or unrecognized API key", 0, 0)
        return JSONResponse(
            status_code=403,
            content={
                "decision": "BLOCK",
                "reason": "Invalid API Key provided.",
                "action_required": "Verify your API key or generate a new key in the PlanGate Dashboard."
            }
        )

    customer_id = customer["customer_id"]
    plan_name = customer["plan_name"]

    # 2. Check current usage & run Entitlement Engine
    current_usage = database.get_usage(customer_id, endpoint)
    evaluation = engine.evaluate_request(plan_name, endpoint, current_usage)

    quota_headers = {
        "X-PlanGate-Plan": plan_name,
        "X-PlanGate-Decision": evaluation["decision"],
        "X-PlanGate-Limit": str(evaluation["limit"]),
        "X-PlanGate-Remaining": str(evaluation["remaining"]),
        "X-PlanGate-Reset": evaluation["reset_at"]
    }

    # 3. If BLOCKED (100% limit reached), log and return Explainable Block (HTTP 429)
    if not evaluation["allowed"]:
        database.log_decision(
            customer_id=customer_id,
            plan_name=plan_name,
            endpoint=endpoint,
            decision="BLOCK",
            reason=evaluation["reason"],
            current_usage=evaluation["current_usage"],
            limit_value=evaluation["limit"]
        )
        return JSONResponse(
            status_code=429,
            headers=quota_headers,
            content={
                "error": "PlanLimitExceeded",
                "decision": evaluation["decision"],
                "customer": customer["name"],
                "plan": plan_name,
                "endpoint": endpoint,
                "usage": {
                    "current": evaluation["current_usage"],
                    "limit": evaluation["limit"],
                    "remaining": 0
                },
                "explainable_block": {
                    "why_blocked": evaluation["reason"],
                    "reset_date_utc": evaluation["reset_at"],
                    "unblocking_plan": evaluation.get("unblocking_plan", "Pro"),
                    "how_to_unblock": evaluation["upgrade_suggestion"]
                }
            }
        )

    # 4. Allowed (ALLOW or WARN): Increment usage & record in Audit Log
    database.increment_usage(customer_id, endpoint)
    database.log_decision(
        customer_id=customer_id,
        plan_name=plan_name,
        endpoint=endpoint,
        decision=evaluation["decision"],
        reason=evaluation["reason"],
        current_usage=evaluation["current_usage"],
        limit_value=evaluation["limit"]
    )

    # 5. Forward request to the untouched Existing Notes App via httpx
    body_bytes = await request.body()
    transport = httpx.ASGITransport(app=demo_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://upstream") as client:
        upstream_Resp = await client.request(
            method=request.method,
            url=endpoint,
            content=body_bytes,
            params=request.query_params
        )

    upstream_json = upstream_Resp.json()

    # Attach PlanGate metadata so the customer sees 80% warnings clearly
    response_payload = {
        "plangate_meta": {
            "decision": evaluation["decision"],
            "plan": plan_name,
            "usage": f"{evaluation['current_usage']}/{evaluation['limit']}",
            "remaining_quota": evaluation["remaining"],
            "reset_at": evaluation["reset_at"],
            "message": evaluation["reason"],
            "upgrade_suggestion": evaluation["upgrade_suggestion"]
        },
        "upstream_response": upstream_json
    }

    if evaluation["decision"] == "WARN":
        quota_headers["X-PlanGate-Warning"] = evaluation["reason"]

    return JSONResponse(
        status_code=upstream_Resp.status_code,
        headers=quota_headers,
        content=response_payload
    )


# Serve the Dashboard at root "/" once static/index.html is created in Step 4
@app.get("/")
def serve_dashboard():
    if os.path.exists("static/index.html"):
        return FileResponse("static/index.html")
    return {
        "message": "PlanGate Gateway is running! Create static/index.html in Step 4 for the visual dashboard.",
        "try_endpoints": ["/direct/notes", "/forecast", "/logs"]
    }
