"""
app/stability.py
─────────────────────────────────────────────────────────────────────────────
Stability Score computation — the single most important number in the system.

OVERVIEW
────────
The Stability Score (0.0 – 10.0) is a composite index that answers:
"How healthy and sustainable is this RV energy system RIGHT NOW?"

It is computed from four independent pillars, each measuring a different
dimension of energy safety. The pillars are weighted by their practical
importance to an RV traveller:

    Pillar              Max pts   Weight   Primary question
    ────────────────────────────────────────────────────────────────────────
    P1 Energy Autonomy  3.5 pts   35%      How many days can I survive?
    P2 Solar Coverage   3.0 pts   30%      Is the sun keeping up?
    P3 Peak Safety      2.0 pts   20%      Will I trip my inverter?
    P4 Reserve Floor    1.5 pts   15%      Does battery stay healthy?
    ────────────────────────────────────────────────────────────────────────
    TOTAL               10.0 pts  100%

GRADE SCALE
───────────
    Grade   Score       Label           What it means
    ─────────────────────────────────────────────────────────────────────────
    S       9.0 – 10.0  Exceptional     Fully solar. 14+ days. No concerns.
    A       8.0 – 8.9   Excellent       Strong solar. 10+ days. Healthy.
    B       7.0 – 7.9   Good            Moderate solar. 7+ days. Safe.
    C       6.0 – 6.9   Fair            Partial solar. 4–7 days. Monitor.
    D       5.0 – 5.9   Poor            <40% solar. 2–4 days. Act soon.
    F       0.0 – 4.9   CRITICAL        System cannot sustain itself.
    ─────────────────────────────────────────────────────────────────────────

WHAT GRADE F MEANS
──────────────────
Grade F (score < 5.0) is a SYSTEM FAILURE STATE. It fires when the combined
weight of failures across pillars is too severe for a safe off-grid stay.
At least one of the following is true:

  1. IMMINENT DEPLETION (P1 low)
     days_off_grid < ~2.4 → P1 < 0.6 pts
     Battery will be exhausted within 2 days. Shore power or load shedding
     is immediately required.

  2. SOLAR BLACKOUT (P2 low)
     solar_coverage < ~33% → P2 < 1.0 pt
     The panels generate less than a third of daily demand. This happens
     during multi-day overcast, insufficient panel capacity, or shading.
     The battery is doing ALL the work.

  3. INVERTER OVERLOAD RISK (P3 low)
     peak_kw > ~2.5 kW → P3 < 1.0 pt
     Simultaneous large loads (dryer + AC + water heater) push instantaneous
     draw toward the 5 kW inverter limit. Risk of circuit trip or damage.

  4. RESERVE VIOLATION (P4 low)
     min_soc < ~53% → P4 < 0.49 pts
     The battery's daily low dips close to the 20% LiFePO4 safety floor.
     Repeated deep cycles permanently age lithium cells.

A COMBINED F (multiple pillars near zero simultaneously) is the most
dangerous scenario. Example: 2 kWh/day solar against 13 kWh/day load
with AC + water heater running → score ≈ 2.0/10.

BENCHMARK VALUES
────────────────
These constants reflect real-world RV best practices:

  14 days autonomy   — BLM boondocking in the US Southwest ("14-day rule")
  5 kW inverter      — Common pure-sine RV inverter limit (Victron Multiplus,
                       Renogy, Giandel etc.)
  20% SOC floor      — LiFePO4 manufacturer-recommended minimum depth
  100% solar         — The goal: zero battery drain; panels cover everything

FORMULA REFERENCE
─────────────────
  P1 = min(3.5,  (days_off_grid / 14) × 3.5)
  P2 = min(3.0,  solar_coverage_ratio × 3.0)       # ratio capped at 1.0
  P3 = min(2.0,  max(0, (1 − peak_kw / 5.0)) × 2.0)
  P4 = min(1.5,  max(0, (min_soc% − 20%) / 80%) × 1.5)
  SI = P1 + P2 + P3 + P4
"""
from __future__ import annotations


# Colour assigned to each grade for gauge rendering
_GRADE_COLOR: dict[str, str] = {
    "S": "#30D158",  # Apple green — exceptional
    "A": "#34C759",  # Apple system green — excellent
    "B": "#5AC8F5",  # Apple teal — good
    "C": "#0A84FF",  # Apple blue — fair
    "D": "#FF9F0A",  # Apple orange — poor
    "F": "#FF453A",  # Apple red — critical
}


def compute_stability_score(
    sol_cov:  float,   # Solar coverage ratio  0.0 – 1.0
    days:     float,   # Days off-grid autonomy
    peak_kw:  float,   # Peak instantaneous load in kW
    min_soc:  float,   # Lowest battery SOC % seen during 24h simulation
) -> tuple[float, str, str, str, dict]:
    """
    Compute the Stability Score (0.0 – 10.0).

    Parameters
    ──────────
    sol_cov  : float  Solar self-sufficiency ratio (total_solar / total_load),
                      clipped to 1.0 maximum.
    days     : float  Estimated days of off-grid autonomy at current net draw.
    peak_kw  : float  Highest instantaneous load (kW) observed during the
                      2880-step simulation.
    min_soc  : float  Lowest battery state-of-charge (%) seen during the
                      simulation (0 – 100).

    Returns
    ───────
    tuple of:
      score  : float  Composite score 0.0 – 10.0 (2 decimal places)
      grade  : str    Letter grade S/A/B/C/D/F
      label  : str    English label (Exceptional … Critical)
      color  : str    Hex color for UI gauge rendering
      pillars: dict   {'p1': float, 'p1_max': 3.5,
                       'p2': float, 'p2_max': 3.0,
                       'p3': float, 'p3_max': 2.0,
                       'p4': float, 'p4_max': 1.5}
    """
    # ── Pillar 1: Energy Autonomy (0 – 3.5 pts) ──────────────────────────
    # Reference: 14 days is the BLM boondocking benchmark.
    # Capped at max value so extraordinary configurations don't inflate score.
    p1 = min(3.5, (min(days, 999.0) / 14.0) * 3.5)

    # ── Pillar 2: Solar Self-Sufficiency (0 – 3.0 pts) ───────────────────
    # sol_cov = total_solar_kWh / total_load_kWh  (already capped at 1.0)
    # At 100% solar → 3.0 pts; at 50% solar → 1.5 pts; at 0% solar → 0 pts.
    p2 = min(3.0, sol_cov * 3.0)

    # ── Pillar 3: Peak Safety Margin (0 – 2.0 pts) ───────────────────────
    # Reference inverter limit = 5 kW (Victron/Renogy/Giandel class).
    # Headroom factor = 1 − (peak_kw / 5.0); negative when overloaded.
    p3 = min(2.0, max(0.0, (1.0 - peak_kw / 5.0)) * 2.0)

    # ── Pillar 4: Battery Reserve Floor (0 – 1.5 pts) ────────────────────
    # Measures how far ABOVE the 20% LiFePO4 safety floor the daily minimum
    # SOC stays.  Score = 0 if min_soc ≤ 20%.
    p4 = min(1.5, max(0.0, (min_soc - 20.0) / 80.0) * 1.5)

    # ── Total ─────────────────────────────────────────────────────────────
    score = round(p1 + p2 + p3 + p4, 2)

    # ── Grade + label ─────────────────────────────────────────────────────
    if   score >= 9.0: grade, label = "S", "Exceptional"
    elif score >= 8.0: grade, label = "A", "Excellent"
    elif score >= 7.0: grade, label = "B", "Good"
    elif score >= 6.0: grade, label = "C", "Fair"
    elif score >= 5.0: grade, label = "D", "Poor"
    else:              grade, label = "F", "Critical"

    color = _GRADE_COLOR[grade]

    pillars = {
        "p1": round(p1, 2), "p1_max": 3.5,
        "p2": round(p2, 2), "p2_max": 3.0,
        "p3": round(p3, 2), "p3_max": 2.0,
        "p4": round(p4, 2), "p4_max": 1.5,
    }
    return score, grade, label, color, pillars
