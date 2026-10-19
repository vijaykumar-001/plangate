from datetime import datetime, timezone, timedelta
import calendar

# Zero-code retrofit plan configuration per endpoint per month
PLANS = {
    "Free": {
        "price_monthly": 0,
        "limits": {
            "/notes": 20,
            "/export": 10  # 10 exports/month: 1-7 Allow, 8-9 Warn (>=80%), 10 Block (100%)
        },
        "next_tier": "Pro"
    },
    "Pro": {
        "price_monthly": 49,
        "limits": {
            "/notes": 500,
            "/export": 100
        },
        "next_tier": None
    }
}

def get_reset_date_iso() -> str:
    """Calculate the first day of next month at 00:00 UTC."""
    now = datetime.now(timezone.utc)
    if now.month == 12:
        next_month = datetime(now.year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        next_month = datetime(now.year, now.month + 1, 1, tzinfo=timezone.utc)
    return next_month.strftime("%Y-%m-%dT00:00:00Z")

def find_unblocking_plan(endpoint: str, current_usage: int) -> dict:
    """Find which higher tier plan would immediately unblock the customer."""
    for plan_name, details in PLANS.items():
        limit = details["limits"].get(endpoint, 1000)
        if limit > current_usage:
            return {
                "recommended_plan": plan_name,
                "new_limit": limit,
                "monthly_price_usd": details["price_monthly"]
            }
    return {"recommended_plan": "Enterprise Custom", "new_limit": "Unlimited", "monthly_price_usd": 199}

def evaluate_request(plan_name: str, endpoint: str, current_usage: int) -> dict:
    """
    Pure entitlement decision engine:
    - BLOCK at 100% (current_usage >= limit)
    - WARN at >= 80% (current_usage / limit >= 0.8)
    - ALLOW below 80%
    """
    if plan_name not in PLANS:
        return {
            "allowed": False,
            "decision": "BLOCK",
            "reason": f"Invalid or unrecognized plan '{plan_name}'.",
            "current_usage": current_usage,
            "limit": 0,
            "remaining": 0,
            "reset_at": get_reset_date_iso(),
            "upgrade_suggestion": None
        }

    plan_limits = PLANS[plan_name]["limits"]
    limit = plan_limits.get(endpoint, 50)
    reset_at = get_reset_date_iso()

    # 1. Check 100% Block condition
    if current_usage >= limit:
        upgrade = find_unblocking_plan(endpoint, current_usage)
        return {
            "allowed": False,
            "decision": "BLOCK",
            "reason": f"Monthly quota of {limit} calls for '{endpoint}' on the {plan_name} plan has been exhausted (100% used).",
            "current_usage": current_usage,
            "limit": limit,
            "remaining": 0,
            "reset_at": reset_at,
            "upgrade_suggestion": (
                f"Upgrade to the {upgrade['recommended_plan']} plan (${upgrade['monthly_price_usd']}/mo) "
                f"to immediately increase your '{endpoint}' limit to {upgrade['new_limit']} calls/month."
            ),
            "unblocking_plan": upgrade["recommended_plan"]
        }

    # If allowed, calculate post-request usage percentage
    new_usage = current_usage + 1
    remaining = max(0, limit - new_usage)
    usage_ratio = current_usage / limit

    # 2. Check 80% Warning condition ( triggers when current usage is >= 80% or new usage reaches >= 80%)
    if usage_ratio >= 0.8 or (new_usage / limit) >= 0.8:
        upgrade = find_unblocking_plan(endpoint, limit)
        return {
            "allowed": True,
            "decision": "WARN",
            "reason": f"Warning: You have used {new_usage}/{limit} ({int((new_usage/limit)*100)}%) of your '{endpoint}' quota on the {plan_name} plan.",
            "current_usage": new_usage,
            "limit": limit,
            "remaining": remaining,
            "reset_at": reset_at,
            "upgrade_suggestion": f"Consider upgrading to {upgrade['recommended_plan']} (${upgrade['monthly_price_usd']}/mo) for {upgrade['new_limit']} calls/month before hitting a hard block."
        }

    # 3. Standard Allow (< 80%)
    return {
        "allowed": True,
        "decision": "ALLOW",
        "reason": f"Within {plan_name} plan limits ({new_usage}/{limit} used).",
        "current_usage": new_usage,
        "limit": limit,
        "remaining": remaining,
        "reset_at": reset_at,
        "upgrade_suggestion": None
    }

def calculate_burn_rate_forecast(plan_name: str, endpoint: str, current_usage: int) -> dict:
    """
    Phase 5: Burn-rate forecast.
    Calculates daily usage pace and predicts when the customer will hit 100% of their limit.
    """
    now = datetime.now(timezone.utc)
    days_elapsed = max(1, now.day)
    _, total_days_in_month = calendar.monthrange(now.year, now.month)
    days_remaining_in_month = max(0, total_days_in_month - now.day)

    limit = PLANS.get(plan_name, PLANS["Free"])["limits"].get(endpoint, 10)
    daily_burn_rate = round(current_usage / days_elapsed, 2)

    if current_usage >= limit:
        return {
            "endpoint": endpoint,
            "plan": plan_name,
            "current_usage": current_usage,
            "limit": limit,
            "daily_burn_rate": daily_burn_rate,
            "status": "EXHAUSTED",
            "days_until_limit": 0,
            "projected_exhaustion_date": now.strftime("%Y-%m-%d"),
            "message": f"Limit already reached ({current_usage}/{limit}). Upgrade to Pro to resume traffic immediately."
        }

    if daily_burn_rate == 0:
        return {
            "endpoint": endpoint,
            "plan": plan_name,
            "current_usage": current_usage,
            "limit": limit,
            "daily_burn_rate": 0.0,
            "status": "SAFE",
            "days_until_limit": None,
            "projected_exhaustion_date": None,
            "message": "No usage recorded yet this period. You are well within your monthly limit."
        }

    remaining_quota = limit - current_usage
    days_until_limit = round(remaining_quota / daily_burn_rate, 1)
    projected_date = (now + timedelta(days=days_until_limit)).strftime("%Y-%m-%d")

    if days_until_limit <= days_remaining_in_month:
        upgrade = find_unblocking_plan(endpoint, limit)
        return {
            "endpoint": endpoint,
            "plan": plan_name,
            "current_usage": current_usage,
            "limit": limit,
            "daily_burn_rate": daily_burn_rate,
            "status": "AT_RISK",
            "days_until_limit": days_until_limit,
            "projected_exhaustion_date": projected_date,
            "message": (
                f"At your current pace ({daily_burn_rate} calls/day), you will hit your {plan_name} limit "
                f"in {days_until_limit} days ({projected_date}). Upgrade to {upgrade['recommended_plan']} "
                f"for {upgrade['new_limit']} calls/month."
            )
        }

    return {
        "endpoint": endpoint,
        "plan": plan_name,
        "current_usage": current_usage,
        "limit": limit,
        "daily_burn_rate": daily_burn_rate,
        "status": "SAFE",
        "days_until_limit": days_until_limit,
        "projected_exhaustion_date": projected_date,
        "message": f"Safe pace ({daily_burn_rate} calls/day). Projected to stay within your {limit} call limit this month."
    }