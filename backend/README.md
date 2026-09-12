# backend

Phase 2 (database) + Phase 4 basics (API) of the Induscope build plan. FastAPI +
SQLAlchemy over a 12-table schema, seeded from `data-pipeline/`'s Phase-1 output by
actually running it through the engine/intelligence code below — nothing in the
database is hand-typed.

## What's real here

- `app/models.py`, `app/seed.py` — these were referenced everywhere (`from ..models
  import ...`, `from ..seed import ...`) but **did not exist** before this phase; the
  pre-existing `app/engine/*` and `app/intelligence/*` modules could not even be
  imported. They exist now, and `app/seed.py` reads from `data-pipeline/clean/*.csv`
  (the corrected, sourced Phase-1 output) rather than the older, partially-mis-cited
  `backend/data/*.json`.
- `app/db/` — the 12-table schema (SQLAlchemy models), Alembic migrations, and
  `seed_loader.py`, which loads `data-pipeline/synth/factories_synthetic.json` and
  computes every derived value (CO2e, benchmark deviation, severity, anomalies,
  root-cause text, sized recommendations) by calling the real functions in
  `app/engine` and `app/intelligence` — see `data-pipeline/LIMITATIONS.md` #5 for why
  this matters.
- `app/routers/` — FastAPI endpoints backed by the database, described below.

## A real bug this phase found and fixed

Seeding the actual 120-factory dataset through `app/intelligence/anomaly.py` for the
first time (it had never been run against real-scale data before) surfaced a genuine
methodological problem: its original defaults (`z_limit=2.0, rel_guard=0.08`) flagged
**~8% of all equipment-months** as anomalies (575 false positives vs. 26 real
injected ones — precision 0.04, recall 1.00). A threshold sweep against the labelled
ground truth found `z_limit=2.5, rel_guard=0.15` gives precision 0.57 / recall 0.92 —
now the default (live number drifts slightly with dataset regeneration; regression-tested
in `validation/baseline_metrics.json` via `scripts/validate_all.py`). Full writeup:
`data-pipeline/LIMITATIONS.md` #7. This is exactly the
"false positives from normal behaviour" failure mode this whole project exists to
avoid (see repo-root `CLAUDE.md`) — worth fixing for real, not papering over.

## Running it

```bash
cd backend
pip install -r requirements.txt

# apply the schema (SQLite by default — see app/db/base.py for Postgres via DATABASE_URL)
python -m alembic upgrade head

# load data-pipeline output through the real engine/intelligence code
python -m app.db.seed_loader

# serve the API
python -m uvicorn app.main:app --port 8811
```

Then e.g.:
```bash
curl http://127.0.0.1:8811/api/clusters
curl http://127.0.0.1:8811/api/factories/morbi-ceramics-01
curl http://127.0.0.1:8811/api/factories/morbi-ceramics-01/benchmark
```

## Endpoints implemented (Phase 4, no ML dependency)

| Endpoint | Notes |
|---|---|
| `GET /api/clusters` | live factory + open-anomaly counts, not hardcoded |
| `GET /api/clusters/{id}/factories` | |
| `GET /api/factories/{id}` | totals + all equipment |
| `GET /api/factories/{id}/equipment` | |
| `GET /api/factories/{id}/emissions` | every record shows the formula's inputs (factor, source) |
| `GET /api/factories/{id}/benchmark` | global/India levels honestly reported `available: false` — no sourced dataset exists for them, not fabricated. Also includes an `ml_predicted` level (`ml/benchmark_model.py`) and a `capacity_band` level (real small/medium/large-scale adjustment, sourced for Ceramics only — see `data-pipeline/clean/capacity_band_multipliers.csv`) alongside the sourced flat benchmark |
| `GET /api/factories/{id}/anomalies` | |
| `GET /api/factories/{id}/diagnosis/{anomaly_id}` | evidence chain from the real rule engine; `explanation_source: "deterministic_fallback"` until Phase 3's LLM lands |
| `GET /api/factories/{id}/recommendations` | sized per-equipment, not a flat catalog lookup |
| `GET /api/interventions`, `GET /api/emission-factors` | static catalogs |
| `GET /api/scale-projection` | methodology string is in the response itself, not separate docs |
| `POST /api/factories` | real onboarding — same engine, real sourced benchmark lookup + severity + root-cause (fixed in Phase 5 tail — previously hardcoded benchmark=0/severity="ok"), `anomaly_check_status: "not_available"` (honest, not faked). **Known gap**: `OnboardFactoryIn` has no waste fields yet, so onboarded factories always show 0 t/yr waste and 0% circularity even if the Intake page's waste/recovered inputs are filled in — those fields aren't sent to this endpoint. |
| `POST /api/factories/{id}/activity` | append another real month of activity for an already-onboarded process (onboarding above is one-shot). Auto-triggers the recompute job below, so `anomaly_check_status` moves from `"not_available"` to `"available"`/`"partial"` on its own once enough real months exist — see `app/routers/onboarding.py`. |
| `POST /api/factories/{id}/recompute` | the live feature-window job: re-checks every process against `anomaly.py`'s own `len(series) < 4` minimum and activates real anomaly detection (same z-score rule as the 120 seeded factories) for any that now qualify. Idempotent, safe to call repeatedly. |
| `GET /api/factories/summary` | lightweight id/name/co2e/severity variant of the bulk listing below, no nested equipment/recommendations — for map/portfolio views that don't need per-process detail. |
| `POST /api/factories/{id}/leak-assessments/compressed-air/load-unload-test` | compressed-air leak % from the real DOE/Compressed Air Challenge load/unload timing test — no ultrasonic survey needed. See `app/intelligence/leak_estimators.py`. |
| `POST /api/factories/{id}/leak-assessments/compressed-air/unaudited-estimate` | fallback using the literature-cited 20-30% unaudited-system range when no timing test has been run — clearly flagged as a range, not a measurement. |
| `POST /api/factories/{id}/leak-assessments/refrigerant` | refrigerant leak % + GWP-weighted CO2e from top-up volume vs. nameplate charge — computable straight from purchase invoices, no sensor. |
| `GET /api/factories/{id}/leak-assessments` | every leak assessment ever run for a factory, persisted (not recomputed on each view). |
| `GET /api/factories/{id}/water-benchmark` | sourced water-intensity benchmark (TERI Tirupur study), honestly `available: false` outside textile dyeing/finishing — see `app/water_benchmark.py`. |
| `GET /api/factories/{id}/cross-process-insights` | structural heat-source/heat-sink pairing check across equipment (the root-cause rules in `app/intelligence/rootcause.py` are all per-equipment) — a pattern flag, not a sized recommendation. |
| `GET /api/factories/{id}` `worker_exposure_flags` field | keyword-heuristic VOC/solvent exposure risk notes on process labels — disclosed as a heuristic, not a measured exposure reading. |

All of the above are motivated directly by a HackOut'26 research doc, "Industrial Emission Leak-Point Detector" — see its Parts A.1/A.2/A.4 and Scenario walkthroughs (F.2/F.3) for the sourced methods each endpoint implements.
| `GET /api/factories/{id}/symbiosis-matches`, `GET /api/symbiosis/network` | real matches from `ml/symbiosis_model.py` (Phase 3c) |
| `POST /api/factories/{id}/ask` | tool-calling explainer, factory-scoped — `{"question": "..."}` |
| `POST /api/ask` | tool-calling explainer, global/cross-factory — `{"question": "...", "factory_id": null}`. Handles "which factory is best/worst", "what's wrong with X", cluster comparisons — powers the chat widget |
| `GET /api/ml/status` | what's actually active for each Phase 3 ML component (`ml/registry.py`) |
| `GET /api/scale-projection?factory_count=N` | now also returns `projected_carbon_credit_value_inr` (illustrative CCTS-indicative valuation, see `app/carbon_credit.py`) |

## ML layer (Phase 3) — see `ml/README.md`

Built and live: LightGBM benchmark predictor (beats the flat benchmark), MiniLM+FAISS
symbiosis matcher (140 real matches), and the tool-calling Ollama explainer
(`POST /api/factories/{id}/ask`). The PyTorch anomaly autoencoder was built and
evaluated but does NOT beat the existing z-score rule — documented and kept out of
production (see `ml/LIMITATIONS.md`); the z-score rule below is still the real
in-production anomaly detector, not a placeholder. `ModelRegistry` (lazy-loading
wrapper for the above) is the one remaining piece — see `[[induscope_build_plan]]`
memory for the full phase history.
