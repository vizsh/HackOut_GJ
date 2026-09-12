"""Anomaly detection — genuinely different attempt #2: an ensemble of the
z-score rule (in production, backend/app/intelligence/anomaly.py) and the
Phase 3b conditional autoencoder (ml/anomaly_model.py), instead of trying to
replace one with the other.

Why this, not another architecture swap: ml/LIMITATIONS.md's writeup on the
autoencoder is explicit that this is "not a try a different architecture
gap, it's a we don't have enough history per series yet gap" — the real fix
(multiple years of history per factory) would require extending the
synthetic generator's time series length, which turns out to have a large,
risky blast radius across the rest of the product: `output_tonnes_per_year`,
every equipment's `co2e_tpy`, every benchmark ratio and severity
classification, and every sized recommendation are all currently computed by
summing/dividing over an assumed-12-month year (see backend/app/db/
seed_loader.py's `annual_output_t = sum(fac_raw["monthly_output_tonnes"])`
and `co2e_tpy = sum(v for _, v in monthly_co2e)`) — extending months without
carefully re-deriving every one of those would silently corrupt numbers the
whole rest of the app depends on. Not attempted here for that reason.

An ensemble is a genuinely different approach (combining two independent,
already-validated signals) that touches NONE of that — it only reads
already-computed EmissionRecord rows the same way both existing detectors
already do, so it carries none of that risk. Evaluated with the same
rigour and against the same real ground truth as everything else: reports
the result whichever way it goes.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from .anomaly_model import build_tensors, reconstruction_errors, train
from .data import load_anomaly_ground_truth, load_monthly_series_frame

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = REPO_ROOT / "backend"
import sys  # noqa: E402
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.intelligence.anomaly import detect_anomalies  # noqa: E402

ARTIFACTS_DIR = Path(__file__).resolve().parent / "artifacts"


def _zscore_matrix(df) -> np.ndarray:
    """Re-runs the real production z-score rule (not a reimplementation) row
    by row, returning a (N, 12) matrix of |z| values — the same rule
    ml/eval_zscore_baseline.py evaluates standalone."""
    out = np.zeros((len(df), 12), dtype=np.float64)
    for i, row in df.reset_index(drop=True).iterrows():
        series = list(zip(row["months"], row["series"]))
        points = detect_anomalies(series)
        for m_idx, p in enumerate(points):
            out[i, m_idx] = abs(p.z)
    return out


def _score(flags: np.ndarray, df, ground_truth: set[tuple[str, str]]) -> dict:
    tp = fp = fn = 0
    for i, row in df.reset_index(drop=True).iterrows():
        for m_idx, month in enumerate(row["months"]):
            key = (row["equipment_id"], month)
            flagged = bool(flags[i, m_idx])
            is_true = key in ground_truth
            if flagged and is_true:
                tp += 1
            elif flagged and not is_true:
                fp += 1
            elif not flagged and is_true:
                fn += 1
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    return {"tp": tp, "fp": fp, "fn": fn, "precision": round(precision, 3), "recall": round(recall, 3)}


def main():
    df = load_monthly_series_frame()
    ground_truth = load_anomaly_ground_truth()
    print(f"Loaded {len(df)} equipment series, {len(ground_truth)} ground-truth anomaly labels.")

    # Signal 1: the real production z-score rule.
    z_abs = _zscore_matrix(df)
    z_flag = z_abs > 2.5  # the rule's own z_limit — rel_guard omitted here since
    # we want the RAW z signal for the ensemble scoring below, not the
    # rule's own already-thresholded flag (that's evaluated separately as
    # the baseline to beat).

    # Signal 2: the Phase 3b autoencoder's reconstruction error, per-equipment
    # normalised (median/MAD) the same way anomaly_model.py already does.
    series_t, cond_t, means, stds = build_tensors(df)
    model = train(series_t, cond_t)
    errors = reconstruction_errors(model, series_t, cond_t)
    median = np.median(errors, axis=1, keepdims=True)
    mad = np.median(np.abs(errors - median), axis=1, keepdims=True) * 1.4826 + 1e-9
    recon_z = (errors - median) / mad  # per-equipment robust z-score of reconstruction error

    # The actual z-score RULE (with its own rel_guard, exactly as in
    # production) — this is the baseline every ensemble variant below must
    # beat, not just the raw z_flag computed above.
    baseline_flags = np.zeros((len(df), 12), dtype=bool)
    for i, row in df.reset_index(drop=True).iterrows():
        series = list(zip(row["months"], row["series"]))
        for m_idx, p in enumerate(detect_anomalies(series)):
            baseline_flags[i, m_idx] = p.anomaly
    baseline = _score(baseline_flags, df, ground_truth)
    print("z-score rule alone (production baseline):", baseline)

    variants = {}

    # OR ensemble: either signal alone is enough — maximises recall, likely
    # hurts precision (adds the autoencoder's own false positives on top).
    or_flags = baseline_flags | (recon_z > 3.0)
    variants["or_zscore_or_autoencoder"] = _score(or_flags, df, ground_truth)

    # AND ensemble: both signals must agree — should raise precision by using
    # the autoencoder to veto z-score flags that don't also show unusual
    # reconstruction error, at the cost of recall.
    and_flags = baseline_flags & (recon_z > 1.0)
    variants["and_zscore_and_autoencoder"] = _score(and_flags, df, ground_truth)

    # Weighted-sum ensemble: a continuous combined score instead of a hard
    # AND/OR — thresholded at a level chosen to match the baseline's own
    # flag COUNT, so precision/recall are compared at a similar operating
    # point rather than an arbitrarily stricter or looser one.
    combined = 0.6 * z_abs + 0.4 * np.clip(recon_z, 0, None)
    target_flags = int(baseline_flags.sum())
    thresh = np.sort(combined.ravel())[::-1][target_flags - 1] if target_flags > 0 else combined.max() + 1
    weighted_flags = combined >= thresh
    variants["weighted_sum_matched_flag_count"] = _score(weighted_flags, df, ground_truth)

    for name, result in variants.items():
        print(name, result)

    best_name, best = max(variants.items(), key=lambda kv: kv[1]["precision"] + kv[1]["recall"])
    beats_baseline = best["precision"] >= baseline["precision"] and best["recall"] >= baseline["recall"]

    ARTIFACTS_DIR.mkdir(exist_ok=True)
    with open(ARTIFACTS_DIR / "anomaly_ensemble_metrics.json", "w", encoding="utf-8") as f:
        json.dump({
            "zscore_rule_alone_baseline": baseline,
            "ensemble_variants": variants,
            "best_variant": best_name,
            "best_result": best,
            "verdict": "beats_baseline" if beats_baseline else "does_not_beat_baseline",
            "note": (
                "Ensemble of the production z-score rule (backend/app/intelligence/anomaly.py) "
                "and the Phase 3b autoencoder's per-equipment-normalised reconstruction error "
                "(ml/anomaly_model.py). Three combination strategies tried: OR (either signal "
                "flags), AND (both must agree), and a weighted continuous sum thresholded to "
                "match the baseline's own flag count. This does not require more history per "
                "series (see this file's module docstring for why that fix was not attempted) — "
                "it only recombines two already-validated signals computed from the same real "
                "EmissionRecord data both detectors already read."
            ),
        }, f, indent=2)

    print(f"\nBest variant: {best_name} -> {best}")
    print("Baseline (z-score rule alone):", baseline)
    print("Verdict:", "beats_baseline" if beats_baseline else "does_not_beat_baseline")
    print(f"Saved metrics to {ARTIFACTS_DIR / 'anomaly_ensemble_metrics.json'}")


if __name__ == "__main__":
    main()
