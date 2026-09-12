from __future__ import annotations

import sys
from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import carbon_credit, schemas
from ..db import models as db
from ..deps import get_db
from . import leaks as leaks_router
from . import onboarding as onboarding_router

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ml.registry import registry  # noqa: E402

router = APIRouter(prefix="/api", tags=["catalog"])


@router.get("/csv-templates/activity", response_class=PlainTextResponse)
def activity_csv_template():
    """Downloadable starting point for POST /api/factories/{id}/activity/csv
    — the same fields already on a real utility bill (fuel type, quantity,
    billing month). Kept in this router (not under /api/factories) so its
    literal path never collides with GET /api/factories/{factory_id}."""
    return PlainTextResponse(
        onboarding_router.ACTIVITY_CSV_TEMPLATE, media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=induscope_activity_template.csv"},
    )


@router.get("/csv-templates/leak-assessments", response_class=PlainTextResponse)
def leak_assessments_csv_template():
    """Downloadable starting point for POST /api/factories/{id}/leak-assessments/csv."""
    return PlainTextResponse(
        leaks_router.LEAK_CSV_TEMPLATE, media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=induscope_leak_assessments_template.csv"},
    )


@router.get("/ml/status")
def ml_status():
    """What's actually active for each Phase-3 ML component, not just what
    exists on disk — see ml/registry.py ModelRegistry.status()."""
    return registry.status()


@router.get("/interventions", response_model=list[schemas.InterventionOut])
def list_interventions(session: Session = Depends(get_db)):
    return session.scalars(select(db.Intervention)).all()


@router.get("/emission-factors", response_model=list[schemas.EmissionFactorOut])
def list_emission_factors(session: Session = Depends(get_db)):
    return session.scalars(select(db.EmissionFactor)).all()


@router.get("/symbiosis/network", response_model=list[schemas.SymbiosisMatchOut])
def symbiosis_network(session: Session = Depends(get_db)):
    """Every symbiosis match across the whole cohort, computed by
    ml/symbiosis_model.py (Phase 3c). co2_avoided_tpy is always
    is_placeholder=True — see data-pipeline/LIMITATIONS.md #1."""
    rows = session.scalars(select(db.SymbiosisMatch).order_by(db.SymbiosisMatch.overall_score.desc())).all()
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


@router.get("/scale-projection", response_model=schemas.ScaleProjectionOut)
def scale_projection(factory_count: int = 5000, session: Session = Depends(get_db)):
    """'What if this scaled to N factories' projection.

    Method (printed verbatim in the response, not summarised): take the mean
    total CO2e/yr and mean recommended-avoidable CO2e/yr across the 120 seeded
    factories actually in the database, and scale linearly by factory_count.
    This is a linear extrapolation from the calibrated synthetic sample, not a
    forecast grounded in a real Gujarat-wide industrial census (that data does
    not exist — see data-pipeline/LIMITATIONS.md #1) — every number the
    frontend shows for this endpoint must carry that caveat, not hide it.
    """
    factories = session.scalars(select(db.Factory)).all()
    n = len(factories) or 1

    total_co2e = 0.0
    total_avoidable = 0.0
    for f in factories:
        total_co2e += sum(e.co2e_tpy or 0.0 for e in f.equipment)
        # Best single recommendation per equipment — matches the per-factory
        # GET /api/factories/{id} convention, not a sum of every overlapping
        # recommendation (which would double-count fixes on one process).
        total_avoidable += sum(
            max((r.co2_reduction_tpy for r in e.recommendations), default=0.0)
            for e in f.equipment
        )

    avg_co2e = total_co2e / n
    avg_avoidable = total_avoidable / n
    scale = factory_count / n
    projected_avoidable = round(avg_avoidable * factory_count, 1)
    projected_credit_value = carbon_credit.credit_value_inr(projected_avoidable)

    methodology = (
        f"projected_total = mean(factory total_co2e_tpy across {n} seeded factories) x "
        f"factory_count; projected_avoidable = mean(best single recommendation per "
        f"equipment, summed per factory, across {n} seeded factories) x factory_count. "
        f"Linear extrapolation from a calibrated synthetic sample, not a Gujarat-wide "
        f"census (none exists — see data-pipeline/LIMITATIONS.md #1). "
        f"projected_carbon_credit_value_inr = projected_avoidable x "
        f"Rs {carbon_credit.INDICATIVE_PRICE_INR_PER_TCO2E:.0f}/tCO2e "
        f"({carbon_credit.SOURCE_NOTE}). "
        f"sample_avg_co2e_tpy={avg_co2e:.1f}, sample_avg_avoidable_co2e_tpy={avg_avoidable:.1f}, "
        f"scale_factor={scale:.2f}."
    )

    return schemas.ScaleProjectionOut(
        factory_count=factory_count,
        projected_total_co2e_tpy=round(avg_co2e * factory_count, 1),
        projected_avoidable_co2e_tpy=projected_avoidable,
        projected_carbon_credit_value_inr=projected_credit_value,
        sample_factory_count=n,
        sample_avg_co2e_tpy=round(avg_co2e, 1),
        sample_avg_avoidable_co2e_tpy=round(avg_avoidable, 1),
        methodology=methodology,
    )
