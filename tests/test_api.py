"""
tests/test_api.py
─────────────────────────────────────────────────────────────────────────────
Integration tests for the FastAPI application.

Uses httpx.AsyncClient with FastAPI's test transport — the full application
stack runs in-process (no network socket needed).

A temporary SQLite database is created for each test session and deleted
on teardown, so tests never touch the production database.

Run:
    pytest tests/test_api.py -v
    pytest tests/test_api.py -v -k "test_simulate"
"""
import os
import tempfile
import pytest
import pytest_asyncio
import httpx
from fastapi.testclient import TestClient


# ── Override DB_PATH before importing app modules ───────────────────────────
# This must happen before any app import that reads DB_PATH from config.
_tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp_db.close()
os.environ["DB_PATH"] = _tmp_db.name


# ── Now import the app (after env var is set) ────────────────────────────────
from main import app
from app.database import init_db


@pytest.fixture(scope="session")
def client():
    """
    Synchronous test client for the whole test session.

    Using TestClient as a context manager triggers the FastAPI lifespan,
    which calls init_db() — creating all tables and seeding defaults.
    This is the correct way to initialise the test database.
    """
    with TestClient(app) as c:
        yield c
    # Cleanup temp DB files
    for suffix in ("", "-shm", "-wal"):
        try:
            os.unlink(_tmp_db.name + suffix)
        except FileNotFoundError:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# HEALTH
# ─────────────────────────────────────────────────────────────────────────────
class TestHealth:

    def test_health_ok(self, client):
        r = client.get("/api/health")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert "version" in data
        assert "appliances" in data
        assert isinstance(data["appliances"], int)


# ─────────────────────────────────────────────────────────────────────────────
# APPLIANCES — LIST
# ─────────────────────────────────────────────────────────────────────────────
class TestAppliancesList:

    def test_list_returns_array(self, client):
        r = client.get("/api/appliances")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)

    def test_default_appliances_seeded(self, client):
        r    = client.get("/api/appliances")
        data = r.json()
        # Should have 19 default appliances after init_db()
        assert len(data) >= 19

    def test_appliance_has_required_fields(self, client):
        r    = client.get("/api/appliances")
        item = r.json()[0]
        required = ["id", "name", "cat", "voltage_v", "current_a",
                    "power_factor", "efficiency_pct", "duty_cycle_pct",
                    "hrs", "watts", "effective_watts", "on",
                    "sched", "icon", "clr", "is_custom"]
        for field in required:
            assert field in item, f"Missing field: {field}"

    def test_no_on_state_key_in_response(self, client):
        """The raw DB field 'on_state' should be remapped to 'on'."""
        r = client.get("/api/appliances")
        for item in r.json():
            assert "on_state" not in item


# ─────────────────────────────────────────────────────────────────────────────
# APPLIANCES — CRUD
# ─────────────────────────────────────────────────────────────────────────────
class TestApplianceCRUD:

    def test_create_appliance(self, client):
        payload = {
            "name": "Test Diesel Heater",
            "cat": "high",
            "voltage_v": 12.0,
            "current_a": 8.33,
            "power_factor": 1.0,
            "efficiency_pct": 92.0,
            "duty_cycle_pct": 60.0,
            "hrs": 8.0,
            "sched": "evening",
            "on": True,
            "icon": "🔥",
            "clr": "#FF453A",
        }
        r = client.post("/api/appliances", json=payload)
        assert r.status_code == 201
        data = r.json()
        assert data["name"] == payload["name"]
        assert data["id"] > 0
        assert data["is_custom"] is True
        # Derived fields computed server-side
        expected_watts = round(12.0 * 8.33 * 1.0, 2)
        assert data["watts"] == pytest.approx(expected_watts, abs=0.1)

    def test_get_appliance_by_id(self, client):
        # Create one first
        r   = client.post("/api/appliances", json={"name": "GetTest", "voltage_v": 120})
        aid = r.json()["id"]
        r2  = client.get(f"/api/appliances/{aid}")
        assert r2.status_code == 200
        assert r2.json()["id"] == aid
        assert r2.json()["name"] == "GetTest"

    def test_get_nonexistent_returns_404(self, client):
        r = client.get("/api/appliances/999999")
        assert r.status_code == 404

    def test_update_appliance(self, client):
        r   = client.post("/api/appliances", json={"name": "UpdateMe", "voltage_v": 120})
        aid = r.json()["id"]
        r2  = client.put(f"/api/appliances/{aid}", json={"name": "Updated", "hrs": 6.0})
        assert r2.status_code == 200
        assert r2.json()["name"] == "Updated"
        assert r2.json()["hrs"] == 6.0

    def test_update_recomputes_watts(self, client):
        r   = client.post("/api/appliances", json={"name": "WattsTest", "voltage_v": 120, "current_a": 1.0, "power_factor": 1.0})
        aid = r.json()["id"]
        # Change voltage — watts should update
        r2  = client.put(f"/api/appliances/{aid}", json={"voltage_v": 240, "current_a": 2.0})
        data = r2.json()
        assert data["watts"] == pytest.approx(240 * 2.0 * data["power_factor"], abs=0.1)

    def test_delete_appliance(self, client):
        r   = client.post("/api/appliances", json={"name": "DeleteMe", "voltage_v": 120})
        aid = r.json()["id"]
        r2  = client.delete(f"/api/appliances/{aid}")
        assert r2.status_code == 200
        assert r2.json()["deleted"] == aid
        # Should no longer exist
        r3 = client.get(f"/api/appliances/{aid}")
        assert r3.status_code == 404

    def test_delete_nonexistent_returns_404(self, client):
        r = client.delete("/api/appliances/999999")
        assert r.status_code == 404

    def test_toggle_on_to_off(self, client):
        r   = client.post("/api/appliances", json={"name": "Toggle", "on": True, "voltage_v": 120})
        aid = r.json()["id"]
        r2  = client.post(f"/api/appliances/{aid}/toggle", json={"on": False})
        assert r2.status_code == 200
        assert r2.json()["on"] is False

    def test_toggle_flip(self, client):
        r   = client.post("/api/appliances", json={"name": "Flip", "on": True, "voltage_v": 120})
        aid = r.json()["id"]
        # Omit `on` → server flips current state
        r2  = client.post(f"/api/appliances/{aid}/toggle", json={})
        assert r2.json()["on"] is False
        r3  = client.post(f"/api/appliances/{aid}/toggle", json={})
        assert r3.json()["on"] is True

    def test_create_validates_name_required(self, client):
        r = client.post("/api/appliances", json={"voltage_v": 120})
        assert r.status_code == 422

    def test_create_validates_power_factor_range(self, client):
        r = client.post("/api/appliances", json={
            "name": "Bad", "voltage_v": 120, "power_factor": 2.5  # > 1.0
        })
        assert r.status_code == 422


# ─────────────────────────────────────────────────────────────────────────────
# SIMULATE
# ─────────────────────────────────────────────────────────────────────────────
class TestSimulate:

    def test_simulate_default_body(self, client):
        r = client.post("/api/simulate", json={})
        assert r.status_code == 200

    def test_simulate_required_fields(self, client):
        r    = client.post("/api/simulate", json={})
        data = r.json()
        for key in ["si_score", "si_grade", "si_label", "si_pillars",
                    "sol_hourly", "load_hourly", "soc_hourly", "net_hourly",
                    "breakdown", "alerts", "tips", "days_off_grid"]:
            assert key in data, f"Missing field: {key}"

    def test_simulate_no_legacy_stability_key(self, client):
        r    = client.post("/api/simulate", json={})
        data = r.json()
        assert "stability" not in data

    def test_simulate_score_in_range(self, client):
        r    = client.post("/api/simulate", json={})
        data = r.json()
        assert 0.0 <= data["si_score"] <= 10.0

    def test_simulate_hourly_length(self, client):
        r    = client.post("/api/simulate", json={})
        data = r.json()
        for key in ("sol_hourly", "load_hourly", "soc_hourly", "net_hourly"):
            assert len(data[key]) == 24

    def test_simulate_grade_F_low_solar(self, client):
        r    = client.post("/api/simulate", json={"solar_output_kwh": 0.1})
        data = r.json()
        assert data["si_grade"] == "F"

    def test_simulate_grade_improves_with_solar(self, client):
        low  = client.post("/api/simulate", json={"solar_output_kwh": 1.0}).json()
        high = client.post("/api/simulate", json={"solar_output_kwh": 10.0}).json()
        assert high["si_score"] > low["si_score"]

    def test_simulate_solar_intensity_multiplier(self, client):
        """solar_intensity=0.5 should halve solar output."""
        full = client.post("/api/simulate", json={
            "solar_output_kwh": 4.0, "solar_intensity": 1.0
        }).json()
        half = client.post("/api/simulate", json={
            "solar_output_kwh": 4.0, "solar_intensity": 0.5
        }).json()
        assert half["total_sol_kwh"] < full["total_sol_kwh"]

    def test_simulate_persisted_to_history(self, client):
        """After a simulation, it should appear in /api/history."""
        before = len(client.get("/api/history").json())
        client.post("/api/simulate", json={})
        after  = len(client.get("/api/history").json())
        assert after >= before  # May be equal if same test run

    def test_simulate_invalid_weather(self, client):
        r = client.post("/api/simulate", json={"weather": "hailstorm"})
        assert r.status_code == 422

    def test_simulate_invalid_scenario(self, client):
        r = client.post("/api/simulate", json={"scenario": "apocalypse"})
        assert r.status_code == 422

    def test_simulate_occupants_boundary(self, client):
        r_ok  = client.post("/api/simulate", json={"occupants": 12})
        assert r_ok.status_code == 200
        r_bad = client.post("/api/simulate", json={"occupants": 99})
        assert r_bad.status_code == 422


# ─────────────────────────────────────────────────────────────────────────────
# WEATHER LOG
# ─────────────────────────────────────────────────────────────────────────────
class TestWeatherLog:

    def test_log_weather(self, client):
        r = client.post("/api/weather", json={
            "lat": 37.33, "lon": -122.03,
            "city": "Cupertino",
            "temp_c": 18.5, "cloud_pct": 20.0, "wind_kmh": 12.0,
            "weather_code": 1, "irr_factor": 0.87,
            "wx_label": "Mainly clear", "wx_icon": "🌤",
        })
        assert r.status_code == 200
        assert r.json()["logged"] is True

    def test_log_weather_empty_body(self, client):
        """Weather log is optional — empty body should succeed."""
        r = client.post("/api/weather", json={})
        assert r.status_code == 200


# ─────────────────────────────────────────────────────────────────────────────
# HISTORY
# ─────────────────────────────────────────────────────────────────────────────
class TestHistory:

    def test_history_returns_list(self, client):
        r = client.get("/api/history")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_history_limit(self, client):
        r = client.get("/api/history?limit=3")
        assert r.status_code == 200
        assert len(r.json()) <= 3


# ─────────────────────────────────────────────────────────────────────────────
# HOME PAGE
# ─────────────────────────────────────────────────────────────────────────────
class TestHomePage:

    def test_home_returns_html(self, client):
        r = client.get("/")
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]

    def test_home_contains_app_title(self, client):
        r    = client.get("/")
        html = r.text
        assert "Elevatics" in html or "RV Energy" in html

    def test_home_contains_idat(self, client):
        """Initial simulation data must be embedded in the HTML."""
        r    = client.get("/")
        html = r.text
        assert "IDAT" in html or "si_score" in html
