"""Leak-diagnostic endpoints motivated directly by the HackOut'26 research
doc "Industrial Emission Leak-Point Detector": compressed-air and
refrigerant leak estimators computed from invoice/nameplate data (no new
sensor hardware), a sourced water-intensity benchmark, and a cross-equipment
heat-recovery-gap insight. See app/intelligence/leak_estimators.py and
app/water_benchmark.py for the actual sourced methods.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import schemas
from .. import seed as seed_data
from ..db import models as db
from ..deps import get_db
from ..intelligence import leak_estimators as le
from .. import water_benchmark

router = APIRouter(prefix="/api/factories", tags=["leaks"])

HEAT_SOURCE_KINDS = {"kiln", "boiler", "furnace"}
HEAT_SINK_KINDS = {"dryer", "effluent"}


def _get_factory_or_404(session: Session, factory_id: str) -> db.Factory:
    factory = session.get(db.Factory, factory_id)
    if factory is None:
        raise HTTPException(404, f"factory '{factory_id}' not found")
    return factory


def _grid_kgco2e_per_kwh(session: Session) -> float:
    ef = session.get(db.EmissionFactor, "grid_electricity")
    if ef is None:
        raise HTTPException(500, "grid_electricity emission factor not seeded")
    return ef.kgco2e_per_unit


def _persist(session: Session, factory_id: str, kind: str, method: str, inputs: dict,
             leak_rate_pct: float, co2e_tpy: float, cost_inr_per_year: float, note: str) -> db.LeakAssessment:
    row = db.LeakAssessment(
        factory_id=factory_id, kind=kind, method=method, inputs=inputs,
        leak_rate_pct=leak_rate_pct, co2e_tpy=co2e_tpy, cost_inr_per_year=cost_inr_per_year, note=note,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


@router.post("/{factory_id}/leak-assessments/compressed-air/load-unload-test", response_model=schemas.LeakAssessmentOut, status_code=201)
def compressed_air_load_unload(factory_id: str, payload: schemas.CompressedAirLoadUnloadIn, session: Session = Depends(get_db)):
    """The real method: run the compressor off-shift with no demand on the
    line, time how long it spends loaded vs. unloaded per cycle. See
    app/intelligence/leak_estimators.py for why this timing ratio alone
    reveals the leak fraction, no ultrasonic survey required."""
    factory = _get_factory_or_404(session, factory_id)
    grid_ef = _grid_kgco2e_per_kwh(session)
    kwargs = {"specific_power_kw_per_100cfm": payload.specific_power_kw_per_100cfm} if payload.specific_power_kw_per_100cfm else {}
    result = le.compressed_air_leak_from_load_unload_test(
        rated_capacity_cfm=payload.rated_capacity_cfm, load_time_min=payload.load_time_min,
        unload_time_min=payload.unload_time_min, operating_hours_per_year=payload.operating_hours_per_year,
        electricity_rate_inr_per_kwh=payload.electricity_rate_inr_per_kwh, grid_kgco2e_per_kwh=grid_ef, **kwargs,
    )
    return _persist(
        session, factory.id, "compressed_air", result.method, payload.model_dump(),
        result.leak_fraction * 100, result.co2e_tpy, result.cost_inr_per_year, result.note,
    )


@router.post("/{factory_id}/leak-assessments/compressed-air/unaudited-estimate", response_model=schemas.LeakAssessmentOut, status_code=201)
def compressed_air_unaudited(factory_id: str, payload: schemas.CompressedAirUnauditedIn, session: Session = Depends(get_db)):
    """Fallback for a plant that hasn't run the timing test yet — uses the
    literature-cited 20-30% unaudited-system range, clearly flagged as a
    range estimate rather than a site-measured number."""
    factory = _get_factory_or_404(session, factory_id)
    grid_ef = _grid_kgco2e_per_kwh(session)
    kwargs = {"specific_power_kw_per_100cfm": payload.specific_power_kw_per_100cfm} if payload.specific_power_kw_per_100cfm else {}
    result = le.compressed_air_leak_unaudited_default(
        rated_capacity_cfm=payload.rated_capacity_cfm, operating_hours_per_year=payload.operating_hours_per_year,
        electricity_rate_inr_per_kwh=payload.electricity_rate_inr_per_kwh, grid_kgco2e_per_kwh=grid_ef, **kwargs,
    )
    return _persist(
        session, factory.id, "compressed_air", result.method, payload.model_dump(),
        result.leak_fraction * 100, result.co2e_tpy, result.cost_inr_per_year, result.note,
    )


@router.post("/{factory_id}/leak-assessments/refrigerant", response_model=schemas.LeakAssessmentOut, status_code=201)
def refrigerant_leak(factory_id: str, payload: schemas.RefrigerantLeakIn, session: Session = Depends(get_db)):
    """A refrigerant top-up is compensation for a continuous leak, not
    routine maintenance — see app/intelligence/leak_estimators.py."""
    factory = _get_factory_or_404(session, factory_id)
    try:
        result = le.refrigerant_leak_from_topup(
            refrigerant_key=payload.refrigerant_key, nameplate_charge_kg=payload.nameplate_charge_kg,
            annual_topup_kg=payload.annual_topup_kg, refrigerant_cost_inr_per_kg=payload.refrigerant_cost_inr_per_kg,
        )
    except ValueError as e:
        raise HTTPException(422, str(e))
    return _persist(
        session, factory.id, "refrigerant", "topup_vs_nameplate", payload.model_dump(),
        result.leak_rate_pct, result.co2e_tpy, result.replacement_cost_inr_per_year, result.note,
    )


@router.get("/{factory_id}/leak-assessments", response_model=list[schemas.LeakAssessmentOut])
def list_leak_assessments(factory_id: str, session: Session = Depends(get_db)):
    _get_factory_or_404(session, factory_id)
    return session.scalars(
        select(db.LeakAssessment).where(db.LeakAssessment.factory_id == factory_id).order_by(db.LeakAssessment.created_at.desc())
    ).all()


@router.get("/{factory_id}/water-benchmark", response_model=schemas.WaterBenchmarkOut)
def water_benchmark_check(factory_id: str, litres_per_kg: float | None = None, session: Session = Depends(get_db)):
    """Sourced water-intensity benchmark (app/water_benchmark.py) — a second
    benchmark axis alongside the existing energy-intensity one, honestly
    reported unavailable outside the one sector it's actually sourced for."""
    factory = _get_factory_or_404(session, factory_id)
    result = water_benchmark.evaluate(factory.sector, litres_per_kg)
    return schemas.WaterBenchmarkOut(factory_id=factory.id, **result)


@router.get("/{factory_id}/cross-process-insights", response_model=list[schemas.CrossProcessInsightOut])
def cross_process_insights(factory_id: str, session: Session = Depends(get_db)):
    """Root-cause rules in app/intelligence/rootcause.py are all per-equipment
    — this looks ACROSS equipment for the specific structural pattern the
    source research doc's Scenario 1 describes: a heat-rejecting process
    (kiln/boiler/furnace) and a heat-consuming process (dryer/ETP) coexisting
    in the same factory with no waste-heat-recovery link between them, each
    tracked in a different logbook so nobody connects the two facts. This is
    a structural pattern flag, not a validated engineering match — it says
    "these two exist together, worth a site review," not "X kWh is
    recoverable," since no heat-exchanger sizing data exists to compute that."""
    factory = _get_factory_or_404(session, factory_id)
    equipment_ids = [e.id for e in factory.equipment]
    existing_heat_recovery_ids = set(session.scalars(
        select(db.Recommendation.equipment_id).where(
            db.Recommendation.equipment_id.in_(equipment_ids), db.Recommendation.category == "heat-recovery",
        )
    ).all()) if equipment_ids else set()

    sources = [e for e in factory.equipment if e.kind in HEAT_SOURCE_KINDS]
    sinks = [e for e in factory.equipment if e.kind in HEAT_SINK_KINDS]

    insights: list[schemas.CrossProcessInsightOut] = []
    for src in sources:
        for sink in sinks:
            already_flagged = src.id in existing_heat_recovery_ids
            insights.append(schemas.CrossProcessInsightOut(
                finding="waste_heat_recovery_gap",
                equipment_a=src.label, equipment_b=sink.label,
                note=(
                    f"{src.label} rejects heat as a normal part of its process; {sink.label} "
                    f"separately consumes energy to heat/process material. "
                    + ("A heat-recovery intervention is already sized for "
                       f"{src.label} (see its recommendations) — check whether it's routed toward "
                       f"{sink.label} specifically." if already_flagged else
                       f"No heat-recovery intervention is currently sized for {src.label} — worth a "
                       f"site review of whether its rejected heat could pre-heat {sink.label}'s intake, "
                       "the same pattern a Tirupur dyeing-unit case study found (ETP spending ~2x the "
                       "process's own energy recycling water with no capture of boiler/dye-bath waste heat).")
                ),
            ))
    return insights
