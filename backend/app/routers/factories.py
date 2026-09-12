from __future__ import annotations

import sys
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import carbon_credit, schemas
from ..db import models as db
from ..deps import get_db

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ml.registry import registry  # noqa: E402

router = APIRouter(prefix="/api/factories", tags=["factories"])

_ML_FUEL_KEYS = ("grid_electricity", "natural_gas", "coal", "pet_coke", "biomass")


def _fuel_shares_for_ml(session: Session, equipment_id: str) -> dict[str, float]:
    """Same feature construction ml/data.py's load_equipment_frame() uses at
    training time — must match exactly, or predict_benchmark_ratio() would be
    scoring on a different feature distribution than it was trained on."""
    rows = session.execute(
        select(db.EmissionRecord.fuel_key, func.sum(db.EmissionRecord.co2e_t))
        .where(db.EmissionRecord.equipment_id == equipment_id)
        .group_by(db.EmissionRecord.fuel_key)
    ).all()
    co2e_by_fuel = dict(rows)
    total = sum(co2e_by_fuel.values()) or 1.0
    return {k: co2e_by_fuel.get(k, 0.0) / total for k in _ML_FUEL_KEYS}


def _get_factory_or_404(session: Session, factory_id: str) -> db.Factory:
    factory = session.get(db.Factory, factory_id)
    if factory is None:
        raise HTTPException(404, f"factory '{factory_id}' not found")
    return factory


def _anomaly_check_status(session: Session, factory: db.Factory) -> str:
    """Derived live, not stored: seeded factories were checked for every
    equipment at seed time (see app/db/seed_loader.py). A self-reported
    factory only qualifies per-equipment once its real submitted series
    reaches app/intelligence/anomaly.py's own len(series) < 4 minimum — the
    same threshold routers/onboarding.py's recompute job checks, kept
    consistent by reading from the same EmissionRecord rows rather than a
    flag that could drift out of sync with what recompute actually did."""
    if factory.data_source != "self_reported":
        return "available"
    if not factory.equipment:
        return "not_available"
    equipment_ids = [e.id for e in factory.equipment]
    counts = dict(session.execute(
        select(db.EmissionRecord.equipment_id, func.count(func.distinct(db.EmissionRecord.month)))
        .where(db.EmissionRecord.equipment_id.in_(equipment_ids))
        .group_by(db.EmissionRecord.equipment_id)
    ).all())
    qualifies = [counts.get(eid, 0) >= 4 for eid in equipment_ids]
    if all(qualifies):
        return "available"
    if any(qualifies):
        return "partial"
    return "not_available"


# Keyword heuristic, not a measured exposure reading — no VOC/solvent
# instrumentation exists in this system. Flags process labels that
# plausibly involve solvent/VOC handling (dyeing, glazing, distillation,
# reactor chemistry) per the source research doc's Part B.2 (worker health
# is a real, documented occupational-exposure risk for these process types,
# separate from and additional to their emissions/cost impact).
_VOC_RISK_KEYWORDS = ("dye", "glaz", "distill", "reactor", "solvent", "paint", "degreas", "print")


def _worker_exposure_flags(factory: db.Factory) -> list[str]:
    flags = []
    for e in factory.equipment:
        label_lower = e.label.lower()
        if any(kw in label_lower for kw in _VOC_RISK_KEYWORDS):
            flags.append(
                f"{e.label}: plausible solvent/VOC exposure risk (keyword heuristic on process label, "
                f"not a measured reading — see occupational studies cited in the leak-point research doc)."
            )
    return flags


def _to_full_out(session: Session, factory: db.Factory) -> schemas.FactoryFullOut:
    total = sum(e.co2e_tpy or 0.0 for e in factory.equipment)
    equipment = [
        schemas.EquipmentFullOut(
            id=e.id, process_id=e.process_id, label=e.label, kind=e.kind,
            share_of_energy=e.share_of_energy, benchmark_kgco2e_per_t=e.benchmark_kgco2e_per_t,
            benchmark_source=e.benchmark_source, benchmark_confidence=e.benchmark_confidence,
            co2e_tpy=e.co2e_tpy, share_of_total=e.share_of_total, actual_intensity=e.actual_intensity,
            severity=e.severity, root_cause_text=e.root_cause_text,
            recommendations=e.recommendations,
        )
        for e in factory.equipment
    ]

    equipment_ids = [e.id for e in factory.equipment]
    total_gj = 0.0
    if equipment_ids:
        rows = session.execute(
            select(db.EnergyRecord.quantity, db.EmissionFactor.gj_per_unit)
            .join(db.EmissionFactor, db.EnergyRecord.fuel_key == db.EmissionFactor.key)
            .where(db.EnergyRecord.equipment_id.in_(equipment_ids))
        ).all()
        total_gj = sum(qty * gj for qty, gj in rows)
    total_energy_mwh = total_gj / 3.6  # 1 MWh = 3.6 GJ

    total_waste = session.scalar(
        select(func.coalesce(func.sum(db.WasteRecord.hazardous_waste_t + db.WasteRecord.general_process_waste_t), 0.0))
        .where(db.WasteRecord.factory_id == factory.id)
    ) or 0.0

    # No recovered-material tracking exists in this dataset yet (Phase 1/2 built
    # emissions, not a symbiosis/recovery ledger) — 0.0 is the honest value for
    # every factory until Phase 3's symbiosis matcher and an "implemented
    # interventions" ledger exist, not a placeholder guess like the old mock data.
    circularity_ratio = 0.0

    # Best single recommendation per equipment (not every recommendation
    # summed — avoids double-counting overlapping fixes on one process,
    # matching the same convention the pre-existing frontend rollup used).
    avoidable_co2e = sum(
        max((r.co2_reduction_tpy for r in e.recommendations), default=0.0)
        for e in factory.equipment
    )
    credit_value = carbon_credit.credit_value_inr(avoidable_co2e)

    return schemas.FactoryFullOut(
        id=factory.id, name=factory.name, cluster_id=factory.cluster_id, sector=factory.sector,
        district=factory.district, lat=factory.lat, lon=factory.lon, data_source=factory.data_source,
        consent_to_share=factory.consent_to_share, output_tonnes_per_year=factory.output_tonnes_per_year,
        total_co2e_tpy=round(total, 2), total_energy_mwh_per_year=round(total_energy_mwh, 1),
        total_waste_tpy=round(total_waste, 2), circularity_ratio=circularity_ratio,
        avoidable_co2e_tpy=round(avoidable_co2e, 1), carbon_credit_value_inr_per_year=credit_value,
        carbon_credit_is_placeholder=True, carbon_credit_note=carbon_credit.SOURCE_NOTE,
        equipment=equipment, anomaly_check_status=_anomaly_check_status(session, factory),
        worker_exposure_flags=_worker_exposure_flags(factory),
    )


_SEVERITY_RANK = {"ok": 0, "warn": 1, "crit": 2}


def _to_lite_out(session: Session, factory: db.Factory) -> schemas.FactorySummaryLiteOut:
    total = sum(e.co2e_tpy or 0.0 for e in factory.equipment)
    worst = max((e.severity or "ok" for e in factory.equipment), key=lambda s: _SEVERITY_RANK.get(s, 0), default="ok")
    return schemas.FactorySummaryLiteOut(
        id=factory.id, name=factory.name, cluster_id=factory.cluster_id, sector=factory.sector,
        lat=factory.lat, lon=factory.lon, data_source=factory.data_source,
        total_co2e_tpy=round(total, 2), worst_severity=worst,
        anomaly_check_status=_anomaly_check_status(session, factory),
        organization_id=factory.organization_id,
    )


@router.get("/summary", response_model=list[schemas.FactorySummaryLiteOut])
def list_factories_summary(session: Session = Depends(get_db)):
    """Lightweight variant of the bulk listing below — id/name/co2e/severity
    only, no nested equipment or recommendations. Registered before
    /{factory_id} so "summary" isn't swallowed as a factory_id path param.
    For map/portfolio views that only need to plot/rank factories; fetch
    GET /{factory_id} (FactoryFullOut) on demand for the one actually
    selected. The full bulk endpoint below still returns everything for
    every factory on every call — fine at ~120 factories, won't scale to
    the 5,000-factory pitch in README.md's roadmap, which is what this
    endpoint exists to head off."""
    factories = session.scalars(select(db.Factory)).all()
    return [_to_lite_out(session, f) for f in factories]


@router.get("", response_model=list[schemas.FactoryFullOut])
def list_factories(session: Session = Depends(get_db)):
    """Bulk listing — every factory with its full equipment + recommendations
    nested, in one request. Small dataset (~120 factories) by design; see
    docstring on schemas.FactoryFullOut for why this shape exists. Prefer
    GET /api/factories/summary for map/portfolio views that don't need the
    nested detail — see that endpoint's docstring."""
    factories = session.scalars(select(db.Factory)).all()
    return [_to_full_out(session, f) for f in factories]


@router.get("/{factory_id}", response_model=schemas.FactoryFullOut)
def get_factory(factory_id: str, session: Session = Depends(get_db)):
    factory = _get_factory_or_404(session, factory_id)
    return _to_full_out(session, factory)


@router.get("/{factory_id}/equipment", response_model=list[schemas.EquipmentOut])
def get_equipment(factory_id: str, session: Session = Depends(get_db)):
    factory = _get_factory_or_404(session, factory_id)
    return factory.equipment


@router.get("/{factory_id}/emissions", response_model=list[schemas.EmissionMonthOut])
def get_emissions(factory_id: str, session: Session = Depends(get_db)):
    """Monthly CO2e with the formula, factor, and source shown per record —
    every row here was computed by app/engine/emissions.co2e_for, not looked up."""
    factory = _get_factory_or_404(session, factory_id)
    equipment_ids = [e.id for e in factory.equipment]
    if not equipment_ids:
        return []
    records = session.scalars(
        select(db.EmissionRecord).where(db.EmissionRecord.equipment_id.in_(equipment_ids)).order_by(db.EmissionRecord.month)
    ).all()
    return [
        schemas.EmissionMonthOut(
            month=r.month, fuel_key=r.fuel_key, co2e_t=r.co2e_t,
            emission_factor_kgco2e_per_unit=r.emission_factor_kgco2e_per_unit,
            emission_factor_source=r.emission_factor_source,
        )
        for r in records
    ]


@router.get("/{factory_id}/benchmark", response_model=list[schemas.BenchmarkOut])
def get_benchmark(factory_id: str, session: Session = Depends(get_db)):
    """Sub-sector (Gujarat cluster) benchmark comparison per process.

    Global and India-level benchmarks are honestly reported as unavailable —
    no sourced global/national per-process intensity dataset exists in this
    project (see data-pipeline/sources.md). Returning fabricated numbers for
    those levels to fill out a nicer-looking table would violate the one rule
    this whole product is built around: never assert a number without a real
    source behind it.

    Also includes an "ml_predicted" level (ml/benchmark_model.py via
    ml/registry.py) — a LightGBM prediction of this specific equipment's
    expected intensity from its real profile (output scale, fuel mix),
    instead of one flat number for the whole sub-sector. Measured accuracy is
    reported inline via `note`, split by whether this factory's cluster was
    in the model's training data (+36.9% MAE vs. flat benchmark) or not
    (+6.3%) — see ml/LIMITATIONS.md #9 for the full validation. If the model
    artifact isn't available (e.g. `python -m ml.benchmark_model` was never
    run), this level is honestly reported unavailable, not skipped silently.
    """
    factory = _get_factory_or_404(session, factory_id)
    out = []
    for e in factory.equipment:
        deviation = None
        if e.actual_intensity is not None and e.benchmark_kgco2e_per_t:
            deviation = round((e.actual_intensity - e.benchmark_kgco2e_per_t) / e.benchmark_kgco2e_per_t * 100, 1)

        ml_level = schemas.BenchmarkLevelOut(
            level="ml_predicted", available=False,
            note="ML benchmark model not available — run: python -m ml.benchmark_model",
        )
        if e.benchmark_kgco2e_per_t and factory.output_tonnes_per_year:
            try:
                fuel_shares = _fuel_shares_for_ml(session, e.id)
                prediction = registry.predict_benchmark_ratio(
                    sector=factory.sector, process_kind=e.kind, share_of_energy=e.share_of_energy,
                    output_tonnes_per_year=factory.output_tonnes_per_year, fuel_shares=fuel_shares,
                )
                ml_level = schemas.BenchmarkLevelOut(
                    level="ml_predicted", available=True,
                    value_kgco2e_per_t=round(prediction["predicted_ratio"] * e.benchmark_kgco2e_per_t, 1),
                    source="ml/benchmark_model.py (LightGBM, ml/registry.py)", confidence="medium",
                    note=prediction["note"],
                )
            except Exception:
                pass  # model artifact missing/unreadable — ml_level keeps its unavailable default above

        out.append(schemas.BenchmarkOut(
            equipment_id=e.id, process_label=e.label,
            actual_intensity_kgco2e_per_t=e.actual_intensity, deviation_pct=deviation, severity=e.severity,
            levels=[
                schemas.BenchmarkLevelOut(level="global", available=False,
                                          note="No sourced global per-process intensity dataset — not fabricated"),
                schemas.BenchmarkLevelOut(level="india", available=False,
                                          note="No sourced India-wide per-process intensity dataset — not fabricated"),
                schemas.BenchmarkLevelOut(level="gujarat_cluster", available=True,
                                          value_kgco2e_per_t=e.benchmark_kgco2e_per_t,
                                          source=e.benchmark_source, confidence=e.benchmark_confidence),
                ml_level,
                schemas.BenchmarkLevelOut(level="factory", available=True,
                                          value_kgco2e_per_t=e.actual_intensity,
                                          source="computed: app/engine/intensity.intensity_kg_per_t", confidence="high"),
            ],
        ))
    return out


@router.get("/{factory_id}/anomalies", response_model=list[schemas.AnomalyOut])
def get_anomalies(factory_id: str, session: Session = Depends(get_db)):
    factory = _get_factory_or_404(session, factory_id)
    equipment_ids = [e.id for e in factory.equipment]
    if not equipment_ids:
        return []
    return session.scalars(
        select(db.Anomaly).where(db.Anomaly.equipment_id.in_(equipment_ids)).order_by(db.Anomaly.month)
    ).all()


@router.get("/{factory_id}/diagnosis/{anomaly_id}", response_model=schemas.DiagnosisOut)
def get_diagnosis(factory_id: str, anomaly_id: int, session: Session = Depends(get_db)):
    factory = _get_factory_or_404(session, factory_id)
    anomaly = session.get(db.Anomaly, anomaly_id)
    if anomaly is None or anomaly.equipment_id not in {e.id for e in factory.equipment}:
        raise HTTPException(404, f"anomaly {anomaly_id} not found on factory '{factory_id}'")
    equipment = session.get(db.Equipment, anomaly.equipment_id)
    return schemas.DiagnosisOut(
        anomaly=anomaly, equipment_label=equipment.label,
        root_cause_text=equipment.root_cause_text or "No rule fired.",
        root_cause_rules=equipment.root_cause_rules or [],
        explanation_source="deterministic_fallback",
    )


@router.get("/{factory_id}/recommendations", response_model=list[schemas.RecommendationOut])
def get_recommendations(factory_id: str, session: Session = Depends(get_db)):
    factory = _get_factory_or_404(session, factory_id)
    equipment_ids = [e.id for e in factory.equipment]
    if not equipment_ids:
        return []
    return session.scalars(
        select(db.Recommendation)
        .where(db.Recommendation.equipment_id.in_(equipment_ids))
        .order_by(db.Recommendation.rank)
    ).all()


@router.get("/{factory_id}/symbiosis-matches", response_model=list[schemas.SymbiosisMatchOut])
def get_symbiosis_matches(factory_id: str, session: Session = Depends(get_db)):
    """Matches this factory is on either side of, computed by
    ml/symbiosis_model.py (Phase 3c). co2_avoided_tpy is always
    is_placeholder=True — no sourced embodied-carbon dataset exists for
    these waste categories yet, see data-pipeline/LIMITATIONS.md #1."""
    _get_factory_or_404(session, factory_id)
    rows = session.scalars(
        select(db.SymbiosisMatch)
        .where(
            (db.SymbiosisMatch.provider_factory_id == factory_id)
            | (db.SymbiosisMatch.recipient_factory_id == factory_id)
        )
        .order_by(db.SymbiosisMatch.overall_score.desc())
    ).all()
    names = {f.id: f.name for f in session.query(db.Factory).all()}
    return [
        schemas.SymbiosisMatchOut(
            id=r.id, provider_factory_id=r.provider_factory_id,
            provider_factory_name=names.get(r.provider_factory_id),
            recipient_factory_id=r.recipient_factory_id,
            recipient_factory_name=names.get(r.recipient_factory_id),
            waste_tag=r.waste_tag, quantity_tpy=r.quantity_tpy, distance_km=r.distance_km,
            semantic_score=r.semantic_score, quantity_fit_score=r.quantity_fit_score,
            proximity_score=r.proximity_score, overall_score=r.overall_score,
            co2_avoided_tpy=r.co2_avoided_tpy, provider_saving_inr=r.provider_saving_inr,
            recipient_saving_inr=r.recipient_saving_inr, is_placeholder=r.is_placeholder,
        )
        for r in rows
    ]
