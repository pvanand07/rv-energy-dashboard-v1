"""
tests/test_simulation.py
─────────────────────────────────────────────────────────────────────────────
Unit tests for app/simulation.py — the 2880-step energy simulation engine.

These tests are fully isolated: no database, no HTTP, no filesystem.
They pass a minimal appliance list into run_simulation() and verify that
the output fields are within physically correct ranges.

Run:
    pytest tests/test_simulation.py -v
"""
import math
import pytest
from app.simulation import run_simulation, solar_curve, app_duty


# ── Minimal fixture appliances ────────────────────────────────────────────────
def _make_app(id_=1, name="Test", watts=100.0, eff=100.0, dc=100.0,
              hrs=24.0, sched="24h", on=True):
    """Helper to build a minimal appliance dict for simulation input."""
    return {
        "id": id_, "name": name, "cat": "low",
        "voltage_v": 120.0, "current_a": watts / 120.0, "power_factor": 1.0,
        "efficiency_pct": eff, "duty_cycle_pct": dc, "hrs": hrs,
        "watts": watts, "effective_watts": round(watts / (eff / 100), 2),
        "on": on, "sched": sched, "icon": "🔌", "clr": "#0A84FF",
    }


BASE_CFG = {
    "battery_capacity_kwh": 45.0,
    "starting_soc": 0.87,
    "solar_output_kwh": 2.0,
    "weather": "sunny",
    "scenario": "expected",
    "occupants": 2,
    "experience": "normal",
    "load_factor": 1.0,
    "temperature_c": 22.0,
    "irradiance_factor": 1.0,
}


# ─────────────────────────────────────────────────────────────────────────────
# SOLAR CURVE
# ─────────────────────────────────────────────────────────────────────────────
class TestSolarCurve:

    def test_zero_before_dawn(self):
        assert solar_curve(5.99) == 0.0

    def test_zero_after_dusk(self):
        assert solar_curve(20.01) == 0.0

    def test_peaks_at_noon(self):
        """Peak at solar noon = midpoint of [6, 20] = 13:00."""
        assert solar_curve(13.0) == pytest.approx(1.0, abs=0.001)

    def test_non_negative(self):
        for h in [x * 0.5 for x in range(48)]:
            assert solar_curve(h) >= 0.0

    def test_symmetry(self):
        """Curve should be symmetric around solar noon (h=13)."""
        for offset in [1.0, 2.0, 3.5]:
            left  = solar_curve(13.0 - offset)
            right = solar_curve(13.0 + offset)
            assert left == pytest.approx(right, abs=0.001)


# ─────────────────────────────────────────────────────────────────────────────
# SCHEDULE DUTY
# ─────────────────────────────────────────────────────────────────────────────
class TestAppDuty:

    def test_24h_always_on(self):
        for s in range(0, 2880, 100):
            assert app_duty("24h", s, 24.0, 2) == 1.0

    def test_cycle_on_phase(self):
        """First 22 of every 90 steps should return 3.5."""
        assert app_duty("cycle", 0, 24.0, 2) == 3.5
        assert app_duty("cycle", 21, 24.0, 2) == 3.5
        assert app_duty("cycle", 22, 24.0, 2) == pytest.approx(0.06)

    def test_morning_only_daytime(self):
        """Morning schedule: active only 6:00–9:00."""
        # step 720 = 6.0h exactly
        assert app_duty("morning", 720, 24.0, 2) == pytest.approx(0.60)
        # step 1080 = 9.0h (exclusive boundary)
        assert app_duty("morning", 1080, 24.0, 2) == 0.0
        # nighttime
        assert app_duty("morning", 0, 24.0, 2) == 0.0

    def test_once_single_block(self):
        """Once schedule: on from step 360 for hrs×120 steps."""
        hrs = 0.75
        s0, se = 360, 360 + int(hrs * 120)  # 360 to 450
        assert app_duty("once", s0,   hrs, 2) == 1.0
        assert app_duty("once", se-1, hrs, 2) == 1.0
        assert app_duty("once", se,   hrs, 2) == 0.0
        assert app_duty("once", 0,    hrs, 2) == 0.0


# ─────────────────────────────────────────────────────────────────────────────
# RUN SIMULATION — OUTPUT STRUCTURE
# ─────────────────────────────────────────────────────────────────────────────
class TestSimulationStructure:

    def test_required_keys_present(self):
        apps   = [_make_app()]
        result = run_simulation({**BASE_CFG, "appliances": apps})
        required = [
            "soc_pct", "soc_kwh", "bat_cap", "bat_temp_factor",
            "tte", "tte_ok", "sol_now", "ld_now", "net_now",
            "si_score", "si_grade", "si_label", "si_color", "si_pillars",
            "days_off_grid", "total_load_kwh", "total_sol_kwh", "bat_draw_kwh",
            "min_soc", "min_soc_h", "peak_load_kw", "sol_coverage_pct",
            "sol_hourly", "load_hourly", "soc_hourly", "net_hourly",
            "breakdown", "alerts", "tips",
            "scenario", "weather", "occupants", "experience", "temperature_c",
            "ms",
        ]
        for key in required:
            assert key in result, f"Missing key: {key}"

    def test_no_legacy_stability_key(self):
        """The old 'stability' field must not be present."""
        apps   = [_make_app()]
        result = run_simulation({**BASE_CFG, "appliances": apps})
        assert "stability" not in result, "Legacy 'stability' field must be removed"

    def test_hourly_arrays_length_24(self):
        apps   = [_make_app()]
        result = run_simulation({**BASE_CFG, "appliances": apps})
        for key in ("sol_hourly", "load_hourly", "soc_hourly", "net_hourly"):
            assert len(result[key]) == 24, f"{key} must have 24 entries"

    def test_si_pillars_structure(self):
        apps   = [_make_app()]
        result = run_simulation({**BASE_CFG, "appliances": apps})
        pillars = result["si_pillars"]
        assert set(pillars.keys()) == {"p1", "p1_max", "p2", "p2_max", "p3", "p3_max", "p4", "p4_max"}
        assert pillars["p1_max"] == 3.5
        assert pillars["p2_max"] == 3.0
        assert pillars["p3_max"] == 2.0
        assert pillars["p4_max"] == 1.5

    def test_min_soc_h_valid_hour(self):
        apps   = [_make_app()]
        result = run_simulation({**BASE_CFG, "appliances": apps})
        assert 0 <= result["min_soc_h"] <= 23


# ─────────────────────────────────────────────────────────────────────────────
# SOLAR ACCURACY
# ─────────────────────────────────────────────────────────────────────────────
class TestSolarAccuracy:

    def test_total_solar_matches_target(self):
        """
        The simulation must generate exactly the target kWh (± 2%).
        This verifies the normalisation integral is correct.
        """
        for target in (1.0, 2.0, 5.0, 8.0):
            result = run_simulation({
                **BASE_CFG,
                "appliances": [],        # no load → pure solar test
                "solar_output_kwh": target,
            })
            assert result["total_sol_kwh"] == pytest.approx(target, rel=0.02), \
                f"Solar target {target} kWh: got {result['total_sol_kwh']}"

    def test_no_solar_at_night(self):
        """Hours 0–5 and 21–23 must have zero solar."""
        result = run_simulation({**BASE_CFG, "appliances": []})
        sol_h = result["sol_hourly"]
        for h in list(range(0, 6)) + list(range(21, 24)):
            assert sol_h[h] == pytest.approx(0.0, abs=0.001), \
                f"Solar must be 0 at hour {h}, got {sol_h[h]}"

    def test_solar_peaks_midday(self):
        """Solar should be highest around 13:00."""
        result = run_simulation({**BASE_CFG, "appliances": []})
        sol_h  = result["sol_hourly"]
        peak_h = sol_h.index(max(sol_h))
        assert 11 <= peak_h <= 15, f"Solar peak at hour {peak_h}, expected 11–15"

    def test_irradiance_factor_scales_solar(self):
        """irradiance_factor=0.5 should halve total solar generation."""
        full = run_simulation({**BASE_CFG, "appliances": [], "irradiance_factor": 1.0})
        half = run_simulation({**BASE_CFG, "appliances": [], "irradiance_factor": 0.5})
        assert half["total_sol_kwh"] == pytest.approx(full["total_sol_kwh"] * 0.5, rel=0.02)

    def test_weather_rainy_reduces_solar(self):
        """Rainy weather (factor 0.05) must drastically reduce solar."""
        sunny = run_simulation({**BASE_CFG, "appliances": [], "weather": "sunny"})
        rainy = run_simulation({**BASE_CFG, "appliances": [], "weather": "rainy"})
        assert rainy["total_sol_kwh"] < sunny["total_sol_kwh"] * 0.10


# ─────────────────────────────────────────────────────────────────────────────
# BATTERY MODEL
# ─────────────────────────────────────────────────────────────────────────────
class TestBatteryModel:

    def test_soc_never_negative(self):
        """Battery SOC must never go below 0%."""
        apps = [_make_app(watts=5000.0, hrs=24.0)]  # massive drain
        result = run_simulation({**BASE_CFG, "appliances": apps, "solar_output_kwh": 0.0})
        assert all(s >= 0.0 for s in result["soc_hourly"]), "SOC went negative"

    def test_soc_never_exceeds_100(self):
        """Battery SOC must never exceed 100%."""
        apps = [_make_app(watts=1.0)]  # negligible load
        result = run_simulation({
            **BASE_CFG, "appliances": apps,
            "solar_output_kwh": 100.0,    # massive solar surplus
            "starting_soc": 0.50,
        })
        assert all(s <= 100.1 for s in result["soc_hourly"]), "SOC exceeded 100%"

    def test_temperature_derating_cold(self):
        """Cold temperature should reduce battery temp factor."""
        warm = run_simulation({**BASE_CFG, "appliances": [], "temperature_c": 25.0})
        cold = run_simulation({**BASE_CFG, "appliances": [], "temperature_c": 5.0})
        assert cold["bat_temp_factor"] < warm["bat_temp_factor"]
        assert cold["bat_temp_factor"] == pytest.approx(0.85, abs=0.01)

    def test_temperature_derating_severe(self):
        warm = run_simulation({**BASE_CFG, "appliances": [], "temperature_c": 25.0})
        frz  = run_simulation({**BASE_CFG, "appliances": [], "temperature_c": -5.0})
        assert frz["bat_temp_factor"] == pytest.approx(0.70, abs=0.01)

    def test_higher_load_reduces_autonomy(self):
        light  = run_simulation({**BASE_CFG, "appliances": [_make_app(watts=100.0)]})
        heavy  = run_simulation({**BASE_CFG, "appliances": [_make_app(watts=2000.0)]})
        assert heavy["days_off_grid"] < light["days_off_grid"]


# ─────────────────────────────────────────────────────────────────────────────
# STABILITY SCORE INTEGRATION
# ─────────────────────────────────────────────────────────────────────────────
class TestStabilityIntegration:

    def test_score_in_range(self):
        apps   = [_make_app()]
        result = run_simulation({**BASE_CFG, "appliances": apps})
        assert 0.0 <= result["si_score"] <= 10.0

    def test_grade_F_with_default_config(self):
        """
        Default: 2 kWh solar vs ~13 kWh load → very low solar coverage
        + peak load > 5 kW threshold → Grade F expected.
        """
        from app.simulation import run_simulation as rs
        from app.database import _default_appliances
        apps = _default_appliances()
        result = rs({**BASE_CFG, "appliances": apps})
        # With only 2 kWh/day solar and heavy load, score should be low
        assert result["si_score"] < 5.0
        assert result["si_grade"] == "F"

    def test_more_solar_improves_score(self):
        apps  = [_make_app(watts=500.0)]
        low   = run_simulation({**BASE_CFG, "appliances": apps, "solar_output_kwh": 1.0})
        high  = run_simulation({**BASE_CFG, "appliances": apps, "solar_output_kwh": 10.0})
        assert high["si_score"] > low["si_score"]

    def test_worst_scenario_lower_than_best(self):
        apps = [_make_app()]
        best  = run_simulation({**BASE_CFG, "appliances": apps, "scenario": "best"})
        worst = run_simulation({**BASE_CFG, "appliances": apps, "scenario": "worst"})
        assert worst["si_score"] <= best["si_score"]


# ─────────────────────────────────────────────────────────────────────────────
# APPLIANCE BREAKDOWN
# ─────────────────────────────────────────────────────────────────────────────
class TestApplianceBreakdown:

    def test_off_appliance_excluded_from_breakdown(self):
        apps = [
            _make_app(id_=1, name="On",  watts=500.0, on=True),
            _make_app(id_=2, name="Off", watts=500.0, on=False),
        ]
        result = run_simulation({**BASE_CFG, "appliances": apps})
        names  = [a["name"] for a in result["breakdown"]]
        assert "On"  in names
        assert "Off" not in names

    def test_breakdown_sorted_by_kwh_descending(self):
        apps = [
            _make_app(id_=1, name="Small", watts=50.0),
            _make_app(id_=2, name="Large", watts=2000.0),
        ]
        result = run_simulation({**BASE_CFG, "appliances": apps})
        kwhs   = [a["daily_kwh"] for a in result["breakdown"]]
        assert kwhs == sorted(kwhs, reverse=True)

    def test_share_pcts_sum_to_100(self):
        apps = [_make_app(id_=i, watts=100.0) for i in range(1, 5)]
        result = run_simulation({**BASE_CFG, "appliances": apps})
        total  = sum(a["share_pct"] for a in result["breakdown"])
        assert total == pytest.approx(100.0, abs=1.0)

    def test_is_critical_flag(self):
        apps = [
            _make_app(id_=1, name="Normal",   watts=500.0),
            _make_app(id_=2, name="Critical", watts=2000.0),
        ]
        result = run_simulation({**BASE_CFG, "appliances": apps})
        by_name = {a["name"]: a for a in result["breakdown"]}
        assert by_name["Normal"]["is_critical"]   is False
        assert by_name["Critical"]["is_critical"] is True


# ─────────────────────────────────────────────────────────────────────────────
# ALERTS
# ─────────────────────────────────────────────────────────────────────────────
class TestAlerts:

    def test_at_least_one_alert_always(self):
        result = run_simulation({**BASE_CFG, "appliances": []})
        assert len(result["alerts"]) >= 1

    def test_critical_battery_alert(self):
        result = run_simulation({
            **BASE_CFG, "appliances": [],
            "starting_soc": 0.10,  # 10% — critically low
        })
        sevs = [a["sev"] for a in result["alerts"]]
        assert "critical" in sevs

    def test_rainy_weather_info_alert(self):
        result = run_simulation({**BASE_CFG, "appliances": [], "weather": "rainy"})
        msgs = [a["msg"] for a in result["alerts"]]
        assert any("rainy" in m.lower() or "solar minimal" in m.lower() for m in msgs)

    def test_alert_severity_values(self):
        result = run_simulation({**BASE_CFG, "appliances": []})
        valid  = {"info", "warning", "critical"}
        for a in result["alerts"]:
            assert a["sev"] in valid, f"Invalid severity: {a['sev']}"


# ─────────────────────────────────────────────────────────────────────────────
# PERFORMANCE
# ─────────────────────────────────────────────────────────────────────────────
class TestPerformance:

    def test_simulation_completes_within_500ms(self):
        """Full 2880-step simulation must complete in < 500 ms."""
        from app.database import _default_appliances
        apps   = _default_appliances()
        result = run_simulation({**BASE_CFG, "appliances": apps})
        assert result["ms"] < 500, f"Simulation too slow: {result['ms']} ms"

    def test_ms_field_is_positive(self):
        result = run_simulation({**BASE_CFG, "appliances": []})
        assert result["ms"] > 0
