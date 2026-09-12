"""Invoice/nameplate-based leak estimators — no new sensor hardware required.

Motivated directly by the HackOut'26 research doc "Industrial Emission
Leak-Point Detector" (Parts A.1/A.2, F.2/F.3): compressed-air leaks and
refrigerant leaks are two of the most common, most under-monitored SME leak
categories, and both are computable from data a plant already has on its
utility bills, compressor control panel, and refrigerant purchase invoices —
no OGI camera, no ultrasonic survey, no IoT retrofit needed to get a first
estimate. These are deliberately narrow, formula-based calculators (not a
generic ML model) so every number traces to a named, sourced method.
"""
from __future__ import annotations

from dataclasses import dataclass

# --- Compressed air ----------------------------------------------------------

# Rule-of-thumb specific power for a typical efficient rotary-screw compressor
# at ~100 psig, commonly cited in Compressed Air Challenge / DOE audit
# materials (~4-5 cfm delivered per kW, i.e. ~20 kW per 100 cfm). This is a
# DEFAULT, not a measurement of any specific compressor — callers should
# override it with the compressor's own nameplate kW / rated cfm ratio when
# known. Disclosed here rather than silently assumed.
DEFAULT_SPECIFIC_POWER_KW_PER_100CFM = 20.0

# Industry-cited leak-fraction range for a system that has never had a
# load/unload timing test done — used only as a fallback "quick estimate"
# when the user has no timing data, per Compressed Air Challenge Fact Sheet #7
# ("20-30% of compressor output lost to leaks in a poorly maintained system").
UNAUDITED_LEAK_FRACTION_LOW = 0.20
UNAUDITED_LEAK_FRACTION_HIGH = 0.30


@dataclass
class CompressedAirLeakResult:
    method: str  # "load_unload_test" | "unaudited_default_range"
    leak_fraction: float  # 0-1
    leak_fraction_low: float | None  # only set for the unaudited range method
    leak_fraction_high: float | None
    leaked_cfm: float
    wasted_kwh_per_year: float
    cost_inr_per_year: float
    co2e_tpy: float
    note: str


def compressed_air_leak_from_load_unload_test(
    rated_capacity_cfm: float,
    load_time_min: float,
    unload_time_min: float,
    operating_hours_per_year: float,
    electricity_rate_inr_per_kwh: float,
    grid_kgco2e_per_kwh: float,
    specific_power_kw_per_100cfm: float = DEFAULT_SPECIFIC_POWER_KW_PER_100CFM,
) -> CompressedAirLeakResult:
    """The standard DOE / Compressed Air Challenge "on-time" test method:
    with no production load on the system (off-shift), the compressor
    repeatedly loads (actually compressing, to cover leakage) and unloads
    (coasting). %Leakage = load_time / (load_time + unload_time) x 100 —
    the only thing consuming air during this test IS the leaks, so the
    load fraction of the cycle directly measures the leak fraction of the
    compressor's rated capacity. See Compressed Air Challenge Fact Sheet #7.
    """
    if load_time_min < 0 or unload_time_min < 0:
        raise ValueError("load_time_min and unload_time_min must be >= 0")
    cycle = load_time_min + unload_time_min
    leak_fraction = (load_time_min / cycle) if cycle > 0 else 0.0

    leaked_cfm = rated_capacity_cfm * leak_fraction
    kw_wasted = leaked_cfm * (specific_power_kw_per_100cfm / 100.0)
    wasted_kwh_per_year = kw_wasted * operating_hours_per_year
    cost_inr_per_year = wasted_kwh_per_year * electricity_rate_inr_per_kwh
    co2e_tpy = wasted_kwh_per_year * grid_kgco2e_per_kwh / 1000.0

    return CompressedAirLeakResult(
        method="load_unload_test",
        leak_fraction=round(leak_fraction, 4),
        leak_fraction_low=None, leak_fraction_high=None,
        leaked_cfm=round(leaked_cfm, 1),
        wasted_kwh_per_year=round(wasted_kwh_per_year, 0),
        cost_inr_per_year=round(cost_inr_per_year, 0),
        co2e_tpy=round(co2e_tpy, 2),
        note=(
            f"Load/unload timing test (Compressed Air Challenge method): compressor was "
            f"loaded {load_time_min:.1f} min and unloaded {unload_time_min:.1f} min per cycle "
            f"during a no-demand test — leak fraction = load time / cycle time, since only "
            f"leaks draw air during that test. Specific power assumed at "
            f"{specific_power_kw_per_100cfm:.1f} kW/100cfm (typical rotary-screw rule of thumb, "
            f"not measured for this exact compressor unless overridden)."
        ),
    )


def compressed_air_leak_unaudited_default(
    rated_capacity_cfm: float,
    operating_hours_per_year: float,
    electricity_rate_inr_per_kwh: float,
    grid_kgco2e_per_kwh: float,
    specific_power_kw_per_100cfm: float = DEFAULT_SPECIFIC_POWER_KW_PER_100CFM,
) -> CompressedAirLeakResult:
    """Fallback when no load/unload timing test has been run: uses the
    literature-cited 20-30% range for an unaudited system (Compressed Air
    Challenge Fact Sheet #7) rather than a specific measured number — the
    midpoint is reported as the point estimate, with the range disclosed."""
    mid = (UNAUDITED_LEAK_FRACTION_LOW + UNAUDITED_LEAK_FRACTION_HIGH) / 2
    leaked_cfm = rated_capacity_cfm * mid
    kw_wasted = leaked_cfm * (specific_power_kw_per_100cfm / 100.0)
    wasted_kwh_per_year = kw_wasted * operating_hours_per_year
    cost_inr_per_year = wasted_kwh_per_year * electricity_rate_inr_per_kwh
    co2e_tpy = wasted_kwh_per_year * grid_kgco2e_per_kwh / 1000.0

    return CompressedAirLeakResult(
        method="unaudited_default_range",
        leak_fraction=round(mid, 4),
        leak_fraction_low=UNAUDITED_LEAK_FRACTION_LOW, leak_fraction_high=UNAUDITED_LEAK_FRACTION_HIGH,
        leaked_cfm=round(leaked_cfm, 1),
        wasted_kwh_per_year=round(wasted_kwh_per_year, 0),
        cost_inr_per_year=round(cost_inr_per_year, 0),
        co2e_tpy=round(co2e_tpy, 2),
        note=(
            "No load/unload timing test data supplied — this uses the literature-cited "
            f"{UNAUDITED_LEAK_FRACTION_LOW*100:.0f}-{UNAUDITED_LEAK_FRACTION_HIGH*100:.0f}% leak "
            "range for an unaudited compressed-air system (Compressed Air Challenge Fact Sheet #7), "
            "not a number measured on this specific plant. Run the load/unload test for a real "
            "site-specific figure."
        ),
    )


# --- Refrigerant leaks --------------------------------------------------------

# GWP-100 values, IPCC AR5 (the same edition KC Commercial Refrigeration's
# R-404A figure in the source doc traces to — kept consistent with it).
REFRIGERANT_GWP: dict[str, dict] = {
    "r22": {"label": "R-22 (HCFC-22)", "gwp100": 1810},
    "r134a": {"label": "R-134a", "gwp100": 1430},
    "r404a": {"label": "R-404A", "gwp100": 3922},
    "r407c": {"label": "R-407C", "gwp100": 1774},
    "r410a": {"label": "R-410A", "gwp100": 2088},
    "r717_ammonia": {"label": "R-717 (Ammonia)", "gwp100": 0},
    "r744_co2": {"label": "R-744 (CO2)", "gwp100": 1},
}


@dataclass
class RefrigerantLeakResult:
    refrigerant_label: str
    gwp100: float
    leak_rate_pct: float
    co2e_tpy: float
    replacement_cost_inr_per_year: float
    note: str


def refrigerant_leak_from_topup(
    refrigerant_key: str,
    nameplate_charge_kg: float,
    annual_topup_kg: float,
    refrigerant_cost_inr_per_kg: float,
) -> RefrigerantLeakResult:
    """A refrigerant top-up is not maintenance — it is compensation for a
    continuous leak. leak_rate = annual top-up / nameplate charge (the same
    inference the source doc's Scenario 3 describes: "logs refrigerant
    purchase/top-up volume against system nameplate charge... data that
    already exists on every purchase invoice"). GWP-weighted CO2e follows
    directly since refrigerant mass leaked x GWP100 = CO2-equivalent."""
    if refrigerant_key not in REFRIGERANT_GWP:
        raise ValueError(f"unknown refrigerant_key '{refrigerant_key}'. Accepted: {list(REFRIGERANT_GWP)}")
    ref = REFRIGERANT_GWP[refrigerant_key]
    leak_rate_pct = (annual_topup_kg / nameplate_charge_kg * 100.0) if nameplate_charge_kg > 0 else 0.0
    co2e_tpy = annual_topup_kg * ref["gwp100"] / 1000.0
    replacement_cost = annual_topup_kg * refrigerant_cost_inr_per_kg

    return RefrigerantLeakResult(
        refrigerant_label=ref["label"], gwp100=ref["gwp100"],
        leak_rate_pct=round(leak_rate_pct, 1), co2e_tpy=round(co2e_tpy, 3),
        replacement_cost_inr_per_year=round(replacement_cost, 0),
        note=(
            f"Inferred from {annual_topup_kg:.1f} kg/yr top-up against a {nameplate_charge_kg:.1f} kg "
            f"nameplate charge — the same simple invoice-based method the source research doc's "
            f"Scenario 3 describes, no new sensor required. IPCC AR5 GWP100={ref['gwp100']} for "
            f"{ref['label']}. A leak rate this high (IPCC's own default range for medium/large "
            "commercial refrigeration is 10-35%/yr) means the annual 'top-up' cost line is really "
            "a continuous-leak cost line."
        ),
    )
