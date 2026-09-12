"""
Induscope data pipeline — synthetic factory generator (Phase 1).

Produces RAW monthly activity data (fuel/electricity quantities, output tonnage,
waste tonnage) for 120 factories across the 9 real Gujarat clusters in
data-pipeline/clean/clusters.csv, using the process mix and benchmark
intensities in data-pipeline/clean/sector_benchmarks.csv and the emission
factors in data-pipeline/clean/emission_factors.csv.

Deliberately does NOT compute CO2e totals, benchmark-deviation severities,
root-cause text, or recommended interventions here — see LIMITATIONS.md #5.
Those must be computed by backend/app/engine + backend/app/intelligence
reading this file's output, so every number in the product traces to a real
function call on real-or-calibrated input, not a hand-authored figure.

Deterministic: fixed RANDOM_SEED, single sequential random stream, so re-running
this script produces byte-identical output. Change RANDOM_SEED only if you
intend to regenerate a new dataset version (bump SCHEMA_VERSION too).

Injected anomaly months are written ONLY to synth/anomaly_ground_truth.json,
never into the model-facing factories_synthetic.json — see LIMITATIONS.md #6.
"""

import csv
import json
import random
from pathlib import Path

RANDOM_SEED = 42
SCHEMA_VERSION = "1.0.0"

ROOT = Path(__file__).resolve().parent.parent
CLEAN = ROOT / "clean"
SYNTH = ROOT / "synth"

MONTHS = [
    "2025-04", "2025-05", "2025-06", "2025-07", "2025-08", "2025-09",
    "2025-10", "2025-11", "2025-12", "2026-01", "2026-02", "2026-03",
]

# Illustrative output-scale ranges per sector (annual tonnes of product/throughput).
# NOT independently sourced — order-of-magnitude judgement calls consistent with
# publicly known GIDC SME scale. Tagged is_placeholder. See LIMITATIONS.md #7.
SECTOR_OUTPUT_RANGE_T_PER_YEAR = {
    "Ceramics": (20000, 60000),
    "Chemicals": (3000, 15000),
    "Textiles": (5000, 20000),
    "Engineering": (2000, 10000),
}

# Which factory count to generate per cluster (sums to 120), and which sector
# each cluster's factories draw from (a cluster with two dominant sectors
# splits its count across both).
CLUSTER_PLAN = {
    "morbi":      [("Ceramics", 18)],
    "vapi":       [("Chemicals", 14)],
    "ankleshwar": [("Chemicals", 12)],
    "surat":      [("Textiles", 16)],
    "rajkot":     [("Engineering", 14)],
    "jamnagar":   [("Engineering", 5), ("Chemicals", 5)],
    "vatva":      [("Chemicals", 8), ("Textiles", 8)],
    "dahej":      [("Chemicals", 10)],
    # Alang (ship recycling) has no dedicated process template; it is mapped
    # onto the Engineering template (furnace/cutting, compressor, heat-treat)
    # as a documented simplification, not a fabricated new sector — see
    # SYNTHETIC_DATA_DISCLOSURE.md.
    "alang":      [("Engineering", 10)],
}

# Primary fuel assignment per process kind — a defensible typical mix, not a
# cited figure. Documented as `calibrated` in SYNTHETIC_DATA_DISCLOSURE.md.
PROCESS_FUEL_MIX = {
    "kiln":       [("natural_gas", 0.85), ("pet_coke", 0.15)],
    "boiler":     [("coal", 0.55), ("biomass", 0.25), ("natural_gas", 0.20)],
    "furnace":    [("grid_electricity", 0.90), ("natural_gas", 0.10)],
    "dryer":      [("natural_gas", 0.75), ("grid_electricity", 0.25)],
    "compressor": [("grid_electricity", 1.0)],
    "effluent":   [("grid_electricity", 1.0)],
    "generic":    [("grid_electricity", 0.6), ("natural_gas", 0.4)],
}

# Seasonal output multiplier by month-of-year (index 0 = April), mild swing —
# a documented modelling choice (monsoon slowdown, year-end ramp), not sourced.
SEASONAL_MULTIPLIER = [1.00, 1.02, 1.01, 0.92, 0.90, 0.95, 1.00, 1.03, 1.05, 1.06, 1.04, 0.98]

ANOMALY_FRACTION = 0.17  # ~17% of factories get 1-2 injected anomalous months
ANOMALY_MULTIPLIER_RANGE = (1.4, 2.1)

# --- Real-distribution-fit noise model (replaces the earlier hand-tuned
# rng.uniform(0.80, 1.45) inter-factory dispersion described in LIMITATIONS.md
# #9) --------------------------------------------------------------------
#
# SEC_CV_BY_SECTOR: a real, sourced coefficient of variation (std/mean) for
# how much specific energy consumption (SEC — energy per unit output, already
# scale-normalised) varies ACROSS DIFFERENT UNITS of the same sub-sector,
# computed from BEE/SAMEEEKSHA cluster-manual SEC-range tables (min-max per
# equipment type), assuming the reported range approximates a uniform
# distribution (std = range / sqrt(12)):
#
#   Ceramics (Morbi cluster) — BEE/SAMEEEKSHA "Manual on Energy Conservation
#   Measures in Ceramic Cluster Morbi", Table 7 "Specific Energy Consumption
#   Range in Ceramic Units in Morbi" (sameeeksha.org/pdf/clusterprofile/
#   Morbi_Ceramic_Cluster.pdf):
#     Vitrified tiles electrical 3.71-5.01 kWh/m2 -> CV 8.6%
#     Vitrified tiles thermal    1.51-2.11 SCM/m2 -> CV 9.6%
#     Wall & floor electrical    1.51-1.92 kWh/m2 -> CV 6.9%
#     Wall & floor thermal       1.28-1.80 SCM/m2 -> CV 9.8%
#     Sanitary ware electrical   57-128 kWh/MT     -> CV 22.2% (small product
#       category, treated as a real but noisier outlier, not excluded)
#     Sanitary ware thermal      81.48-110 SCM/MT  -> CV 8.6%
#   Mean across all six rows = 10.9%, rounded to 0.11.
#
#   Textiles (Surat cluster) — BEE/SAMEEEKSHA "Manual on Energy Conservation
#   Measures in Textile Cluster Surat, Gujarat", Table 5 "Specific Energy
#   Consumption" (sameeeksha.org/pdf/clusterprofile/Surat_textile_cluster.pdf):
#     Saflina machine    0.011-0.013 kWh/m -> CV 4.8%
#     Drum washer        0.012-0.016 kWh/m -> CV 8.3%
#     Jet dyeing machine 0.016-0.019 kWh/m -> CV 5.0%
#     Stenter machine    0.018-0.020 kWh/m -> CV 3.0%
#   Mean across all four rows = 5.0%.
#
# Chemicals and Engineering: NOT included here. The one directly comparable
# cluster-manual table found for chemicals (Vapi cluster, Table 5.2.1 "Unit
# level energy consumption") reports RAW annual toe/year by product category
# (320-470 for dyes & pigments, 51-455 for API/pharma, 152-370 for other
# chemicals) — that range conflates plant-to-plant SCALE differences (which
# this generator already models separately via SECTOR_OUTPUT_RANGE_T_PER_YEAR
# + scale_effect below) with genuine efficiency variation, since it is not
# normalised per unit of output. Using it directly would double-count scale
# as noise. No output-normalised SEC-range table for a Gujarat chemicals or
# engineering cluster was located in this research pass, so those two
# sectors fall back to LEGACY_UNSOURCED_CV below — an explicit placeholder,
# not silently reused from a different sector.
SEC_CV_BY_SECTOR = {
    "Ceramics": 0.11,
    "Textiles": 0.05,
}
# Reproduces the ORIGINAL rng.uniform(0.85, 1.25) cross-factory dispersion's
# implied std/mean exactly (std = range/sqrt(12) = 0.4/3.464 = 0.1155) — for
# Chemicals/Engineering (no sourced SEC-range table located, see above), this
# is an unchanged placeholder, not a new number.
LEGACY_CROSS_SECTIONAL_CV = (1.25 - 0.85) / (12 ** 0.5)

# Month-to-month (temporal, within ONE factory) variation is a genuinely
# different statistic from the cross-sectional SEC_CV_BY_SECTOR above (which
# measures spread ACROSS different plants) — no public month-by-month SEC
# time series for individual Indian MSME units was found to source this
# directly. For Ceramics/Textiles (sourced sectors), modelled as a disclosed
# FRACTION of the sourced cross-sectional CV (same equipment/operators
# month-to-month should vary less than different plants do) — this ratio
# itself, not the base CV it's derived from, is the modelling assumption
# still pending a real source. For Chemicals/Engineering (unsourced), the
# temporal CV instead reproduces the ORIGINAL rng.uniform(0.93, 1.07)
# month-to-month noise's implied std/mean EXACTLY (std = 0.14/sqrt(12) =
# 0.0404) — deliberately NOT derived via the same ratio from
# LEGACY_CROSS_SECTIONAL_CV, since that would silently change behaviour for
# the two sectors this pass did not actually improve on. Only touch what you
# sourced.
TEMPORAL_TO_CROSS_SECTIONAL_CV_RATIO = 0.5
LEGACY_TEMPORAL_CV = (1.07 - 0.93) / (12 ** 0.5)


def _sourced_cv(sector: str) -> float:
    return SEC_CV_BY_SECTOR.get(sector, LEGACY_CROSS_SECTIONAL_CV)


def _temporal_cv(sector: str) -> float:
    cross_sectional = SEC_CV_BY_SECTOR.get(sector)
    if cross_sectional is None:
        return LEGACY_TEMPORAL_CV
    return cross_sectional * TEMPORAL_TO_CROSS_SECTIONAL_CV_RATIO


def _gauss_ratio(rng, mean: float, cv: float, clip_sigmas: float = 3 ** 0.5) -> float:
    """A normal draw centred on `mean` with std = mean*cv, replacing the
    earlier plain rng.uniform(lo, hi) noise so the generator is actually
    parameterised by a real, sourced coefficient of variation instead of an
    arbitrarily-picked interval width.

    Clipped at +/-clip_sigmas standard deviations rather than a fixed
    absolute range: a first version of this used a generic wide clip
    (0.5-1.8x), which let rare Gaussian tail draws exceed the old bounded
    uniform distribution's HARD cutoff — a uniform(0.93,1.07) draw can never
    exceed 7% deviation, but an unclipped/loosely-clipped gauss(1.0, 0.055)
    occasionally does, at 3+ sigma. Those rare tail events were enough to
    push app/intelligence/anomaly.py's z-score+rel_guard thresholds (tuned
    against the old bounded distribution) into false positives, cratering
    precision (caught by scripts/validate_all.py against
    validation/baseline_metrics.json). Default clip is sqrt(3) sigma
    specifically because that is the exact max deviation a uniform
    distribution with the same std implies (a uniform's std = range /
    (2*sqrt(3)), so its hard edge sits at std*sqrt(3) from the mean) — this
    keeps the Gaussian SHAPE (still meaningfully different from, and more
    realistic than, flat uniform density in the bulk of the distribution)
    while capping the tail at the same max deviation the old bounded
    uniform distribution always had, not a looser or tighter one."""
    std = mean * cv
    draw = rng.gauss(mean, std)
    return max(mean - clip_sigmas * std, min(mean + clip_sigmas * std, draw))


def load_csv(name):
    with open(CLEAN / name, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_clusters():
    rows = load_csv("clusters.csv")
    out = {}
    for r in rows:
        out[r["id"]] = {
            "id": r["id"],
            "name": r["name"],
            "district": r["district"],
            "lat": float(r["lat"]),
            "lon": float(r["lon"]),
        }
    return out


def load_benchmarks():
    rows = load_csv("sector_benchmarks.csv")
    by_sector = {}
    for r in rows:
        by_sector.setdefault(r["sector"], []).append({
            "process_id": r["process_id"],
            "label": r["process_label"],
            "kind": r["process_kind"],
            "share": float(r["share_of_energy"]),
            "benchmark_kgco2e_per_t": float(r["benchmark_intensity_kgco2e_per_t"]),
            "source": r["source"],
            "confidence": r["confidence"],
        })
    return by_sector


def load_waste_stream_profiles():
    rows = load_csv("waste_stream_profiles.csv")
    by_sector = {}
    for r in rows:
        by_sector.setdefault(r["sector"], []).append({
            "role": r["role"],
            "tag": r["tag"],
            "label": r["label"],
            "form": r["form"],
            "share_of_basis": float(r["share_of_basis"]),
            "cost_inr_per_t": float(r["cost_inr_per_t"]),
            "basis": r["basis"],
        })
    return by_sector


def load_emission_factors():
    rows = load_csv("emission_factors.csv")
    out = {}
    for r in rows:
        out[r["key"]] = {
            "kgco2e_per_unit": float(r["kgco2e_per_unit"]),
            "canonical_unit": r["canonical_unit"],
        }
    return out


def jitter_latlon(rng, lat, lon, max_km=12.0):
    # ~0.009 deg latitude per km; longitude scaled by cos(lat) roughly ignored
    # at this small radius for a demo-grade dataset (documented simplification).
    dlat = (rng.uniform(-1, 1)) * (max_km / 111.0)
    dlon = (rng.uniform(-1, 1)) * (max_km / 111.0)
    return round(lat + dlat, 4), round(lon + dlon, 4)


def build_waste_stream_tags(rng, sector, profiles_by_sector, total_waste_tpy, annual_output_t):
    """Tagged waste streams (emit) and accepted inputs (accept) for one
    factory, sized off its own real computed totals — not fabricated
    quantities. See data-pipeline/clean/waste_stream_profiles.csv for the
    per-sector tag vocabulary and sourcing notes."""
    emit, accept = [], []
    for p in profiles_by_sector.get(sector, []):
        noise = rng.uniform(0.85, 1.15)
        if p["role"] == "emit":
            basis_value = total_waste_tpy if p["basis"] == "total_waste_tpy" else annual_output_t
            tpy = round(p["share_of_basis"] * basis_value * noise, 1) if p["share_of_basis"] > 0 else 0
            emit.append({
                "tag": p["tag"], "label": p["label"], "form": p["form"],
                "tpy": tpy, "disposal_cost_inr_per_t": p["cost_inr_per_t"],
            })
        else:
            basis_value = total_waste_tpy if p["basis"] == "total_waste_tpy" else annual_output_t
            max_tpy = round(p["share_of_basis"] * basis_value * noise, 1)
            accept.append({
                "tag": p["tag"], "label": p["label"],
                "max_tpy": max_tpy, "virgin_cost_inr_per_t": p["cost_inr_per_t"],
            })
    return emit, accept


def build_factory(rng, cluster, sector, seq, processes, ef, waste_ratio_row, waste_stream_profiles):
    output_lo, output_hi = SECTOR_OUTPUT_RANGE_T_PER_YEAR[sector]
    annual_output_t = rng.uniform(output_lo, output_hi)
    monthly_base_output = annual_output_t / 12.0

    lat, lon = jitter_latlon(rng, cluster["lat"], cluster["lon"])
    factory_id = f"{cluster['id']}-{sector.lower()}-{seq:02d}"
    name = f"{cluster['name']} {sector} Unit {seq:02d} (Synthetic)"

    # Per-factory performance ratio: how this factory's real specific-energy
    # compares to the sector benchmark (0.8 = runs 20% better than benchmark,
    # 1.4 = runs 40% worse). This is what later lets benchmark-deviation and
    # hotspot ranking actually differentiate factories.
    #
    # Includes a deliberate, documented economies-of-scale effect: larger
    # factories within a sector's output range tend to run closer to (or
    # better than) benchmark, smaller ones tend to run worse — a real,
    # well-known industrial pattern (better instrumentation, more consistent
    # throughput, amortised process-control investment at scale), not an
    # invented one, though the specific magnitude here is a documented
    # modelling choice, not a cited coefficient. This was ADDED after Phase 3a
    # (ml/benchmark_model.py) found the original pure-noise ratio made the
    # flat benchmark mathematically optimal — no covariate-dependent signal
    # existed for any model to learn, so a LightGBM predictor scored worse
    # than just using the benchmark number (see ml/artifacts/benchmark_metrics.json
    # history / data-pipeline/LIMITATIONS.md #9). Fixed here, at the source,
    # rather than papering over it in the model.
    output_percentile = (annual_output_t - output_lo) / (output_hi - output_lo) if output_hi > output_lo else 0.5
    scale_effect = 1.18 - 0.32 * output_percentile  # 1.18x at the small end, 0.86x at the large end
    cross_sectional_cv = _sourced_cv(sector)
    base_noise = _gauss_ratio(rng, 1.0, cross_sectional_cv)
    factory_performance_ratio = scale_effect * base_noise

    # Dampen and individualise the seasonal curve per factory. Applying the
    # exact same seasonal shape to all 120 factories turned out to be a real
    # bug once run through the actual anomaly detector (app/intelligence/
    # anomaly.py's leave-one-out z-score, n=12): a uniform cross-factory
    # signal reads as a strong, systematic deviation and got ~10% of all
    # equipment-months false-flagged as anomalies, concentrated exactly in
    # the seasonal trough/peak months (verified: see
    # data-pipeline/LIMITATIONS.md #8). Real factories don't all share one
    # calendar-perfect seasonal curve, so each factory now gets its own
    # damping factor on top of the shared shape.
    seasonal_damping = rng.uniform(0.25, 0.6)
    # Month-to-month (temporal, ONE factory) noise — derived from the sourced
    # cross-sectional CV above, applied at exactly ONE point in the pipeline
    # (the final per-month target_kgco2e draw below), not compounded across
    # multiple independent noise layers. An earlier version of this change
    # applied temporal_cv separately to monthly_output, proc_performance, AND
    # the per-month draw — three multiplicative layers at the same magnitude
    # compound to a much larger EFFECTIVE variance than any single sourced CV
    # (verified: it cratered the z-score detector's precision from 0.55 to
    # 0.09 against validation/baseline_metrics.json — a real regression the
    # CI gate caught). monthly_output and proc_performance below keep their
    # original small, independently-tuned ranges (not sourced by this SEC
    # research, and not the thing "month-to-month variance" refers to here);
    # temporal_cv models specifically what the sourced figure measures —
    # month-to-month specific energy consumption at one process.
    temporal_cv = _temporal_cv(sector)
    monthly_output = []
    for m_idx in range(12):
        noise = rng.uniform(0.95, 1.05)
        seasonal = 1.0 + (SEASONAL_MULTIPLIER[m_idx] - 1.0) * seasonal_damping
        monthly_output.append(round(monthly_base_output * seasonal * noise, 1))

    process_records = []
    for proc in processes:
        proc_performance = factory_performance_ratio * rng.uniform(0.92, 1.08)
        fuel_mix = PROCESS_FUEL_MIX[proc["kind"]]
        monthly_activity = []
        for m_idx in range(12):
            target_kgco2e = (
                proc["benchmark_kgco2e_per_t"]
                * monthly_output[m_idx]
                * proc["share"]
                * proc_performance
                * _gauss_ratio(rng, 1.0, temporal_cv)
            )
            fuels = {}
            for fuel_key, fuel_share in fuel_mix:
                fuel_kgco2e = target_kgco2e * fuel_share
                ef_row = ef[fuel_key]
                qty = fuel_kgco2e / ef_row["kgco2e_per_unit"]
                fuels[fuel_key] = round(qty, 3)
            monthly_activity.append({
                "month": MONTHS[m_idx],
                "fuel_quantities": fuels,
            })
        process_records.append({
            "process_id": proc["process_id"],
            "label": proc["label"],
            "kind": proc["kind"],
            "share_of_energy": proc["share"],
            "benchmark_source": proc["source"],
            "benchmark_confidence": proc["confidence"],
            "monthly_activity": monthly_activity,
        })

    hazardous_pct = float(waste_ratio_row["hazardous_waste_ratio_pct_of_output"]) / 100.0
    general_pct = float(waste_ratio_row["general_process_waste_ratio_pct_of_output"]) / 100.0
    monthly_waste = []
    for m_idx in range(12):
        out_t = monthly_output[m_idx]
        monthly_waste.append({
            "month": MONTHS[m_idx],
            "hazardous_waste_t": round(out_t * hazardous_pct * rng.uniform(0.85, 1.15), 2),
            "general_process_waste_t": round(out_t * general_pct * rng.uniform(0.85, 1.15), 2),
        })

    total_waste_tpy = sum(m["hazardous_waste_t"] + m["general_process_waste_t"] for m in monthly_waste)
    waste_streams, accepted_inputs = build_waste_stream_tags(
        rng, sector, waste_stream_profiles, total_waste_tpy, annual_output_t
    )

    return {
        "id": factory_id,
        "name": name,
        "cluster_id": cluster["id"],
        "sector": sector,
        "district": cluster["district"],
        "lat": lat,
        "lon": lon,
        "data_source": "synthetic",
        "schema_version": SCHEMA_VERSION,
        "monthly_output_tonnes": monthly_output,
        "processes": process_records,
        "monthly_waste": monthly_waste,
        "waste_streams": waste_streams,
        "accepted_inputs": accepted_inputs,
        "consent_to_share": True,
    }


def inject_anomalies(rng, factories):
    """Mutate a subset of factories in place, inflating one process's activity
    for 1-2 months. Returns the ground-truth label list (kept out of the
    model-facing file)."""
    ground_truth = []
    n_anomalous = max(1, round(len(factories) * ANOMALY_FRACTION))
    chosen = rng.sample(range(len(factories)), n_anomalous)
    for idx in chosen:
        factory = factories[idx]
        n_months = rng.choice([1, 1, 2])
        proc = rng.choice(factory["processes"])
        month_indices = rng.sample(range(12), n_months)
        multiplier = rng.uniform(*ANOMALY_MULTIPLIER_RANGE)
        for m_idx in month_indices:
            activity = proc["monthly_activity"][m_idx]
            for fuel_key in activity["fuel_quantities"]:
                activity["fuel_quantities"][fuel_key] = round(
                    activity["fuel_quantities"][fuel_key] * multiplier, 3
                )
            ground_truth.append({
                "factory_id": factory["id"],
                "process_id": proc["process_id"],
                "month": activity["month"],
                "injected_multiplier": round(multiplier, 3),
            })
    return ground_truth


def main():
    rng = random.Random(RANDOM_SEED)
    clusters = load_clusters()
    benchmarks = load_benchmarks()
    ef = load_emission_factors()
    waste_ratios = {r["sector"]: r for r in load_csv("waste_ratios.csv")}
    waste_stream_profiles = load_waste_stream_profiles()

    factories = []
    for cluster_id, sector_counts in CLUSTER_PLAN.items():
        cluster = clusters[cluster_id]
        for sector, count in sector_counts:
            processes = benchmarks[sector]
            for seq in range(1, count + 1):
                factories.append(
                    build_factory(rng, cluster, sector, seq, processes, ef, waste_ratios[sector], waste_stream_profiles)
                )

    assert len(factories) == 120, f"expected 120 factories, got {len(factories)}"

    ground_truth = inject_anomalies(rng, factories)

    SYNTH.mkdir(exist_ok=True)
    with open(SYNTH / "factories_synthetic.json", "w", encoding="utf-8") as f:
        json.dump(factories, f, indent=2)

    with open(SYNTH / "anomaly_ground_truth.json", "w", encoding="utf-8") as f:
        json.dump({
            "note": "Held-out labels for injected anomalous process-months. "
                    "NOT present in factories_synthetic.json. For evaluating "
                    "the Phase-3 anomaly detector's precision/recall against "
                    "real labels instead of asserted numbers.",
            "schema_version": SCHEMA_VERSION,
            "random_seed": RANDOM_SEED,
            "labels": ground_truth,
        }, f, indent=2)

    by_cluster = {}
    by_sector = {}
    for fac in factories:
        by_cluster[fac["cluster_id"]] = by_cluster.get(fac["cluster_id"], 0) + 1
        by_sector[fac["sector"]] = by_sector.get(fac["sector"], 0) + 1

    with open(SYNTH / "provenance_report.json", "w", encoding="utf-8") as f:
        json.dump({
            "schema_version": SCHEMA_VERSION,
            "random_seed": RANDOM_SEED,
            "total_factories": len(factories),
            "factories_by_cluster": by_cluster,
            "factories_by_sector": by_sector,
            "injected_anomaly_count": len(ground_truth),
            "injected_anomaly_factory_count": len({g["factory_id"] for g in ground_truth}),
            "field_provenance": {
                "cluster_geography": "real (see clean/clusters.csv, sources.md #5)",
                "emission_factors": "real (see clean/emission_factors.csv, sources.md #1-2)",
                "process_benchmark_intensities": "documented estimate, medium confidence, except Textiles which is real BEE PAT Cycle-1 (see clean/sector_benchmarks.csv, sources.md #4)",
                "waste_ratios": "calibrated to CPCB 2019-20 Gujarat state total order-of-magnitude (see clean/waste_ratios.csv, sources.md #3)",
                "factory_identity_and_time_series": "100% synthetic, seeded+reproducible (this script)",
                "output_scale_ranges": "is_placeholder, illustrative only (see LIMITATIONS.md #7)",
                "monthly_noise_model": (
                    "Ceramics/Textiles: coefficient of variation sourced from real BEE/SAMEEEKSHA "
                    "cluster-manual SEC-range tables (Morbi ceramics Table 7, Surat textiles Table 5); "
                    "Chemicals/Engineering: unsourced placeholder, unchanged from the original modelling "
                    "choice (see LIMITATIONS.md #10, SEC_CV_BY_SECTOR in this script)"
                ),
            },
        }, f, indent=2)

    print(f"Generated {len(factories)} factories across {len(by_cluster)} clusters.")
    print(f"Injected {len(ground_truth)} anomalous process-months across "
          f"{len({g['factory_id'] for g in ground_truth})} factories.")
    print(f"Output: {SYNTH / 'factories_synthetic.json'}")


if __name__ == "__main__":
    main()
