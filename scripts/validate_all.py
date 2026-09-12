"""End-to-end regression gate: data-pipeline -> backend seed -> ml eval ->
FastAPI smoke test, checked against validation/baseline_metrics.json.

This formalizes three evaluation harnesses that were previously run ad-hoc
during development (anomaly ground-truth precision/recall, benchmark-model
cluster-holdout, symbiosis threshold sweep) into one command that actually
refuses to let a change ship if it silently regresses one of them — closing
the gap between "we measured this once in a session" and "this is enforced
in the repo."

Usage:
    python scripts/validate_all.py                  # run everything, fail on regression
    python scripts/validate_all.py --skip-symbiosis  # skip the slow MiniLM-loading step
    python scripts/validate_all.py --update-baseline # after a deliberate, reviewed change,
                                                      # record new numbers as the baseline

Exit code 0 = everything passed (or was intentionally updated). Exit code 1 =
a real regression was found — see stdout for which check and by how much.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BASELINE_PATH = REPO_ROOT / "validation" / "baseline_metrics.json"

sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "backend"))

failures: list[str] = []
warnings: list[str] = []


def _run(cmd: list[str], cwd: Path, label: str) -> subprocess.CompletedProcess:
    print(f"\n--- {label} ---")
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    print(result.stdout[-4000:])
    if result.returncode != 0:
        print(result.stderr[-2000:], file=sys.stderr)
        failures.append(f"{label}: exit code {result.returncode}")
    return result


def _check_min(label: str, value: float, minimum: float) -> None:
    if value < minimum:
        failures.append(f"{label}: {value} is below the recorded floor {minimum} — real regression")
    else:
        print(f"  OK  {label}: {value} >= {minimum}")


def _check_range(label: str, value: float, minimum: float, maximum: float) -> None:
    if not (minimum <= value <= maximum):
        failures.append(f"{label}: {value} is outside the recorded range [{minimum}, {maximum}]")
    else:
        print(f"  OK  {label}: {value} in [{minimum}, {maximum}]")


def stage_data_pipeline() -> None:
    dp = REPO_ROOT / "data-pipeline"
    _run([sys.executable, "scripts/generate_synthetic.py"], dp, "data-pipeline: regenerate (deterministic, must be reproducible)")
    _run([sys.executable, "scripts/validate.py"], dp, "data-pipeline: validate (round-trips every number through the real engine formula)")


def stage_seed_backend() -> None:
    backend = REPO_ROOT / "backend"
    _run([sys.executable, "-m", "app.db.seed_loader"], backend, "backend: seed (runs real engine/intelligence code over the pipeline output)")


def stage_zscore_eval(baseline: dict) -> None:
    from ml.eval_zscore_baseline import evaluate
    print("\n--- ml: z-score anomaly detector (the one actually in production) ---")
    result = evaluate()
    print(json.dumps(result, indent=2))
    b = baseline["zscore_anomaly_detector"]
    _check_min("zscore precision", result["precision"], b["min_precision"])
    _check_min("zscore recall", result["recall"], b["min_recall"])
    return result


def stage_benchmark_model(baseline: dict) -> dict:
    from ml.benchmark_model import (
        leave_one_cluster_out_eval, random_kfold_eval, train_final_model,
        feature_importance, ARTIFACTS_DIR,
    )
    from ml.data import load_equipment_frame
    from sklearn.metrics import mean_absolute_error

    print("\n--- ml: benchmark predictor (LightGBM vs. flat sourced benchmark) ---")
    df = load_equipment_frame()
    baseline_mae = float(mean_absolute_error(df["actual_intensity"], df["benchmark_kgco2e_per_t"]))
    kfold = random_kfold_eval(df)
    loco = leave_one_cluster_out_eval(df)
    kfold_improvement = round((1 - kfold["mae_kgco2e_per_t"] / baseline_mae) * 100, 1)
    loco_improvement = round((1 - loco["mae_kgco2e_per_t"] / baseline_mae) * 100, 1)
    print(f"random_kfold_improvement_pct={kfold_improvement}, leave_one_cluster_out_improvement_pct={loco_improvement}")

    b = baseline["benchmark_model"]
    _check_min("benchmark random_kfold improvement", kfold_improvement, b["min_random_kfold_improvement_pct"])
    _check_min("benchmark leave_one_cluster_out improvement", loco_improvement, b["min_leave_one_cluster_out_improvement_pct"])

    model = train_final_model(df)
    ARTIFACTS_DIR.mkdir(exist_ok=True)
    model.booster_.save_model(str(ARTIFACTS_DIR / "benchmark_model.txt"))
    with open(ARTIFACTS_DIR / "benchmark_metrics.json", "w", encoding="utf-8") as f:
        json.dump({
            "random_kfold": {**kfold, "improvement_vs_flat_benchmark_pct": kfold_improvement},
            "leave_one_cluster_out": {**loco, "improvement_vs_flat_benchmark_pct": loco_improvement},
            "feature_importance_pct": feature_importance(model),
            "recommended_use": (
                f"Trust this model's prediction for factories in clusters already represented in "
                f"the training data (random_kfold regime, {kfold_improvement:+.1f}% MAE vs. flat "
                f"benchmark). For a factory in a cluster with zero prior training data, fall back to "
                f"the flat per-sub-sector benchmark instead (leave_one_cluster_out regime shows only "
                f"{loco_improvement:+.1f}% vs. baseline)."
            ),
        }, f, indent=2)

    return {"random_kfold_improvement_pct": kfold_improvement, "leave_one_cluster_out_improvement_pct": loco_improvement}


def stage_symbiosis(baseline: dict) -> dict:
    from ml import symbiosis_model
    print("\n--- ml: symbiosis matcher (MiniLM + FAISS) ---")
    symbiosis_model.main()
    report = json.loads((symbiosis_model.ARTIFACTS_DIR / "symbiosis_report.json").read_text(encoding="utf-8"))
    b = baseline["symbiosis_matcher"]
    _check_range("symbiosis n_matches", report["n_matches"], b["min_n_matches"], b["max_n_matches"])
    threshold = report["config"]["min_semantic_similarity"]
    if threshold < b["min_semantic_similarity_threshold"]:
        failures.append(
            f"symbiosis min_semantic_similarity dropped to {threshold} (was {b['min_semantic_similarity_threshold']}) "
            f"— this would reintroduce the textile_sludge/cotton_waste false-positive match found in Phase 3c"
        )
    else:
        print(f"  OK  symbiosis similarity threshold: {threshold} >= {b['min_semantic_similarity_threshold']}")
    return {"n_matches": report["n_matches"]}


def stage_anomaly_autoencoder(baseline: dict) -> None:
    from ml import anomaly_model
    print("\n--- ml: anomaly autoencoder (expected to stay NOT in production) ---")
    df = anomaly_model.load_monthly_series_frame()
    ground_truth = anomaly_model.load_anomaly_ground_truth()
    series_t, cond_t, means, stds = anomaly_model.build_tensors(df)
    model = anomaly_model.train(series_t, cond_t, epochs=200)  # shorter run — this is a sanity check, not a full retrain
    errors = anomaly_model.reconstruction_errors(model, series_t, cond_t)
    sweep = [anomaly_model.evaluate_per_equipment(df, errors, m, ground_truth) for m in [1.5, 2.0, 2.5, 3.0]]
    baseline_cmp = {"precision": baseline["zscore_anomaly_detector"]["precision"],
                     "recall": baseline["zscore_anomaly_detector"]["recall"]}
    best = max(sweep, key=lambda r: r["precision"] + r["recall"])
    beats = best["precision"] >= baseline_cmp["precision"] and best["recall"] >= baseline_cmp["recall"]
    verdict = "beats_baseline" if beats else "does_not_beat_baseline"
    print(f"verdict: {verdict} (best sweep point: {best})")
    if verdict != baseline["anomaly_autoencoder"]["expected_verdict"]:
        warnings.append(
            f"anomaly autoencoder verdict changed to '{verdict}' (expected "
            f"'{baseline['anomaly_autoencoder']['expected_verdict']}') — NOT a failure, but a human should "
            f"decide whether to promote it to production now; see ml/anomaly_model.py"
        )


def stage_smoke_test() -> None:
    print("\n--- FastAPI smoke test (TestClient, no live server, no live LLM) ---")
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    checks = [
        ("GET", "/api/health", None),
        ("GET", "/api/clusters", None),
        ("GET", "/api/factories", None),
        ("GET", "/api/factories/summary", None),
        ("GET", "/api/ml/status", None),
        ("GET", "/api/symbiosis/network", None),
        ("GET", "/api/interventions", None),
        ("GET", "/api/emission-factors", None),
        ("GET", "/api/scale-projection?factory_count=1000", None),
    ]
    for method, path, body in checks:
        resp = client.request(method, path, json=body)
        if resp.status_code != 200:
            failures.append(f"smoke test {method} {path}: got {resp.status_code}, expected 200")
        else:
            print(f"  OK  {method} {path} -> 200")

    factories = client.get("/api/factories").json()
    if not factories:
        failures.append("smoke test: GET /api/factories returned zero factories")
    else:
        fid = factories[0]["id"]
        for path in [f"/api/factories/{fid}", f"/api/factories/{fid}/benchmark",
                     f"/api/factories/{fid}/equipment", f"/api/factories/{fid}/recommendations"]:
            resp = client.get(path)
            if resp.status_code != 200:
                failures.append(f"smoke test GET {path}: got {resp.status_code}, expected 200")
            else:
                print(f"  OK  GET {path} -> 200")

    onboard_payload = {
        "name": "CI Smoke Test Factory", "cluster_id": "morbi", "sector": "Ceramics",
        "output_tonnes_total": 12000,
        "processes": [{
            "process_id": "kiln", "label": "Roller Kiln", "kind": "kiln", "share_of_energy": 0.5,
            "activities": [{"fuel_key": "natural_gas", "unit": "SCM", "quantity": 500000, "month": "2026-01"}],
        }],
    }
    resp = client.post("/api/factories", json=onboard_payload)
    if resp.status_code != 201:
        failures.append(f"smoke test POST /api/factories (onboarding): got {resp.status_code}, expected 201")
    else:
        onboarded = resp.json()
        total = onboarded["total_co2e_t"]
        expected = 500000 * 2.04 / 1000  # natural_gas kgco2e_per_unit, see data-pipeline/clean/emission_factors.csv
        if abs(total - expected) > 0.5:
            failures.append(f"smoke test onboarding: computed {total} tCO2e, expected ~{expected} — engine formula changed?")
        else:
            print(f"  OK  POST /api/factories (onboarding) -> 201, {total} tCO2e (matches expected formula output)")

        if onboarded["anomaly_check_status"] != "not_available":
            failures.append(f"smoke test: freshly onboarded factory reported anomaly_check_status="
                             f"'{onboarded['anomaly_check_status']}', expected 'not_available' (1 month of data)")

        # Feed 3 more months so this equipment crosses anomaly.py's own >= 4-month
        # minimum, and confirm the live feature-window job actually activates.
        onboarded_id = onboarded["id"]
        for i, month in enumerate(["2026-02", "2026-03", "2026-04"]):
            qty = 500000 + (50000 if i == 2 else 0)  # inject a real step change in the last month
            resp = client.post(f"/api/factories/{onboarded_id}/activity", json=[{
                "process_id": "kiln",
                "activities": [{"fuel_key": "natural_gas", "unit": "SCM", "quantity": qty, "month": month}],
            }])
            if resp.status_code != 200:
                failures.append(f"smoke test POST /api/factories/{{id}}/activity ({month}): "
                                 f"got {resp.status_code}, expected 200")

        final = resp.json() if resp.status_code == 200 else {}
        if final.get("anomaly_check_status") != "available":
            failures.append(f"smoke test: after 4 months of real activity, anomaly_check_status="
                             f"'{final.get('anomaly_check_status')}', expected 'available' — the live "
                             f"feature-window job (routers/onboarding.py recompute) did not activate")
        else:
            print(f"  OK  live feature-window job activated anomaly detection after 4 months "
                  f"(equipment: {final['equipment']})")

    print("  SKIPPED  POST /api/ask, /api/ask/stream — need a live Ollama server, "
          "not exercised here to keep this smoke test fast and deterministic")

    # Leak diagnostics (compressed air / refrigerant / water benchmark / cross-process insights)
    seed_fid = factories[0]["id"]
    ca = client.post(f"/api/factories/{seed_fid}/leak-assessments/compressed-air/load-unload-test", json={
        "rated_capacity_cfm": 500, "load_time_min": 3.0, "unload_time_min": 7.0,
        "operating_hours_per_year": 6000, "electricity_rate_inr_per_kwh": 8.0,
    })
    if ca.status_code != 201 or abs(ca.json()["leak_rate_pct"] - 30.0) > 0.1:
        failures.append(f"leak-assessments compressed-air (load/unload): got {ca.status_code}, "
                         f"expected 201 with leak_rate_pct=30.0 (3/(3+7)*100)")
    else:
        print(f"  OK  POST .../leak-assessments/compressed-air/load-unload-test -> 201, "
              f"leak_rate_pct={ca.json()['leak_rate_pct']}")

    ref = client.post(f"/api/factories/{seed_fid}/leak-assessments/refrigerant", json={
        "refrigerant_key": "r404a", "nameplate_charge_kg": 1000, "annual_topup_kg": 142,
        "refrigerant_cost_inr_per_kg": 1200,
    })
    expected_co2e = 142 * 3922 / 1000  # kg topup x GWP100 / 1000 -> tCO2e
    if ref.status_code != 201 or abs(ref.json()["co2e_tpy"] - expected_co2e) > 0.5:
        failures.append(f"leak-assessments refrigerant: got {ref.status_code}, expected 201 with "
                         f"co2e_tpy~={expected_co2e} (GWP formula regressed?)")
    else:
        print(f"  OK  POST .../leak-assessments/refrigerant -> 201, co2e_tpy={ref.json()['co2e_tpy']} "
              f"(matches 142kg x GWP3922/1000)")

    hist = client.get(f"/api/factories/{seed_fid}/leak-assessments")
    if hist.status_code != 200 or len(hist.json()) < 2:
        failures.append(f"GET .../leak-assessments: got {hist.status_code}, expected >=2 persisted rows")
    else:
        print(f"  OK  GET .../leak-assessments -> 200, {len(hist.json())} persisted rows")

    wb = client.get(f"/api/factories/{seed_fid}/water-benchmark")
    if wb.status_code != 200:
        failures.append(f"GET .../water-benchmark: got {wb.status_code}, expected 200")
    else:
        print(f"  OK  GET .../water-benchmark -> 200 (available={wb.json()['available']})")

    cpi = client.get(f"/api/factories/{seed_fid}/cross-process-insights")
    if cpi.status_code != 200:
        failures.append(f"GET .../cross-process-insights: got {cpi.status_code}, expected 200")
    else:
        print(f"  OK  GET .../cross-process-insights -> 200, {len(cpi.json())} insight(s)")

    # Capacity-band benchmark level — real, sourced for Ceramics only
    ceramics_fid = next((f["id"] for f in factories if f["sector"] == "Ceramics"), None)
    if ceramics_fid:
        bm = client.get(f"/api/factories/{ceramics_fid}/benchmark")
        levels = bm.json()[0]["levels"] if bm.status_code == 200 and bm.json() else []
        cb = next((l for l in levels if l["level"] == "capacity_band"), None)
        if cb is None or not cb["available"]:
            failures.append(f"GET .../benchmark: capacity_band level missing/unavailable for a Ceramics "
                             f"factory ({ceramics_fid}) — expected available=True (sourced sector)")
        else:
            print(f"  OK  GET .../benchmark capacity_band level -> available, {cb['note']}")
    chem_fid = next((f["id"] for f in factories if f["sector"] == "Chemicals"), None)
    if chem_fid:
        bm = client.get(f"/api/factories/{chem_fid}/benchmark")
        levels = bm.json()[0]["levels"] if bm.status_code == 200 and bm.json() else []
        cb = next((l for l in levels if l["level"] == "capacity_band"), None)
        if cb is None or cb["available"]:
            failures.append(f"GET .../benchmark: capacity_band level for a Chemicals factory ({chem_fid}) "
                             f"should be honestly unavailable (not sourced) but reported available=True")
        else:
            print("  OK  GET .../benchmark capacity_band level -> honestly unavailable for Chemicals (not sourced)")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-symbiosis", action="store_true", help="skip the MiniLM-loading step (slow)")
    parser.add_argument("--skip-autoencoder", action="store_true", help="skip the PyTorch retrain sanity check (slow)")
    parser.add_argument("--update-baseline", action="store_true", help="record current numbers as the new baseline")
    args = parser.parse_args()

    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))

    stage_data_pipeline()
    stage_seed_backend()
    zscore_result = stage_zscore_eval(baseline)
    benchmark_result = stage_benchmark_model(baseline)
    symbiosis_result = {"n_matches": baseline["symbiosis_matcher"]["n_matches"]}
    if not args.skip_symbiosis:
        symbiosis_result = stage_symbiosis(baseline)
    if not args.skip_autoencoder:
        stage_anomaly_autoencoder(baseline)
    stage_smoke_test()

    if args.update_baseline:
        baseline["recorded_at"] = "MANUALLY UPDATED — replace with today's date"
        baseline["zscore_anomaly_detector"]["precision"] = zscore_result["precision"]
        baseline["zscore_anomaly_detector"]["recall"] = zscore_result["recall"]
        baseline["benchmark_model"]["random_kfold_improvement_pct"] = benchmark_result["random_kfold_improvement_pct"]
        baseline["benchmark_model"]["leave_one_cluster_out_improvement_pct"] = benchmark_result["leave_one_cluster_out_improvement_pct"]
        baseline["symbiosis_matcher"]["n_matches"] = symbiosis_result["n_matches"]
        BASELINE_PATH.write_text(json.dumps(baseline, indent=2) + "\n", encoding="utf-8")
        print(f"\nBaseline updated at {BASELINE_PATH} — review the diff before committing.")

    print("\n" + "=" * 60)
    if warnings:
        print(f"{len(warnings)} WARNING(S) (not blocking):")
        for w in warnings:
            print(f"  WARN: {w}")
    if failures:
        print(f"{len(failures)} FAILURE(S):")
        for f in failures:
            print(f"  FAIL: {f}")
        print("\nVALIDATION FAILED — do not ship this change.")
        return 1

    print("ALL CHECKS PASSED.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
