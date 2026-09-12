"""Explainer — Phase 3d.

A tool-calling agent (Ollama, llama3.1:8b) that can answer compound questions
like "which intervention combination gives the best result here" by actually
CALLING the real simulator/optimizer (backend/app/intelligence/simulator.py)
against real database data — not template-matching keywords, and not letting
the LLM invent numbers. This was an explicit requirement carried over from
planning: a plain diagnosis-explainer wasn't enough; it needs to reason about
what-if scenarios the same way a human analyst would — by actually running
them.

Every numeric claim in a response traces to a tool call's return value. The
system prompt tells the model this directly and the tool functions are the
ONLY source of factory-specific numbers available to it.

Deterministic fallback: if Ollama is unreachable or errors, the question is
answered by directly calling the most relevant tool with sensible defaults
and formatting the result as a template sentence — the underlying computation
is identical (same simulator/optimizer functions, same real data), only the
natural-language phrasing is templated instead of LLM-composed. This matches
the project's established fallback discipline: never a canned answer with no
real computation behind it, never a hard failure with nothing at all.

Streaming (`ask_stream`): tested Ollama's actual wire behaviour before
building this (see the two probe scripts referenced in commit history) —
a tool-call decision always arrives as a single complete chunk, never
token-by-token, while a genuine final text answer streams token-by-token.
Because the empty-result safety check below depends only on the PREVIOUS
tool call's result (already known before the next Ollama request even
starts), the check can run BEFORE requesting the final answer — so streaming
never risks showing the user a token of a fabricated answer before it can be
retracted. If the last tool result was empty/erroring, no generation call is
made at all; the guard message is emitted immediately instead.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Iterator

import requests

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.db.base import SessionLocal  # noqa: E402
from app.db import models as db  # noqa: E402
from app.intelligence.simulator import EquipmentData, RecommendationData, optimize, simulate  # noqa: E402

OLLAMA_URL = "http://localhost:11434/api/chat"
OLLAMA_MODEL = "llama3.1:8b"
OLLAMA_TIMEOUT_S = 60
MAX_TOOL_ITERATIONS = 5


def _load_equipment(session, factory_id: str) -> list[EquipmentData]:
    factory = session.get(db.Factory, factory_id)
    if factory is None:
        raise ValueError(f"unknown factory_id '{factory_id}'")
    out = []
    for e in factory.equipment:
        recs = [
            RecommendationData(
                id=r.id, equipment_id=e.id, title=r.title, capex_inr=r.capex_inr,
                annual_saving_inr=r.annual_saving_inr, co2_reduction_tpy=r.co2_reduction_tpy,
                payback_months=r.payback_months, confidence=r.confidence,
            )
            for r in e.recommendations
        ]
        out.append(EquipmentData(id=e.id, label=e.label, co2e_tpy=e.co2e_tpy or 0.0, recommendations=recs))
    return out


def _clean_str_arg(value: str | None) -> str | None:
    """Tool-call arguments come from the model as JSON, but it sometimes
    passes the literal string "None"/"null" for an omitted optional
    parameter instead of leaving it out — observed on sector/cluster_id
    filters. Harmless (the empty-filter-retry logic in tool_rank_factories
    already self-heals it) but produces a confusing filter_dropped message
    for a filter the user never actually asked for, so it's normalised here."""
    if value is None or value.strip().lower() in ("none", "null", ""):
        return None
    return value


def _own_session_if_needed(session):
    """Every tool_* function accepts an optional shared `session` so ask()/
    ask_stream() can open ONE SQLAlchemy session per request instead of one
    per tool call (a real, if modest, latency cost once multiple tools get
    called in one conversation turn). Standalone callers (CLI, tests) that
    don't pass a session still get one created and closed automatically."""
    return (session, False) if session is not None else (SessionLocal(), True)


# --- Tool implementations (the ONLY source of factory-specific numbers) ------

def tool_get_factory_summary(factory_id: str, session=None) -> dict:
    s, owned = _own_session_if_needed(session)
    try:
        factory = s.get(db.Factory, factory_id)
        if factory is None:
            return {"error": f"unknown factory_id '{factory_id}'"}
        return {
            "id": factory.id, "name": factory.name, "sector": factory.sector,
            "cluster_id": factory.cluster_id, "total_co2e_tpy": sum(e.co2e_tpy or 0 for e in factory.equipment),
            "equipment": [
                {"id": e.id, "label": e.label, "kind": e.kind, "co2e_tpy": e.co2e_tpy,
                 "severity": e.severity, "actual_intensity": e.actual_intensity,
                 "benchmark_kgco2e_per_t": e.benchmark_kgco2e_per_t, "root_cause": e.root_cause_text}
                for e in factory.equipment
            ],
        }
    finally:
        if owned:
            s.close()


def tool_get_recommendations(factory_id: str, session=None) -> dict:
    s, owned = _own_session_if_needed(session)
    try:
        equipment_list = _load_equipment(s, factory_id)
        return {
            "recommendations": [
                {"id": r.id, "equipment_id": r.equipment_id, "title": r.title, "capex_inr": r.capex_inr,
                 "annual_saving_inr": r.annual_saving_inr, "co2_reduction_tpy": r.co2_reduction_tpy,
                 "payback_months": r.payback_months, "confidence": r.confidence}
                for e in equipment_list for r in e.recommendations
            ],
        }
    finally:
        if owned:
            s.close()


def tool_simulate_combination(factory_id: str, recommendation_ids: list[str], session=None) -> dict:
    s, owned = _own_session_if_needed(session)
    try:
        equipment_list = _load_equipment(s, factory_id)
        result = simulate(equipment_list, set(recommendation_ids))
        return {
            "total_co2e_before_tpy": result.total_co2e_before, "total_co2e_after_tpy": result.total_co2e_after,
            "co2_reduction_tpy": result.co2_reduction_tpy, "capex_inr": result.capex_inr,
            "annual_saving_inr": result.annual_saving_inr, "blended_payback_months": result.blended_payback_months,
            "confidence": result.confidence,
        }
    finally:
        if owned:
            s.close()


def tool_find_best_strategy(factory_id: str, objective: str = "max_co2_reduction",
                             budget_inr: float | None = None, max_payback_months: float | None = None,
                             session=None) -> dict:
    s, owned = _own_session_if_needed(session)
    try:
        equipment_list = _load_equipment(s, factory_id)
        report = optimize(equipment_list, objective=objective, budget_inr=budget_inr, max_payback_months=max_payback_months)
        best = report["best_selection"]
        return {
            "objective": objective, "constraints": report["constraints"],
            "selected_recommendation_ids": best.selected_ids,
            "total_co2e_before_tpy": best.total_co2e_before, "total_co2e_after_tpy": best.total_co2e_after,
            "co2_reduction_tpy": best.co2_reduction_tpy, "capex_inr": best.capex_inr,
            "annual_saving_inr": best.annual_saving_inr, "blended_payback_months": best.blended_payback_months,
            "confidence": best.confidence, "n_combinations_evaluated": report["n_combinations_evaluated"],
        }
    finally:
        if owned:
            s.close()


def _factory_stats(f: db.Factory) -> dict:
    total = sum(e.co2e_tpy or 0.0 for e in f.equipment)
    hotspot_count = sum(1 for e in f.equipment if e.severity == "crit")
    deviations = [
        (e.actual_intensity - e.benchmark_kgco2e_per_t) / e.benchmark_kgco2e_per_t * 100
        for e in f.equipment if e.benchmark_kgco2e_per_t and e.actual_intensity is not None
    ]
    avg_deviation_pct = round(sum(deviations) / len(deviations), 1) if deviations else None
    return {
        "id": f.id, "name": f.name, "sector": f.sector, "cluster_id": f.cluster_id,
        "total_co2e_tpy": round(total, 1), "hotspot_count": hotspot_count,
        "avg_deviation_pct": avg_deviation_pct,
    }


def tool_list_factories(sector: str | None = None, cluster_id: str | None = None,
                         limit: int | float | str = 20, session=None) -> dict:
    sector, cluster_id = _clean_str_arg(sector), _clean_str_arg(cluster_id)
    limit_int = int(limit) if limit else 20
    s, owned = _own_session_if_needed(session)
    try:
        q = s.query(db.Factory)
        if sector:
            q = q.filter(db.Factory.sector == sector)
        if cluster_id:
            q = q.filter(db.Factory.cluster_id == cluster_id)
        factories = q.limit(limit_int).all()
        return {"factories": [_factory_stats(f) for f in factories], "count": len(factories)}
    finally:
        if owned:
            s.close()


def tool_rank_factories(metric: str = "avg_deviation_pct", order: str = "asc",
                         sector: str | None = None, cluster_id: str | None = None,
                         limit: int | float | str = 5, session=None) -> dict:
    """For 'best'/'worst performing factory' questions. Lower avg_deviation_pct
    and lower hotspot_count both mean a BETTER-performing factory (closer to
    or under its sourced sub-sector benchmark) — order='asc' finds the best on
    either metric, order='desc' finds the worst.

    If sector/cluster_id is given but matches nothing (a hallucinated or
    misspelled filter value — observed in testing, e.g. a district name used
    instead of a cluster_id), the filter is DROPPED and the unfiltered
    ranking is returned instead, with `filter_dropped` explaining why —
    rather than returning an empty result that risks the LLM fabricating an
    answer instead of admitting it found nothing (see ask()'s
    _tool_result_is_empty_or_error guard, which this reduces how often is
    even needed)."""
    sector, cluster_id = _clean_str_arg(sector), _clean_str_arg(cluster_id)
    limit_int = int(limit) if limit else 5  # tool-call args arrive as JSON; guard against a float/string limit
    s, owned = _own_session_if_needed(session)
    try:
        q = s.query(db.Factory)
        if sector:
            q = q.filter(db.Factory.sector == sector)
        if cluster_id:
            q = q.filter(db.Factory.cluster_id == cluster_id)
        rows = q.all()

        filter_dropped = None
        if not rows and (sector or cluster_id):
            valid_sectors = sorted({f.sector for f in s.query(db.Factory.sector).distinct()})
            valid_clusters = sorted({c.id for c in s.query(db.Cluster.id).distinct()})
            filter_dropped = (
                f"sector={sector!r} / cluster_id={cluster_id!r} matched no factories — ignored. "
                f"Valid sectors: {valid_sectors}. Valid cluster_ids: {valid_clusters}."
            )
            rows = s.query(db.Factory).all()

        stats = [_factory_stats(f) for f in rows]
        ranked = [st for st in stats if st.get(metric) is not None]
        ranked.sort(key=lambda st: st[metric], reverse=(order == "desc"))
        result = {"metric": metric, "order": order, "ranked": ranked[:limit_int], "total_considered": len(ranked)}
        if filter_dropped:
            result["filter_dropped"] = filter_dropped
        return result
    finally:
        if owned:
            s.close()


def tool_get_cluster_summary(cluster_id: str, session=None) -> dict:
    s, owned = _own_session_if_needed(session)
    try:
        cluster = s.get(db.Cluster, cluster_id)
        factories = s.query(db.Factory).filter_by(cluster_id=cluster_id).all()
        stats = [_factory_stats(f) for f in factories]
        return {
            "cluster_id": cluster_id, "cluster_name": cluster.name if cluster else cluster_id,
            "factory_count": len(factories),
            "total_co2e_tpy": round(sum(st["total_co2e_tpy"] for st in stats), 1),
            "total_hotspots": sum(st["hotspot_count"] for st in stats),
        }
    finally:
        if owned:
            s.close()


def tool_search_factory(query: str, limit: int | float | str = 5, session=None) -> dict:
    """Find a factory by a partial/fuzzy name or id — use this whenever the
    user names a factory that isn't already known to be a valid factory_id."""
    limit_int = int(limit) if limit else 5
    s, owned = _own_session_if_needed(session)
    try:
        like = f"%{query}%"
        rows = s.query(db.Factory).filter(
            db.Factory.name.ilike(like) | db.Factory.id.ilike(like)
        ).limit(limit_int).all()
        return {"matches": [{"id": f.id, "name": f.name, "sector": f.sector, "cluster_id": f.cluster_id} for f in rows]}
    finally:
        if owned:
            s.close()


TOOLS = [
    {"type": "function", "function": {
        "name": "get_factory_summary", "description": "Get a factory's sector, total CO2e, and per-equipment severity/root-cause.",
        "parameters": {"type": "object", "properties": {"factory_id": {"type": "string"}}, "required": ["factory_id"]},
    }},
    {"type": "function", "function": {
        "name": "get_recommendations", "description": "List all available costed interventions for a factory.",
        "parameters": {"type": "object", "properties": {"factory_id": {"type": "string"}}, "required": ["factory_id"]},
    }},
    {"type": "function", "function": {
        "name": "simulate_combination",
        "description": "Compute the exact combined effect (CO2e, CAPEX, saving, payback) of applying a specific set of recommendation ids together. Use this to check ONE candidate combination.",
        "parameters": {"type": "object", "properties": {
            "factory_id": {"type": "string"},
            "recommendation_ids": {"type": "array", "items": {"type": "string"}},
        }, "required": ["factory_id", "recommendation_ids"]},
    }},
    {"type": "function", "function": {
        "name": "find_best_strategy",
        "description": "Exhaustively search ALL combinations of a factory's available recommendations and return the one that truly maximises CO2 reduction (or ROI), optionally under a budget or payback constraint. Use this whenever the user asks which strategy/combination is 'best' or 'optimal' — do not guess or hand-pick a combination yourself.",
        "parameters": {"type": "object", "properties": {
            "factory_id": {"type": "string"},
            "objective": {"type": "string", "enum": ["max_co2_reduction", "max_roi"]},
            "budget_inr": {"type": "number"},
            "max_payback_months": {"type": "number"},
        }, "required": ["factory_id"]},
    }},
    {"type": "function", "function": {
        "name": "list_factories",
        "description": "List factories, optionally filtered by sector or cluster, each with total CO2e, hotspot count, and average benchmark deviation. Use to browse or enumerate factories.",
        "parameters": {"type": "object", "properties": {
            "sector": {"type": "string", "description": "e.g. Ceramics, Chemicals, Textiles, Engineering"},
            "cluster_id": {"type": "string", "description": "e.g. morbi, vapi, surat"},
            "limit": {"type": "integer"},
        }},
    }},
    {"type": "function", "function": {
        "name": "rank_factories",
        "description": "Find the best- or worst-performing factories by a real metric. Use this for ANY question about which factory is best/worst/most-efficient/most-problematic, including indirectly phrased ones (e.g. 'who needs the most help', 'who's doing great'). metric='avg_deviation_pct' or 'hotspot_count' with order='asc' finds the BEST (closest to/under benchmark, fewest hotspots); order='desc' finds the WORST. Do not guess this from get_factory_summary on one factory — this tool checks all of them.",
        "parameters": {"type": "object", "properties": {
            "metric": {"type": "string", "enum": ["avg_deviation_pct", "hotspot_count", "total_co2e_tpy"]},
            "order": {"type": "string", "enum": ["asc", "desc"]},
            "sector": {"type": "string"},
            "cluster_id": {"type": "string"},
            "limit": {"type": "integer"},
        }, "required": ["metric", "order"]},
    }},
    {"type": "function", "function": {
        "name": "get_cluster_summary",
        "description": "Aggregate CO2e and hotspot totals for one Gujarat industrial cluster (e.g. morbi, vapi, surat, rajkot, jamnagar, ankleshwar, vatva, dahej, alang).",
        "parameters": {"type": "object", "properties": {"cluster_id": {"type": "string"}}, "required": ["cluster_id"]},
    }},
    {"type": "function", "function": {
        "name": "search_factory",
        "description": "Find a factory's exact id from a partial or approximate name the user typed. ALWAYS call this first if the user names a factory and you don't already know its exact factory_id from this conversation.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string"}, "limit": {"type": "integer"},
        }, "required": ["query"]},
    }},
]

TOOL_IMPL = {
    "get_factory_summary": tool_get_factory_summary,
    "get_recommendations": tool_get_recommendations,
    "simulate_combination": tool_simulate_combination,
    "find_best_strategy": tool_find_best_strategy,
    "list_factories": tool_list_factories,
    "rank_factories": tool_rank_factories,
    "get_cluster_summary": tool_get_cluster_summary,
    "search_factory": tool_search_factory,
}

SYSTEM_PROMPT = (
    "You are Induscope's explainer for an industrial-emissions dashboard covering "
    "120 factories across 9 Gujarat industrial clusters. "
    "You have tools that compute REAL numbers from a real database. "
    "NEVER state a CO2e, cost, or payback figure that did not come from a tool "
    "result in this conversation — if you don't have it, call a tool. "
    "Questions are often indirect — infer intent before answering: "
    "'which factory is doing well / badly', 'who needs help', 'top performer', "
    "'biggest problem area' all mean call rank_factories, not a guess. "
    "'what's wrong with X' or 'what problem does X have' means call "
    "get_factory_summary and report the equipment with the worst severity and "
    "its root_cause field. If the user names a factory you don't have the exact "
    "id for, call search_factory first — never invent a factory_id. "
    "When asked which strategy or intervention combination is 'best' or "
    "'optimal', ALWAYS call find_best_strategy rather than picking one "
    "yourself from get_recommendations — that tool exhaustively checks every "
    "combination, which you cannot do reliably by inspection. "
    "All rupee amounts are PLAIN NUMBERS OF RUPEES (e.g. 2000000 means twenty "
    "lakh rupees, NOT two lakh) — when the user says '20 lakh' pass "
    "budget_inr=2000000, not 200000. When describing a tool's result in "
    "words, state the plain rupee number back exactly as given (e.g. "
    "'Rs 133000') — do NOT convert it to lakhs or crores yourself, you have "
    "made unit conversion errors doing this before. "
    "Keep answers concise and cite the specific numbers you computed.\n\n"
    "FORMAT every answer as Markdown — it is rendered, not shown as raw text:\n"
    "- When comparing 2+ factories/equipment/interventions with the same "
    "fields (e.g. rank_factories, get_recommendations results), use a "
    "Markdown table with a header row — never a paragraph of comma-separated "
    "numbers.\n"
    "- Bold (**...**) the single number that answers the question "
    "(e.g. **1,234 tCO2e/yr**, **Rs 45,000**, **14 months**).\n"
    "- Use a short bullet list for anything with more than two discrete "
    "points (root causes, recommendation steps, a ranked list of 3+ items).\n"
    "- Use a one-line intro sentence, then the table/list — do not repeat "
    "the same numbers again afterward in prose.\n"
    "- Never use a raw table or list for a single fact — a one-number answer "
    "stays a plain sentence with the number bolded."
)


def _deterministic_fallback(question: str, factory_id: str | None, session=None) -> str:
    """Same real computation, templated phrasing — used when Ollama is
    unreachable. Never a canned non-answer."""
    q = question.lower()

    if any(w in q for w in ["which factory", "best factory", "worst factory", "top performer",
                             "who needs", "most improved", "performing best", "performing worst",
                             "doing well", "doing badly", "biggest problem"]):
        order = "desc" if any(w in q for w in ["worst", "problem", "needs", "badly", "most improved"]) else "asc"
        result = tool_rank_factories(metric="avg_deviation_pct", order=order, limit=3, session=session)
        label = "worst-performing" if order == "desc" else "best-performing"
        rows = "\n".join(
            f"| {r['name']} | {r['sector']} | {r['cluster_id']} | {r['avg_deviation_pct']:+.1f}% | {r['hotspot_count']} |"
            for r in result["ranked"]
        )
        return (
            f"*[deterministic fallback — Ollama unavailable]*\n\n"
            f"Top {label} factories by average benchmark deviation:\n\n"
            f"| Factory | Sector | Cluster | Deviation | Hotspots |\n"
            f"|---|---|---|---|---|\n{rows}"
        )

    if factory_id is None:
        return ("[deterministic fallback — Ollama unavailable] This question needs a specific factory "
                "or a comparison — try naming a factory or asking 'which factory is best/worst'.")

    if any(w in q for w in ["best", "optimal", "strategy", "which combination", "which intervention"]):
        budget_match = re.search(r"(?:budget|under|within)\s*(?:of\s*)?(?:₹|rs\.?|inr)?\s*([\d,]+)\s*(lakh|crore)?", q)
        budget_inr = None
        if budget_match:
            amount = float(budget_match.group(1).replace(",", ""))
            unit = budget_match.group(2)
            if unit == "lakh":
                amount *= 100_000
            elif unit == "crore":
                amount *= 10_000_000
            budget_inr = amount

        result = tool_find_best_strategy(factory_id, budget_inr=budget_inr, session=session)
        if not result["selected_recommendation_ids"]:
            return ("*[deterministic fallback — Ollama unavailable]*\n\nNo recommendation combination "
                    "satisfies the given constraints; the best option is to make no change yet.")
        budget_note = f" under a budget of **Rs {budget_inr:,.0f}**" if budget_inr else ""
        return (
            f"*[deterministic fallback — Ollama unavailable]*\n\n"
            f"Best strategy{budget_note}, checked exhaustively across "
            f"**{result['n_combinations_evaluated']} combinations**:\n\n"
            f"- Apply **{len(result['selected_recommendation_ids'])} intervention(s)**: "
            f"{', '.join(result['selected_recommendation_ids'])}\n"
            f"- CO2e reduction: **{result['co2_reduction_tpy']} t/yr**\n"
            f"- CAPEX: **Rs {result['capex_inr']:,.0f}**\n"
            f"- Payback: **{result['blended_payback_months']} months**\n"
            f"- Confidence: {result['confidence']}"
        )

    summary = tool_get_factory_summary(factory_id, session=session)
    return (
        f"*[deterministic fallback — Ollama unavailable]*\n\n"
        f"**{summary.get('name', factory_id)}** ({summary.get('sector', '?')}): "
        f"**{summary.get('total_co2e_tpy', 0):.0f} tCO2e/yr** across "
        f"{len(summary.get('equipment', []))} processes. For a specific diagnosis, use "
        f"`GET /api/factories/{{id}}/diagnosis/{{anomaly_id}}`."
    )


_EMPTY_LIST_KEYS = ("ranked", "factories", "matches", "recommendations")


def _tool_result_is_empty_or_error(result: Any) -> bool:
    """Detects a tool result that has no actual data in it. Found necessary
    after testing surfaced a worse failure mode than the lakh/crore one: given
    an empty rank_factories result ({"ranked": [], "total_considered": 0}),
    llama3.1:8b did not say "I don't have that" — it fabricated an entirely
    fictitious, plausible-sounding factory name ("Sasan Power Plant") that
    does not exist anywhere in this system. verified_data alone doesn't fully
    guard against this, since a reader might only see the prose. So when the
    LAST tool call in the conversation came back empty or erroring, the
    LLM's final prose is not returned at all — replaced with an honest,
    tool-result-derived message instead."""
    if not isinstance(result, dict):
        return False
    if "error" in result:
        return True
    for key in _EMPTY_LIST_KEYS:
        if key in result and not result[key]:
            return True
    if result.get("count") == 0 or result.get("total_considered") == 0:
        return True
    return False


def _execute_tool_call(call: dict, session) -> Any:
    name = call["function"]["name"]
    args = call["function"]["arguments"]
    fn = TOOL_IMPL.get(name)
    try:
        return fn(**args, session=session) if fn else {"error": f"unknown tool '{name}'"}
    except Exception as tool_exc:  # a bad argument shouldn't crash the whole request —
        return {"error": f"{type(tool_exc).__name__}: {tool_exc}"}  # let the model see it and retry


def ask_stream(question: str, factory_id: str | None = None) -> Iterator[dict]:
    """Generator version of ask() — yields {"type": "token", "text": ...} for
    each piece of the final answer as it streams from Ollama, then exactly one
    {"type": "final", "answer", "verified_data", "source", ...} event at the
    end. See the module docstring for why streaming never risks showing a
    fabricated answer: the empty-result check runs BEFORE the streamed
    generation call, using the previous iteration's already-known tool result.

    Opens exactly one SQLAlchemy session for the whole call (shared across
    every tool invocation this turn) instead of one per tool call.
    """
    context = f"[current factory in view: factory_id={factory_id}] " if factory_id else (
        "[no specific factory currently in view — this may be a general or cross-factory question] "
    )
    messages: list[dict] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"{context}{question}"},
    ]
    last_tool_result: Any = None
    session = SessionLocal()

    try:
        for _ in range(MAX_TOOL_ITERATIONS):
            # Safety check BEFORE generating — see module docstring. No
            # tokens have been streamed yet this iteration, so discarding
            # here is free (nothing shown to the caller to retract).
            if last_tool_result is not None and _tool_result_is_empty_or_error(last_tool_result):
                detail = last_tool_result.get("error", "no matching data was found")
                answer = (f"I don't have a real answer for that — the lookup returned: {detail}. "
                          f"Try rephrasing, or ask about a specific factory/cluster by name.")
                yield {"type": "final", "answer": answer, "verified_data": last_tool_result,
                       "source": f"ollama:{OLLAMA_MODEL} (empty-result guard)"}
                return

            resp = requests.post(OLLAMA_URL, json={
                "model": OLLAMA_MODEL, "messages": messages, "tools": TOOLS, "stream": True,
            }, timeout=OLLAMA_TIMEOUT_S, stream=True)
            resp.raise_for_status()

            content_parts: list[str] = []
            tool_calls: list[dict] | None = None
            for line in resp.iter_lines():
                if not line:
                    continue
                chunk = json.loads(line)
                msg = chunk.get("message", {})
                if msg.get("tool_calls"):
                    tool_calls = msg["tool_calls"]
                piece = msg.get("content")
                if piece:
                    content_parts.append(piece)
                    if tool_calls is None:  # only ever true text, never a tool-call placeholder
                        yield {"type": "token", "text": piece}
                if chunk.get("done"):
                    break

            full_content = "".join(content_parts)
            messages.append({"role": "assistant", "content": full_content, "tool_calls": tool_calls})

            if not tool_calls:
                yield {"type": "final", "answer": full_content, "verified_data": last_tool_result,
                       "source": f"ollama:{OLLAMA_MODEL}"}
                return

            for call in tool_calls:
                result = _execute_tool_call(call, session)
                last_tool_result = result
                messages.append({"role": "tool", "content": json.dumps(result)})

        yield {"type": "final", "answer": "(ran out of tool-call iterations)",
               "verified_data": last_tool_result, "source": f"ollama:{OLLAMA_MODEL}"}

    except (requests.RequestException, KeyError, ValueError) as exc:
        fallback = _deterministic_fallback(question, factory_id, session=session)
        yield {"type": "final", "answer": fallback, "verified_data": None,
               "source": "deterministic_fallback", "error": str(exc)}
    finally:
        session.close()


def ask(question: str, factory_id: str | None = None) -> dict:
    """Non-streaming convenience wrapper over ask_stream() — collects the
    generator into the same {"answer", "verified_data", "source"} shape the
    CLI and non-streaming API routes already expect.

    `verified_data` exists because testing this against a real question
    ("which strategy is best under a 20 lakh budget") found llama3.1:8b
    reliably calls the right tool with correct real numbers coming back, but
    then MISSTATES them by ~1000x in its own prose (reported "1.33 crore"
    for a tool result of 133000 rupees — off by a factor of ~1000, an Indian
    lakh/crore unit-conversion error) and can also pass a wrong argument
    value to a tool (misread "20 lakh" as 200000 instead of 2000000 when
    building the tool call). The tool computation itself was correct both
    times — only the model's OWN restatement of numbers was wrong. Given
    this project's rule that nothing gets asserted without being real, the
    LLM's prose is treated as explanatory colour only; verified_data (built
    directly from the tool's return value, never re-typed by the model) is
    the authoritative number any caller (API, UI) should actually display.
    """
    for event in ask_stream(question, factory_id):
        if event["type"] == "final":
            return {k: v for k, v in event.items() if k != "type"}
    return {"answer": "(no response)", "verified_data": None, "source": "error"}  # unreachable in practice


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--factory-id", required=False, default=None)
    parser.add_argument("--question", required=True)
    parser.add_argument("--stream", action="store_true", help="print tokens live as they arrive")
    args = parser.parse_args()

    if args.stream:
        final = None
        for event in ask_stream(args.question, args.factory_id):
            if event["type"] == "token":
                print(event["text"], end="", flush=True)
            else:
                final = event
        print(f"\n\n[{final['source']}]")
        if final.get("verified_data"):
            print("--- verified_data ---")
            print(json.dumps(final["verified_data"], indent=2))
    else:
        result = ask(args.question, args.factory_id)
        print(f"[{result['source']}]\n{result['answer']}")
        if result.get("verified_data"):
            print("\n--- verified_data (authoritative, computed directly, not restated by the LLM) ---")
            print(json.dumps(result["verified_data"], indent=2))
