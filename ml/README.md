# ml — Phase 3 (ML layer)

Each model here is built and validated standalone against the real Phase 1/2 dataset
before anything gets wired into the API — see the root `README.md` roadmap for why.

## Status

| Component | Status |
|---|---|
| Benchmark predictor (LightGBM) | **Built** — `benchmark_model.py` — beats flat benchmark |
| Anomaly autoencoder (PyTorch) | **Built and evaluated** — `anomaly_model.py` — does **not** beat the existing z-score rule; documented and kept out of production, see `LIMITATIONS.md` |
| Symbiosis matcher (MiniLM + FAISS) | **Built and live** — `symbiosis_model.py` — real matches (count regression-tested in `validation/baseline_metrics.json`, moves as the dataset changes) served via `/api/symbiosis/network` and wired into the frontend |
| Explainer (Ollama + tool-calling) | **Built and live** — `explainer.py` — answers compound "which strategy is best" questions by actually running the optimizer, served via `POST /api/factories/{id}/ask` |
| `ModelRegistry` | **Built and live** — `registry.py` — served via `GET /api/ml/status` |

**Phase 3 is complete** as of this entry — all four ML/rule components exist, are validated (or, for the autoencoder, honestly rejected) against real ground truth, and are reachable through the API.

## Benchmark predictor (`benchmark_model.py`)

Predicts a process's expected intensity (kgCO2e/t) from its profile (sector, process
kind, output scale, fuel mix) instead of a single fixed per-sub-sector number.

```bash
cd ..                      # repo root
python -m ml.benchmark_model
```

Reads training data straight from the seeded backend database (`python -m
app.db.seed_loader` must have been run first — see `backend/README.md`), trains, and
writes `artifacts/benchmark_model.txt` + `artifacts/benchmark_metrics.json`.

**Two honest validation regimes are reported, not one** — they answer different
questions:

- `random_kfold` — held-out factories from clusters already seen elsewhere in
  training. Result when this section was written: **+36.9% MAE improvement** over
  the flat benchmark.
- `leave_one_cluster_out` — held-out clusters never seen in training at all (the
  strict "brand-new cluster" test). Result when this section was written: **+6.3%**
  — real, but far more modest.

**Use accordingly**: trust this model's prediction for a factory in a cluster the
training data already covers; fall back to the flat per-sub-sector benchmark for a
factory in a cluster with zero prior data, until more data exists per cluster.

These two numbers move a little every time the synthetic dataset is regenerated
(different RNG draw for the noise term each run). The live numbers, regression-tested
against a floor on every run, live in `validation/baseline_metrics.json` — check
`artifacts/benchmark_metrics.json` after running `scripts/validate_all.py` for the
figures from the most recent actual run, not this paragraph.

This split — and the fact that getting here required fixing a real bug in the Phase 1
synthetic generator (the original per-factory noise had zero correlation to anything,
making the flat benchmark mathematically unbeatable) — is documented in full in
`data-pipeline/LIMITATIONS.md` #9.

## Anomaly autoencoder (`anomaly_model.py`)

Built to replace the z-score rule in `backend/app/intelligence/anomaly.py` with a
model that learns each process kind's typical monthly shape. **Result: it does not
beat the z-score rule** on this dataset (precision 0.01 vs. the rule's 0.57, at
matched or lower recall) — evaluated against the same 26 ground-truth labels, under
two threshold strategies, across multiple training configurations. Full reasoning in
`LIMITATIONS.md`. **The z-score rule stays in production.** This is committed anyway:
the honest evaluation harness (train → score against real ground truth → compare
head-to-head against the current baseline) is the reusable artifact, and the documented
negative result tells the next attempt exactly what's missing (multi-year history per
factory) rather than inviting another architecture-guessing pass.

**Revisit attempt #2** (`anomaly_ensemble.py`): rather than extending the synthetic
generator's time series to get that multi-year history (investigated, not attempted —
see `LIMITATIONS.md` for the real blast-radius reason: it would silently corrupt
`output_tonnes_per_year`/`co2e_tpy` calculations the rest of the app depends on),
tried combining the z-score rule and the autoencoder's reconstruction error as two
independent signals. Still does not beat the production rule on both precision and
recall — but the AND-agreement variant does beat it on precision alone (0.533 vs 0.49,
46% fewer false positives) at a real recall cost, suggesting a two-tier confidence
system as a future product idea rather than a detector swap. Full breakdown in
`LIMITATIONS.md`; both this and the autoencoder above are sanity-checked on every
`scripts/validate_all.py` run (flagged, not failed, if a future run's result changes).

```bash
cd ..
python -m ml.anomaly_model
```

## Symbiosis matcher (`symbiosis_model.py`)

Matches one factory's tagged waste stream to another's accepted input — 50% MiniLM
semantic similarity / 25% quantity fit / 25% haversine proximity, per the Induscope
vision doc's weighting. This was blocked until this phase added real schema: Phase 1/2
only tracked aggregate hazardous/general waste tonnage, not typed streams, so this
phase added `WasteStream`/`AcceptedInput` tables, a sourced tag vocabulary
(`data-pipeline/clean/waste_stream_profiles.csv`), and generator support before the
matcher itself could mean anything.

```bash
cd ..
python -m ml.symbiosis_model
```

Loads real tagged waste streams + accepted inputs from the seeded DB, embeds their
descriptions with `all-MiniLM-L6-v2`, searches via FAISS, filters by real haversine
distance between real factory coordinates (≤60 km), and writes results into the
`symbiosis_matches` table — matches on the current dataset (count moves as the waste
catalog and dataset change; live figure is regression-tested in
`validation/baseline_metrics.json` via `scripts/validate_all.py`, not this number),
served live via
`GET /api/symbiosis/network` and `GET /api/factories/{id}/symbiosis-matches`, and
wired into the frontend's Symbiosis panel and regulator rollup.

**A real false positive was found and fixed while building this**: the matcher
initially proposed `textile_sludge → cotton_waste` (ETP dye sludge substituting for
cutting-room fibre) at 0.459 semantic similarity — topically related (both textile
waste) but not physically interchangeable. The similarity threshold was raised to
0.65, chosen from the actual score gap in the data (exact-tag matches scored
0.84-0.86), which excludes that one false positive while keeping every legitimate
match. See the comment in `symbiosis_model.py` for the full reasoning.

**Every `co2_avoided_tpy` figure is `is_placeholder=True`** — no sourced
embodied-carbon dataset exists for these waste categories (see
`data-pipeline/LIMITATIONS.md` #1). The ₹-savings figures ARE real: each side's own
disposal/virgin-material cost rate × real matched tonnage (with a documented 60%
capture assumption on the recipient's side).

## Explainer (`explainer.py`)

**Prerequisite**: a local Ollama server (`ollama serve`, default `http://localhost:11434`)
with `llama3.1:8b` pulled (`ollama pull llama3.1:8b`, ~4.9GB). Without it, every
question is answered by the deterministic fallback described below — the code
degrades, it doesn't fail.

A tool-calling agent (Ollama, `llama3.1:8b`) that answers questions about a factory — including compound
optimization questions like *"which intervention combination gives the best result
under a 20 lakh budget"* — by actually calling a real optimizer
(`backend/app/intelligence/simulator.py`, a new Python port of the frontend's
what-if simulator) against real database data, not by guessing or template-matching
keywords. This was an explicit requirement carried over from planning, not part of
the original Induscope vision doc's explainer scope.

```bash
cd ..
python -m ml.explainer --factory-id morbi-ceramics-01 --question "Which strategy will give the best results, budget 20 lakh?"
```

Served live three ways: `POST /api/factories/{id}/ask` (factory-scoped),
`POST /api/ask` (global, non-streaming), and `POST /api/ask/stream` (global,
Server-Sent Events — what the frontend chat widget actually uses).

**Streaming** (`ask_stream()`) sends tokens to the caller as Ollama generates
them, instead of blocking 5-10s for the whole answer. This was verified safe
before building it: probed Ollama's wire format directly and confirmed a
tool-call decision always arrives as one complete chunk, never token-by-token,
while a genuine final text answer streams token-by-token. Since the
empty-result safety check (below) depends only on the PREVIOUS tool call's
already-known result, it runs BEFORE the next generation request even starts —
so streaming never risks showing the user a token of an answer that then has
to be retracted. `ask()` is now a thin synchronous wrapper over `ask_stream()`
for callers (CLI, the non-streaming endpoints) that don't need it.

Each request now also opens exactly ONE SQLAlchemy session, shared across
every tool call in that turn, instead of one session per tool call — a small
latency cleanup that fell out naturally from restructuring for streaming.

**Eight tools** the model can call:
- `get_factory_summary`, `get_recommendations`, `simulate_combination` (check one
  specific combination), `find_best_strategy` (exhaustively brute-forces every
  combination of a factory's recommendations — typically ≤20, so 2^20 combinations is
  a few seconds of Python — under an optional budget/payback constraint; a real
  optimum, not a greedy heuristic).
- `list_factories`, `rank_factories` (best/worst by benchmark deviation, hotspot
  count, or total CO2e — for "which factory needs the most help" style questions,
  including indirect phrasings), `get_cluster_summary`, `search_factory` (resolve a
  partial/approximate name the user typed to a real factory_id) — added so the
  explainer can answer cross-factory and "what problem does X have" questions, not
  just single-factory optimization ones.

**Two real, reproducible LLM failure modes were found and guarded against.** The first:
llama3.1:8b correctly calls tools and gets correct numbers back, but can misstate them by ~1000x
in its own prose (Indian lakh/crore confusion) and can mis-convert "20 lakh" to the
wrong rupee figure when constructing a tool call. Prompt tightening reduced this but
a stochastic model offers no guarantee, so `ask()` returns `verified_data` — the raw,
directly-computed tool result — alongside the LLM's prose, and treats the LLM's own
restatement of a number as explanatory colour, never as the authoritative value.

The second, more serious: given an empty cross-factory lookup (a hallucinated
sector/cluster filter matching nothing), the model **fabricated a nonexistent factory
name** ("Sasan Power Plant") rather than reporting no data. Guarded two ways — the
ranking tools now drop a filter that matches zero rows instead of returning empty, and
`ask()` hard-discards the LLM's prose entirely (not just flags it) whenever the last
tool result was empty/erroring, replacing it with a message built directly from the
tool result. Full writeup of both: `LIMITATIONS.md`.

**Deterministic fallback**: if Ollama is unreachable, the question is answered by
calling the same real tool directly and templating the result — same computation,
lakh/crore-formatted string instead of LLM prose. Tested by simulating a connection
failure; produces the identical numeric answer.

## Model registry (`registry.py`)

A single lazy-loading access point for the four components above — loads the
LightGBM booster, MiniLM embedder, etc. once and caches them, rather than every
caller reloading an expensive model per request. Deliberately thin: it does not
reimplement any scoring logic, each component's own module stays independently
runnable.

```bash
cd ..
python -m ml.registry   # prints registry.status()
```

Also served via `GET /api/ml/status`. **Read `status()` before assuming any ML
component is in the live request path** — it reports what's actually active, not
just what exists on disk. In particular it reports `anomaly_detector.active_detector:
"zscore_rule"` always, with the autoencoder's rejection verdict alongside it, so
nobody has to rediscover that finding by reading source code.

`predict_benchmark_ratio(...)` is the one method that does real inference (loads the
saved LightGBM booster, reconstructs the exact categorical encoding used at training
time, returns a predicted ratio-to-benchmark) — verified against a known factory's
real data (predicted 0.97 vs. actual 0.924, consistent with the model's measured MAE).
**Now wired into `GET /api/factories/{id}/benchmark`** as an `"ml_predicted"` level
alongside the sourced flat benchmark — additive, not a replacement, so a caller
sees both and the honest accuracy split (+36.9%/+6.3%) inline via that level's
`note`. Falls back to `available: false` (not a 500) if the model artifact hasn't
been generated yet.

## Next

Symbiosis matching's own remaining gap:
fly_ash — the one cross-sector tag in the vocabulary, Chemicals boiler by-product →
Ceramics body filler — currently produces zero matches because Morbi's ceramics
cluster is simply too far from every chemicals cluster in this dataset at the 60 km
radius. That's real Gujarat geography, not a bug, but worth knowing if a demo expects
to see it.
