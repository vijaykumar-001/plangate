# PlanGate — Zero-Code API Entitlement Gateway

> **Add plans, usage limits, explainable blocks, and burn-rate forecasts to any existing API in minutes, with zero code changes.**

Built for **ADVANTIX HACKATHON 2026** (Department of AI & ML, Rajalakshmi Engineering College, in collaboration with Advantix AGI LLP & IEEE CIS).

---

## 1. Problem & Solution

Modern entitlement and metering tools (Stigg, Orb, Metronome, Lago) expect engineering teams to weave SDKs and entitlement checks directly into application code while building a product from scratch.
- **Retrofitting existing or legacy APIs is painful** because it requires modifying and redeploying upstream services.
- **Opaque errors:** Blocked users receive a generic `429 Too Many Requests` or `403 Forbidden` with zero explanation of *why*, *when their quota resets*, or *which plan unblocks them*.
- **Zero early warning:** Customers hit hard walls unexpectedly without knowing their daily burn rate.

**PlanGate** solves this by acting as a drop-in reverse proxy gateway placed in front of any existing API:
1. **Zero-Code Retrofit:** Limits are defined per endpoint in config; the upstream microservice remains 100% untouched.
2. **Explainable Decisions:** Every warning (at 80%) and block (at 100%) returns structured reasons, UTC reset timestamps, standard quota headers (`X-PlanGate-*`), and the exact plan tier required to unblock traffic.
3. **Burn-Rate Forecast:** Calculates real-time daily usage velocity and predicts the exact date a customer will exhaust their quota.

---

## 2. Market Gap Comparison

| Capability | Generic API gateways (Kong, NGINX) | Entitlement and billing platforms (Stigg, Orb, Lago) | **PlanGate** |
| --- | --- | --- | --- |
| Works in front of an existing API without app code changes | ✅ Yes | Usually needs SDK or sidecar integration | **✅ Yes** |
| Plan-based rules per endpoint (Free, Pro) | Possible with custom plugins and config | ✅ Yes | **✅ Built in** |
| Explainable blocks (reason, reset time, plan to unblock) | Typically a plain 429 unless customized | Product team builds this in their own UI | **✅ Built into the response** |
| Warning before the limit (80%) | Not standard | Needs alert or webhook setup | **✅ Automatic** |
| Burn-rate forecast of when the quota runs out | Not standard | Varies by vendor | **✅ Built-in `/forecast`** |

PlanGate's focus is combining all five in one drop-in layer for existing APIs.

---

## 3. Architecture

```text
+-------------------+       X-API-Key        +------------------------------------------------+
|   Client / App    | ---------------------> |          PlanGate Gateway (FastAPI)            |
+-------------------+                        |                                                |
         ^                                   |  1. SHA-256 Key Auth    2. Entitlement Engine  |
         |                                   |     & Input Validation     (<80% Allow,        |
         | Explainable JSON +                |                            >=80% Warn,         |
         | X-PlanGate-* Headers              |  3. Burn-Rate Forecast     100% Block)         |
         +---------------------------------- +----------------------+-------------------------+
                                                                    |
                                           +------------------------+------------------------+
                                           |                                                 |
                                           v (SQLite Persistence)                            v (httpx Proxy if Allowed)
                            +------------------------------+                  +------------------------------+
                            |      plangate.db (SQLite)    |                  |   Untouched Existing App     |
                            | - Hashed Customer Keys       |                  |   (Demo Notes & Export API)  |
                            | - Monthly Usage Counters     |                  |   Zero limit/plan code inside|
                            | - Explainable Audit Logs     |                  +------------------------------+
                            +------------------------------+
```

## 4. Main API Reference
Method
Endpoint
Description
GET
/
Interactive Chart.js Dashboard, Live Traffic Simulator, Forecast Cards & Audit Log UI
ANY
/gateway/{path}
Zero-code entitlement proxy. Authenticates X-API-Key, enforces plan limits, injects X-PlanGate-* headers, and forwards allowed requests to the upstream API
GET
/forecast?endpoint=/export
Returns daily burn rate, remaining quota, and projected exhaustion date for the authenticated customer
GET
/logs
Returns real-time usage summary across plans and the latest 30 audit log entries
POST
/admin/reset
Resets demo counters and audit logs for live evaluation
GET
/direct/notes
Direct access to the untouched upstream Notes API (demonstrates zero limit logic inside the existing app)

## 5. Security & Testing Highlights
SHA-256 API Key Hashing: Raw API keys (pg_free_key_123, pg_pro_key_999) are never stored in plain text in SQLite; only SHA-256 digests (api_key_hash) are persisted and queried.

Server-Side Plan Enforcement: Client requests cannot spoof plan names; plans are resolved strictly from the authenticated key hash.

Automated pytest Suite (test_plangate.py): Verifies under-limit forwarding, 80% warning threshold, 100% HTTP 429 explainable block, invalid/missing key rejection, and burn-rate math.

## 6. Future Scope
Distributed Redis Counters: Sub-millisecond atomic counters across multi-region gateway nodes.

Multi-Tenant Self-Serve Portal: Allow B2B SaaS admins to configure endpoints and pricing tiers dynamically via UI.

Webhook Alerts & Stripe Billing Sync: Trigger Slack/email webhooks at 80% usage and one-click Stripe checkout links inside 429 responses.
