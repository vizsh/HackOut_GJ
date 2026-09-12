# ml — known limitations

## The explainer fabricated a nonexistent factory when a tool result was empty — hard-guarded

Extending `ml/explainer.py` with cross-factory tools (`rank_factories`, for questions like
"which factory is performing best") surfaced a failure mode worse than the earlier
lakh/crore unit-confusion bug: when `rank_factories` happened to return an empty result
(`{"ranked": [], "total_considered": 0}` — root cause: the model occasionally passed a
`sector`/`cluster_id` filter value that matched no factories, e.g. a district name like
"Bhavnagar" instead of the real cluster_id "alang"), llama3.1:8b did not report the empty
result. It **invented a completely fictitious factory name** ("Sasan Power Plant" — a real
Indian power plant it knows from training data, not anything in this system) and presented
it as a confident, plausible-sounding answer.

This is the more serious failure mode of the two found in Phase 3d: the earlier lakh/crore
bug misstated a real number, but this one asserted an entity that does not exist at all. Two
fixes, applied together rather than relying on either alone:

1. **Tool-level**: `rank_factories`/`list_factories`/`get_cluster_summary` now detect a
   filter that matched zero rows, drop it, and return the unfiltered ranking with a
   `filter_dropped` field explaining what happened and listing the valid sector/cluster
   values — so the tool itself rarely returns empty in the first place.
2. **Structural guard in `ask()`**: `_tool_result_is_empty_or_error()` inspects the LAST
   tool result before returning the LLM's final prose. If it's empty or an error, the LLM's
   prose is **discarded entirely** and replaced with a message built directly from the tool
   result — the model never gets a chance to fabricate a substitute answer when the real
   data came back empty. Verified: the exact failing question, re-run multiple times after
   both fixes, now consistently returns the correct real factory every time.

**Takeaway for anything built on top of this**: never treat a small local model's free-form
answer as safe by default just because tool-calling is wired up — an empty or unexpected
tool result is exactly when a model is most likely to fill the gap with something invented.
Guard the empty/error case explicitly; don't assume "it has real data most of the time" is
good enough.

## The anomaly autoencoder (Phase 3b) does not beat the z-score rule — kept out of production

`anomaly_model.py` was built, trained, and rigorously evaluated against the same 26
ground-truth injected anomalies used to validate and retune the existing z-score rule
(`backend/app/intelligence/anomaly.py`, see `data-pipeline/LIMITATIONS.md` #7). Result,
across two threshold strategies (per-equipment robust MAD, and a global percentile
cutoff) and multiple training runs (different epoch counts, learning rates): **it does
not match the z-score rule's precision/recall**, and no threshold choice closes that
gap.

| Approach | Precision | Recall |
|---|---|---|
| z-score rule (in production) | 0.57 | 0.92 |
| Autoencoder, best threshold found | 0.01 | 0.62 |

*Numbers above are frozen from the run that produced this writeup (26 ground-truth
labels at the time). Regenerating the synthetic dataset shifts the RNG sequence and
therefore which months get labeled anomalous, so these will drift slightly — the
current, live numbers (recorded 0.553/0.913 against 23 labels) are tracked and
regression-tested in `validation/baseline_metrics.json`, run via `scripts/validate_all.py`.
Treat that file as the source of truth for "what's true right now"; this table as
"what the original decision was based on."*

**Why, in real numbers:** anomalous months do have a real, measurable signal — roughly
4-5x higher mean reconstruction error than normal months (1.15 vs. 0.29 in the recorded
run). But anomalies are only 0.36% of all equipment-months (26 of 7,176), and the
normal-month error distribution — built from pooling 600 series of only 12 monthly
samples each across a shared conditional model — has a long enough tail from ordinary
month-to-month noise that no single threshold separates the two without either missing
most real anomalies or flagging hundreds of normal months as anomalous.

The z-score rule wins here because it exploits each equipment's own within-series
statistics directly (leave-one-out z against that specific 12-month series), rather
than a shared cross-equipment reconstruction model. With only one year of history per
factory, that turns out to be the more data-efficient approach at this dataset size.

**What would change this:** multiple years of history per factory (giving the
autoencoder real seasonal structure to learn instead of 12 samples), or a much larger
factory count. Neither exists yet — this is not a "try a different architecture" gap,
it's a "we don't have enough history per series yet" gap.

**Decision:** the z-score rule stays in production. This model is committed and
documented — including the negative result — rather than discarded, because the honest
evaluation methodology (same ground truth, same rigor as everything else in this
project) is itself the useful artifact: the next attempt at this (with real or
multi-year data) has a working evaluation harness and a documented reason not to expect
success from more threshold-tuning alone.

Full metrics: `artifacts/anomaly_metrics.json`. Reproduce with `python -m ml.anomaly_model`
(requires the backend seeded first — see `backend/README.md`).

### Revisit attempt #2: an ensemble instead of a replacement — still does not beat baseline

The prescription above ("multiple years of history per factory") would mean extending
`data-pipeline/scripts/generate_synthetic.py`'s time series past 12 months — investigated, and
NOT attempted, because of its blast radius: `output_tonnes_per_year`, every equipment's
`co2e_tpy`, every benchmark ratio, severity classification, and sized recommendation are
currently computed by summing/dividing over an assumed-12-month year (see
`backend/app/db/seed_loader.py`'s `annual_output_t = sum(fac_raw["monthly_output_tonnes"])` and
`co2e_tpy = sum(v for _, v in monthly_co2e)`). Extending months without re-deriving every one of
those correctly would silently corrupt numbers the rest of the app depends on — a bigger,
riskier change than this item's priority (last on the roadmap, explicitly conditional) warranted.

Instead, `ml/anomaly_ensemble.py` tried a genuinely different angle that touches none of that:
combining the production z-score rule with the autoencoder's reconstruction error as two
independent signals, rather than one replacing the other. Three combination strategies, evaluated
against the same real ground truth:

| Variant | Precision | Recall |
|---|---|---|
| z-score rule alone (production baseline) | 0.49 | 0.962 |
| OR (either signal flags) | 0.024 | 1.0 |
| AND (both must agree) | **0.533** | 0.615 |
| Weighted sum (matched to baseline's flag count) | 0.196 | 0.385 |

None beats the baseline on **both** precision and recall — OR trades almost all precision for a
small recall gain (adds the autoencoder's own false positives on top); the weighted sum is worse
on both counts. **AND is the one genuinely interesting result**: requiring the autoencoder to
independently corroborate a z-score flag cuts false positives by 46% (26 → 14) and pushes
precision *above* the production rule (0.533 vs 0.49) — at the real cost of missing more true
anomalies (recall 0.615 vs 0.962, 10 false negatives vs 1).

**Not adopted as a replacement** (the strict bar — beat baseline on both metrics — isn't met), but
worth naming as a real, different possible product shape for a future decision: a two-tier
confidence system (z-score flags a candidate; AND-agreement with the autoencoder promotes it to
"confirmed," z-score-only stays "suspected") rather than a single detector with one threshold.
That's a product/UX decision, not something to silently ship as a behaviour change — flagged here,
not implemented.

Full metrics: `artifacts/anomaly_ensemble_metrics.json`. Reproduce with `python -m ml.anomaly_ensemble`.

## The explainer's LLM misstates numbers in its own prose — guarded against structurally

Testing `ml/explainer.py` (Phase 3d) against a real compound question ("which strategy is
best under a 20 lakh rupee budget") found llama3.1:8b has two real, reproducible failure
modes, even though the underlying tool computation was correct both times:

1. **Argument construction error**: asked to enforce a "20 lakh rupee" budget, the model
   called `find_best_strategy` with `budget_inr=200000` (2 lakh) instead of `2000000`
   (20 lakh) — a 10x Indian-numbering (lakh/crore) conversion error in the tool call itself.
2. **Restatement error**: given a correct tool result of `capex_inr: 133000` (Rs 1.33 lakh),
   the model's own prose reported "a capital expenditure of 1.33 crore rupees" — off by
   ~1000x, again a lakh/crore confusion, this time in describing a number it had just
   received correctly.

Tightening the system prompt (explicit "these are plain rupee numbers, do not convert to
lakhs/crores yourself, you have made this mistake before") fixed both in the next test run,
but this is a stochastic model — prompt tuning reduces the failure rate, it does not
guarantee correctness. Given this project's rule that nothing gets asserted without being
real, prompt tuning alone was not treated as sufficient.

**Structural fix**: `ask()` returns `verified_data` — the raw return value of the last tool
call, taken directly from the Python computation, never re-typed by the model — alongside
the LLM's `answer` prose. Any caller (the API, a UI) should treat `verified_data` as the
authoritative number and the prose as explanatory colour only. This is documented in
`ask()`'s own docstring, not just here, so it isn't missed by whoever wires the frontend
to this next.
