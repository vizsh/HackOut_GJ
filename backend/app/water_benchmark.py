"""Sourced water-intensity benchmark — a second benchmark axis alongside the
existing energy-intensity one in app/engine/intensity.py, motivated by the
HackOut'26 research doc's Part A.4 (Water Leak Points): process-water use
can vary ~50% between comparable units purely from process control, and
that gap is invisible without a benchmark to compare against, exactly like
the energy-intensity gap this project already diagnoses.

Only one sourced comparison exists in the research doc — Tirupur dyeing/
finishing units — so this is deliberately narrow rather than a fabricated
per-sector table: available only for the sector/sub-sector it is actually
sourced for, honestly reported unavailable everywhere else (same discipline
as app/carbon_credit.py and the "global"/"india" benchmark levels in
routers/factories.get_benchmark).
"""
from __future__ import annotations

# TERI — "Energy Implications of Water Use and Pollution Control in Tirupur":
# small/medium units on older winch-dyeing machines measured 175 l/kg fabric;
# larger, better-controlled units measured 120 l/kg — same product, same
# broad process, process-control difference only.
TIRUPUR_DYEING_BENCHMARK_LOW_L_PER_KG = 120.0
TIRUPUR_DYEING_BENCHMARK_HIGH_L_PER_KG = 175.0
TIRUPUR_SOURCE = (
    "TERI — 'Energy Implications of Water Use and Pollution Control in Tirupur': "
    "120 l/kg (larger, better-controlled units) to 175 l/kg (smaller units on older "
    "winch-dyeing machines) for comparable dyeing/finishing output."
)


def water_benchmark_for(sector: str) -> tuple[float, float, str] | None:
    """Returns (low, high, source) l/kg-output benchmark for a sector, or
    None if no sourced benchmark exists for it yet — never fabricated."""
    if sector.strip().lower().startswith("textile"):
        return TIRUPUR_DYEING_BENCHMARK_LOW_L_PER_KG, TIRUPUR_DYEING_BENCHMARK_HIGH_L_PER_KG, TIRUPUR_SOURCE
    return None


def evaluate(sector: str, litres_per_kg_submitted: float | None) -> dict:
    bench = water_benchmark_for(sector)
    if bench is None:
        return {
            "available": False,
            "litres_per_kg_submitted": litres_per_kg_submitted,
            "benchmark_low_litres_per_kg": None,
            "benchmark_high_litres_per_kg": None,
            "deviation_note": None,
            "source": f"No sourced water-intensity benchmark exists for sector '{sector}' yet — "
                      "only Tirupur textile dyeing/finishing is sourced in this build.",
        }

    low, high, source = bench
    deviation_note = None
    if litres_per_kg_submitted is not None:
        if litres_per_kg_submitted > high:
            over_pct = round((litres_per_kg_submitted - high) / high * 100, 1)
            deviation_note = (
                f"{litres_per_kg_submitted:.0f} l/kg is {over_pct}% above the higher end of the "
                f"sourced range ({high:.0f} l/kg) — process-control review (rinse cycles, winch vs. "
                "modern jet/airflow dyeing machines) is the same fix that closed this gap in the "
                "source Tirupur study, not new technology."
            )
        elif litres_per_kg_submitted < low:
            deviation_note = f"{litres_per_kg_submitted:.0f} l/kg is at or below the best-observed end of the sourced range ({low:.0f} l/kg) — already efficient by this benchmark."
        else:
            deviation_note = f"{litres_per_kg_submitted:.0f} l/kg falls within the sourced range ({low:.0f}-{high:.0f} l/kg)."

    return {
        "available": True,
        "litres_per_kg_submitted": litres_per_kg_submitted,
        "benchmark_low_litres_per_kg": low,
        "benchmark_high_litres_per_kg": high,
        "deviation_note": deviation_note,
        "source": source,
    }
