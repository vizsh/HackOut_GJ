from __future__ import annotations

import csv
import io
import uuid

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from .. import models as m
from .. import schemas
from .. import seed as seed_data
from ..db import models as db
from ..deps import get_db
from ..engine import emissions, intensity, units
from ..intelligence import anomaly as anomaly_engine
from ..intelligence import recommender, rootcause

router = APIRouter(prefix="/api/factories", tags=["onboarding"])


@router.post("", response_model=schemas.OnboardFactoryOut, status_code=201)
def onboard_factory(payload: schemas.OnboardFactoryIn, session: Session = Depends(get_db)):
    """Real onboarding: a real factory's own submitted activity data runs
    through the exact same engine (units.normalise -> emissions.co2e_for) and
    recommender used for the 120 seeded factories. There is no separate
    "demo path" vs "real path" — same functions, same code.

    Anomaly detection is honestly reported as not_available: it needs a
    multi-month time series to establish a baseline, which a freshly-onboarded
    factory does not have yet (and even with one, app/intelligence/anomaly.py
    currently only ever runs against the precomputed seed table, not a live
    feature pipeline — see data-pipeline roadmap / Induscope vision doc §04).
    Returning a fabricated "no anomalies detected" would look like a clean
    bill of health that was never actually checked — the opposite of what
    this project is for.
    """
    cluster = session.get(db.Cluster, payload.cluster_id)
    if cluster is None:
        raise HTTPException(400, f"unknown cluster_id '{payload.cluster_id}'")

    factory_id = f"onboarded-{uuid.uuid4().hex[:10]}"
    factory = db.Factory(
        id=factory_id, name=payload.name, cluster_id=payload.cluster_id, sector=payload.sector,
        district=cluster.district, lat=cluster.lat, lon=cluster.lon, data_source="self_reported",
        consent_to_share=False, output_tonnes_per_year=payload.output_tonnes_total,
    )
    session.add(factory)

    all_recommendations: list[schemas.RecommendationOut] = []
    total_co2e = 0.0
    ef_table = seed_data.emission_factors()

    # Real onboarded processes use process_ids drawn from the same sector
    # templates the seeded factories use (the intake form only offers those
    # ids) — so the real sourced benchmark is available and should be looked
    # up, not zeroed out. Only a genuinely unmatched process_id (e.g. a
    # future custom-process feature) falls back to "not applicable".
    sector_bench_rows = {t["id"]: t for t in seed_data.sector_templates().get(payload.sector, [])}

    for proc in payload.processes:
        equip_id = f"{factory_id}:{proc.process_id}"
        bench_row = sector_bench_rows.get(proc.process_id)
        equip = db.Equipment(
            id=equip_id, factory_id=factory_id, process_id=proc.process_id, label=proc.label,
            kind=proc.kind, share_of_energy=proc.share_of_energy,
            benchmark_kgco2e_per_t=bench_row["benchmark"] if bench_row else 0.0,
            benchmark_source=bench_row["source"] if bench_row else
                "not applicable — process_id has no matching sub-sector template",
            benchmark_confidence=bench_row["confidence"] if bench_row else "n/a",
        )
        session.add(equip)

        equip_co2e = 0.0
        for act in proc.activities:
            if act.fuel_key not in ef_table:
                raise HTTPException(422, f"unknown fuel_key '{act.fuel_key}'. Accepted: {list(ef_table)}")
            activity = m.Activity(fuel=act.fuel_key, unit=act.unit, quantity=act.quantity)
            normalised, issue = units.normalise(activity)
            if issue is not None:
                raise HTTPException(422, issue.message)
            co2e_t = emissions.co2e_for(normalised)
            session.add(db.EnergyRecord(
                equipment_id=equip_id, month=act.month, fuel_key=act.fuel_key,
                quantity=act.quantity, canonical_unit=normalised.canonical_unit,
            ))
            session.add(db.EmissionRecord(
                equipment_id=equip_id, month=act.month, fuel_key=act.fuel_key, co2e_t=co2e_t,
                emission_factor_kgco2e_per_unit=normalised.kgco2e_per_unit, emission_factor_source=normalised.source,
            ))
            equip_co2e += co2e_t

        equip.co2e_tpy = round(equip_co2e, 2)
        equipment_output_tpy = payload.output_tonnes_total * proc.share_of_energy
        equip.actual_intensity = intensity.intensity_kg_per_t(equip_co2e, equipment_output_tpy)
        total_co2e += equip_co2e

        if equip.benchmark_kgco2e_per_t:
            ratio = equip.actual_intensity / equip.benchmark_kgco2e_per_t
            equip.severity = intensity.severity_from_ratio(ratio)
        else:
            equip.severity = "ok"  # no real benchmark to compare against — see benchmark_source above

        node = m.ProcessNode(
            id=equip_id, label=equip.label, kind=equip.kind, co2eTpy=equip_co2e, shareOfTotal=0.0,
            actualIntensity=equip.actual_intensity, benchmarkIntensity=equip.benchmark_kgco2e_per_t or equip.actual_intensity or 1.0,
            severity=equip.severity,
        )
        hits = rootcause.diagnose(node, sector_hint=payload.sector, output_tpm=equipment_output_tpy / 12, fuel_mix=None)
        equip.root_cause_text = rootcause.narrative(
            hits, fallback="No rule fired — process runs close to its own historical baseline."
            if equip.benchmark_kgco2e_per_t else "No sub-sector benchmark available for this process yet."
        )
        equip.root_cause_rules = [h.model_dump() for h in hits]
        for iv in recommender.interventions_for(node, payload.sector):
            # see app/db/seed_loader.py for why this can't be a plain split(":", 1)
            key = iv.id[len(equip_id) + 1:]
            rec = db.Recommendation(
                id=f"{equip_id}:{key}", equipment_id=equip_id, intervention_key=key, title=iv.title,
                category=iv.category, capex_inr=iv.capexInr, annual_saving_inr=iv.annualSavingInr,
                co2_reduction_tpy=iv.co2ReductionTpy, payback_months=iv.paybackMonths,
                confidence=iv.confidence, description=iv.description,
                circularity_gain_pct=iv.circularityGainPct, rank=len(all_recommendations),
                applied=False,
            )
            session.add(rec)
            # applied=False is passed explicitly above (not left to the column
            # default) because model_validate below reads this in-memory object
            # BEFORE session.commit() flushes it — a plain column default is
            # only guaranteed to populate the Python attribute at flush time, so
            # without this, rec.applied is still None here and RecommendationOut
            # (applied: bool) fails pydantic validation with a 500.
            all_recommendations.append(schemas.RecommendationOut.model_validate(rec))

    session.commit()

    return schemas.OnboardFactoryOut(
        id=factory_id, name=payload.name, total_co2e_t=round(total_co2e, 2),
        anomaly_check_status="not_available", recommendations=all_recommendations,
    )


def _monthly_series_for_equipment(session: Session, equipment_id: str) -> list[tuple[str, float]]:
    # SessionLocal is autoflush=False (see app/db/base.py), so a pending
    # session.add() from earlier in the same request (e.g. append_activity's
    # just-submitted month) would not be visible to this query without an
    # explicit flush first.
    session.flush()
    rows = session.execute(
        select(db.EmissionRecord.month, func.sum(db.EmissionRecord.co2e_t))
        .where(db.EmissionRecord.equipment_id == equipment_id)
        .group_by(db.EmissionRecord.month)
        .order_by(db.EmissionRecord.month)
    ).all()
    return [(month, float(total)) for month, total in rows]


def _recompute_equipment_anomalies(
    session: Session, equip: db.Equipment, factory: db.Factory,
) -> schemas.RecomputeEquipmentOut:
    """The live feature-window check for one piece of equipment: re-reads its
    real submitted monthly series and, once it has reached anomaly.py's own
    len(series) < 4 minimum, runs the exact same z-score rule the 120 seeded
    factories use — not a reimplementation. Idempotent: safe to call again
    after another month of data lands (clears this equipment's prior computed
    anomalies before writing fresh ones, so re-running never accumulates
    duplicate rows for the same month).
    """
    series = _monthly_series_for_equipment(session, equip.id)

    # Equipment totals/intensity/severity refresh regardless of whether enough
    # months exist yet for anomaly detection to activate — a factory's detail
    # view should reflect newly-appended activity immediately either way.
    total_co2e = sum(v for _, v in series)
    equip.co2e_tpy = round(total_co2e, 2)
    equipment_output_tpy = (factory.output_tonnes_per_year or 0.0) * equip.share_of_energy
    if equipment_output_tpy:
        equip.actual_intensity = intensity.intensity_kg_per_t(total_co2e, equipment_output_tpy)
        if equip.benchmark_kgco2e_per_t:
            equip.severity = intensity.severity_from_ratio(equip.actual_intensity / equip.benchmark_kgco2e_per_t)

    if len(series) < 4:
        return schemas.RecomputeEquipmentOut(
            equipment_id=equip.id, anomaly_check_status="not_available",
            n_months=len(series), anomalies_found=0,
        )

    session.execute(delete(db.Anomaly).where(db.Anomaly.equipment_id == equip.id))
    points = anomaly_engine.detect_anomalies(series)
    anomalies_found = 0
    for p in points:
        if p.anomaly:
            session.add(db.Anomaly(equipment_id=equip.id, month=p.month, co2e_t=p.co2eT, z_score=p.z, status="open"))
            anomalies_found += 1

    node = m.ProcessNode(
        id=equip.id, label=equip.label, kind=equip.kind, co2eTpy=equip.co2e_tpy,
        shareOfTotal=equip.share_of_total or 0.0, actualIntensity=equip.actual_intensity or 0.0,
        benchmarkIntensity=equip.benchmark_kgco2e_per_t or equip.actual_intensity or 1.0,
        severity=equip.severity or "ok", monthly=points,
    )
    hits = rootcause.diagnose(
        node, sector_hint=factory.sector,
        output_tpm=(equipment_output_tpy / 12) if equipment_output_tpy else 0.0, fuel_mix=None,
    )
    equip.root_cause_text = rootcause.narrative(
        hits, fallback="No rule fired — process runs close to its own historical baseline."
    )
    equip.root_cause_rules = [h.model_dump() for h in hits]

    return schemas.RecomputeEquipmentOut(
        equipment_id=equip.id, anomaly_check_status="available",
        n_months=len(series), anomalies_found=anomalies_found,
    )


def _factory_level_status(results: list[schemas.RecomputeEquipmentOut]) -> str:
    if not results:
        return "not_available"
    statuses = {r.anomaly_check_status for r in results}
    if statuses == {"available"}:
        return "available"
    if statuses == {"not_available"}:
        return "not_available"
    return "partial"


@router.post("/{factory_id}/recompute", response_model=schemas.RecomputeOut)
def recompute_factory(factory_id: str, session: Session = Depends(get_db)):
    """The live feature-window job: re-checks every piece of equipment on a
    self-reported factory against anomaly.py's real >= 4-month minimum, and
    activates real anomaly detection for any equipment that has now
    accumulated enough real submitted months — closing the
    anomaly_check_status: "not_available" gap over time instead of it being
    permanent. Safe to call repeatedly (e.g. after every /activity submission,
    which does so automatically); a no-op for equipment still short on data.
    """
    factory = session.get(db.Factory, factory_id)
    if factory is None:
        raise HTTPException(404, f"factory '{factory_id}' not found")
    if factory.data_source != "self_reported":
        raise HTTPException(
            400, "recompute only applies to self-reported (onboarded) factories — "
                 "seeded factories already have anomaly detection computed at seed time",
        )

    results = [_recompute_equipment_anomalies(session, e, factory) for e in factory.equipment]
    session.commit()
    return schemas.RecomputeOut(factory_id=factory_id, anomaly_check_status=_factory_level_status(results), equipment=results)


def _apply_activity_entries(session: Session, factory: db.Factory, entries: list[schemas.ActivityAppendIn]) -> None:
    """Shared core of POST .../activity (JSON) and POST .../activity/csv —
    same validation, same engine calls, same EnergyRecord/EmissionRecord
    writes, regardless of which format the data arrived in. Neither endpoint
    duplicates this logic."""
    ef_table = seed_data.emission_factors()
    equip_by_process = {e.process_id: e for e in factory.equipment}

    for entry in entries:
        equip = equip_by_process.get(entry.process_id)
        if equip is None:
            raise HTTPException(404, f"process_id '{entry.process_id}' not found on factory '{factory.id}'")
        for act in entry.activities:
            if act.fuel_key not in ef_table:
                raise HTTPException(422, f"unknown fuel_key '{act.fuel_key}'. Accepted: {list(ef_table)}")
            activity = m.Activity(fuel=act.fuel_key, unit=act.unit, quantity=act.quantity)
            normalised, issue = units.normalise(activity)
            if issue is not None:
                raise HTTPException(422, issue.message)
            co2e_t = emissions.co2e_for(normalised)
            session.add(db.EnergyRecord(
                equipment_id=equip.id, month=act.month, fuel_key=act.fuel_key,
                quantity=act.quantity, canonical_unit=normalised.canonical_unit,
            ))
            session.add(db.EmissionRecord(
                equipment_id=equip.id, month=act.month, fuel_key=act.fuel_key, co2e_t=co2e_t,
                emission_factor_kgco2e_per_unit=normalised.kgco2e_per_unit, emission_factor_source=normalised.source,
            ))


def _get_self_reported_factory_or_error(session: Session, factory_id: str) -> db.Factory:
    factory = session.get(db.Factory, factory_id)
    if factory is None:
        raise HTTPException(404, f"factory '{factory_id}' not found")
    if factory.data_source != "self_reported":
        raise HTTPException(400, "activity can only be appended to self-reported (onboarded) factories")
    return factory


@router.post("/{factory_id}/activity", response_model=schemas.RecomputeOut)
def append_activity(factory_id: str, payload: list[schemas.ActivityAppendIn], session: Session = Depends(get_db)):
    """Onboarding (POST /api/factories) is one-shot — this is how an
    already-onboarded factory submits another real month of activity data for
    its existing processes. Automatically re-runs the recompute job below
    afterward, so anomaly detection activates on its own the moment enough
    real months exist, rather than requiring a separate manual trigger.

    Known limitation, disclosed rather than hidden: actual_intensity here is
    still computed against `output_tonnes_total` from the original one-shot
    onboarding call (treated as an annual figure), so this model only stays
    accurate within a single reporting year of appended months — a real
    per-period-output submission flow is future work, not built here.
    """
    factory = _get_self_reported_factory_or_error(session, factory_id)
    _apply_activity_entries(session, factory, payload)
    results = [_recompute_equipment_anomalies(session, e, factory) for e in factory.equipment]
    session.commit()
    return schemas.RecomputeOut(factory_id=factory_id, anomaly_check_status=_factory_level_status(results), equipment=results)


ACTIVITY_CSV_COLUMNS = ["process_id", "fuel_key", "unit", "quantity", "month"]
ACTIVITY_CSV_TEMPLATE = (
    "process_id,fuel_key,unit,quantity,month\n"
    "kiln,natural_gas,SCM,420000,2026-05\n"
    "kiln,pet_coke,t,12.5,2026-05\n"
    "compressor,grid_electricity,MWh,38,2026-05\n"
)


@router.post("/{factory_id}/activity/csv", response_model=schemas.RecomputeOut)
async def append_activity_csv(factory_id: str, file: UploadFile, session: Session = Depends(get_db)):
    """Bulk version of POST .../activity: one row per (process, fuel, month)
    reading, straight from the columns a real utility bill / fuel-purchase
    log already has — closes the "dark data" gap the source research doc
    names directly (Part C.6: the evidence a leak/trend exists is usually
    already sitting in a bill or log, just never analysed as a pattern).
    Reuses the exact same validation and engine calls as the JSON endpoint
    via _apply_activity_entries — this is a parsing convenience, not a
    second code path with its own logic.
    """
    factory = _get_self_reported_factory_or_error(session, factory_id)

    raw = (await file.read()).decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(raw))
    missing_cols = [c for c in ACTIVITY_CSV_COLUMNS if c not in (reader.fieldnames or [])]
    if missing_cols:
        raise HTTPException(422, f"CSV missing required column(s): {missing_cols}. "
                                  f"Expected header: {','.join(ACTIVITY_CSV_COLUMNS)}")

    grouped: dict[str, list[schemas.OnboardActivityIn]] = {}
    row_count = 0
    for line_no, row in enumerate(reader, start=2):  # header is line 1
        row_count += 1
        try:
            quantity = float(row["quantity"])
        except (TypeError, ValueError):
            raise HTTPException(422, f"row {line_no}: quantity '{row.get('quantity')}' is not a number")
        process_id = (row["process_id"] or "").strip()
        if not process_id:
            raise HTTPException(422, f"row {line_no}: process_id is blank")
        grouped.setdefault(process_id, []).append(schemas.OnboardActivityIn(
            fuel_key=(row["fuel_key"] or "").strip(), unit=(row["unit"] or "").strip(),
            quantity=quantity, month=(row["month"] or "").strip(),
        ))
    if row_count == 0:
        raise HTTPException(422, "CSV has a header but no data rows")

    entries = [schemas.ActivityAppendIn(process_id=pid, activities=acts) for pid, acts in grouped.items()]
    _apply_activity_entries(session, factory, entries)
    results = [_recompute_equipment_anomalies(session, e, factory) for e in factory.equipment]
    session.commit()
    return schemas.RecomputeOut(factory_id=factory_id, anomaly_check_status=_factory_level_status(results), equipment=results)
