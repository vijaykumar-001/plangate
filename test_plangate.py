from fastapi.testclient import TestClient
import database
import engine
from main import app

client = TestClient(app)

def setup_function():
    """Reset counters before each test so tests are repeatable."""
    database.init_db()
    database.reset_all_usage()

def test_1_under_limit_allow():
    """Test that requests below 80% quota are ALLOWED and forwarded."""
    res = client.get("/gateway/export", headers={"X-API-Key": "pg_free_key_123"})
    assert res.status_code == 200
    assert res.headers["X-PlanGate-Decision"] == "ALLOW"
    assert res.headers["X-PlanGate-Remaining"] == "9"
    body = res.json()
    assert body["plangate_meta"]["decision"] == "ALLOW"
    assert "upstream_response" in body

def test_2_at_80_percent_warning():
    """Test that hitting 80% quota (call #8 out of 10 on Free plan) triggers WARN."""
    for _ in range(7):
        client.get("/gateway/export", headers={"X-API-Key": "pg_free_key_123"})

    # 8th call reaches 80% (8/10)
    res = client.get("/gateway/export", headers={"X-API-Key": "pg_free_key_123"})
    assert res.status_code == 200
    assert res.headers["X-PlanGate-Decision"] == "WARN"
    assert "X-PlanGate-Warning" in res.headers
    body = res.json()
    assert body["plangate_meta"]["decision"] == "WARN"
    assert "Upgrade" in body["plangate_meta"]["upgrade_suggestion"] or "upgrading" in body["plangate_meta"]["upgrade_suggestion"]

def test_3_at_100_percent_explainable_block():
    """Test that exceeding 100% quota (after 10 calls) returns HTTP 429 with Explainable Block."""
    for _ in range(10):
        client.get("/gateway/export", headers={"X-API-Key": "pg_free_key_123"})

    # 11th call must be blocked with explainable metadata
    res = client.get("/gateway/export", headers={"X-API-Key": "pg_free_key_123"})
    assert res.status_code == 429
    assert res.headers["X-PlanGate-Decision"] == "BLOCK"
    body = res.json()
    assert body["error"] == "PlanLimitExceeded"
    assert body["explainable_block"]["unblocking_plan"] == "Pro"
    assert "reset_date_utc" in body["explainable_block"]

def test_4_unknown_or_missing_api_key_security():
    """Test that missing or invalid API keys are rejected and hashed properly."""
    # Missing key -> 401
    res_missing = client.get("/gateway/export")
    assert res_missing.status_code == 401

    # Invalid key -> 403
    res_invalid = client.get("/gateway/export", headers={"X-API-Key": "invalid_key_999"})
    assert res_invalid.status_code == 403
    assert res_invalid.json()["decision"] == "BLOCK"

    # Verify SHA-256 hashing never stores raw key
    raw = "pg_free_key_123"
    assert database.hash_api_key(raw) != raw
    assert len(database.hash_api_key(raw)) == 64

def test_5_burn_rate_forecast():
    """Test that /forecast updates dynamically as usage increases."""
    client.get("/gateway/export", headers={"X-API-Key": "pg_free_key_123"})
    res = client.get("/forecast?endpoint=/export", headers={"X-API-Key": "pg_free_key_123"})
    assert res.status_code == 200
    data = res.json()
    assert data["current_usage"] == 1
    assert data["daily_burn_rate"] > 0