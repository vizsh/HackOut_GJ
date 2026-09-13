"""Idempotent seed loader.

Loads data-pipeline/clean/*.csv + data-pipeline/synth/factories_synthetic.json,
inserts raw rows (clusters, factories, equipment, energy records, waste
records, catalogs), then computes every derived value — CO2e, benchmark
deviation, severity, anomalies, root-cause text, sized recommendations — by
calling the actual functions in app/engine and app/intelligence. Nothing
computed is hand-typed; see data-pipeline/LIMITATIONS.md #5 for why this
matters.

Run with: python -m app.db.seed_loader
Safe to re-run: it wipes and rebuilds every table each time (small dataset,
demo/dev only — a production seed would be additive, not destructive).
"""
from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy.orm import Session

from .. import auth
from .. import models as m
from .. import seed as seed_data
from ..engine import emissions, intensity, units
from ..intelligence import anomaly as anomaly_engine
from ..intelligence import recommender
from ..intelligence import rootcause
from . import models as db
from .base import Base, SessionLocal, engine

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
SYNTH_FILE = REPO_ROOT / "data-pipeline" / "synth" / "factories_synthetic.json"


def _load_synthetic_factories() -> list[dict]:
    return json.loads(SYNTH_FILE.read_text(encoding="utf-8"))


def _seed_catalogs(session: Session) -> None:
    for key, ef in seed_data.emission_factors().items():
        session.merge(db.EmissionFactor(
            key=key, label=ef["label"], canonical_unit=ef["canonicalUnit"],
            kgco2e_per_unit=ef["kgco2ePerUnit"], gj_per_unit=ef["gjPerUnit"],
            source=ef["source"], confidence=ef["confidence"],
        ))
    for entry in seed_data.intervention_library():
        session.merge(db.Intervention(
            key=entry["key"], title=entry["title"], category=entry["category"],
            applies_to=entry["appliesTo"], reduction_pct=entry["reductionPct"],
            capex_base_inr=entry["capexBaseInr"], saving_inr_per_tco2=entry["savingInrPerTco2"],
            confidence=entry["confidence"], description=entry["description"],
            source=entry.get("source", ""),
        ))
    for c in seed_data.clusters():
        session.merge(db.Cluster(
            id=c["id"], name=c["name"], district=c["district"], lat=c["lat"], lon=c["lon"],
            dominant_sectors=";".join(c["dominantSectors"]), source=c["source"], confidence=c["confidence"],
        ))
    for v in seed_data.vendor_directory():
        session.add(db.VendorContact(
            category=v["category"], name=v["name"], contact_email=v["contact_email"],
            phone=v["phone"], region=v["region"], notes=v["notes"],
        ))
    # One demo consultant organization so Portfolio/white-labeling has
    # something real to group factories under out of the box — not required,
    # any factory can also be created unassigned or a new org created via
    # POST /api/organizations.
    session.add(db.Organization(
        id="demo-consultancy", name="Gujarat Decarb Advisors (demo)", tier="free",
        brand_color="#3ea6ff", logo_text="GDA",
    ))

    # Demo accounts so the real login (app/auth.py) is usable without a
    # signup flow — one per role, all in the demo org. Passwords are
    # deliberately simple and printed in backend/README.md: this is a
    # hackathon demo credential set, not a production account.
    for uid, email, role in [
        ("demo-sme", "sme@induscope.demo", "sme"),
        ("demo-consultant", "consultant@induscope.demo", "consultant"),
        ("demo-regulator", "regulator@induscope.demo", "regulator"),
    ]:
        session.add(db.User(
            id=uid, email=email, password_hash=auth.hash_password("induscope-demo"),
            role=role, organization_id="demo-consultancy",
        ))
    session.commit()


def _co2e_for_activity(fuel_key: str, quantity: float, canonical_unit: str) -> tuple[float, float, str]:
    """Run one activity reading through the real engine (units.normalise +
    emissions.co2e_for) rather than recomputing the formula inline here."""
    activity = m.Activity(fuel=fuel_key, unit=canonical_unit, quantity=quantity)
    normalised, issue = units.normalise(activity)
    if issue is not None:
        raise ValueError(f"engine rejected activity {fuel_key}/{canonical_unit}: {issue.message}")
    co2e_t = emissions.co2e_for(normalised)
    return co2e_t, normalised.kgco2e_per_unit, normalised.source


def _seed_factories(session: Session) -> dict:
    """Returns a summary dict for the final report."""
    factories_raw = _load_synthetic_factories()
    stats = {"factories": 0, "equipment": 0, "energy_records": 0, "emission_records": 0,
             "anomalies": 0, "recommendations": 0, "waste_streams": 0, "accepted_inputs": 0}

    for fac_raw in factories_raw:
        annual_output_t = sum(fac_raw["monthly_output_tonnes"])
        factory = db.Factory(
            id=fac_raw["id"], name=fac_raw["name"], cluster_id=fac_raw["cluster_id"],
            sector=fac_raw["sector"], district=fac_raw["district"], lat=fac_raw["lat"],
            lon=fac_raw["lon"], data_source=fac_raw["data_source"],
            consent_to_share=fac_raw["consent_to_share"], output_tonnes_per_year=annual_output_t,
        )
        session.add(factory)
        stats["factories"] += 1

        for waste_rec in fac_raw["monthly_waste"]:
            session.add(db.WasteRecord(
                factory_id=factory.id, month=waste_rec["month"],
                hazardous_waste_t=waste_rec["hazardous_waste_t"],
                general_process_waste_t=waste_rec["general_process_waste_t"],
            ))

        for stream in fac_raw.get("waste_streams", []):
            session.add(db.WasteStream(
                factory_id=factory.id, tag=stream["tag"], label=stream["label"],
                form=stream["form"], tpy=stream["tpy"],
                disposal_cost_inr_per_t=stream["disposal_cost_inr_per_t"],
            ))
            stats["waste_streams"] += 1
        for inp in fac_raw.get("accepted_inputs", []):
            session.add(db.AcceptedInput(
                factory_id=factory.id, tag=inp["tag"], label=inp["label"],
                max_tpy=inp["max_tpy"], virgin_cost_inr_per_t=inp["virgin_cost_inr_per_t"],
            ))
            stats["accepted_inputs"] += 1

        equipment_rows: list[db.Equipment] = []
        for proc in fac_raw["processes"]:
            equip_id = f"{factory.id}:{proc['process_id']}"
            equip = db.Equipment(
                id=equip_id, factory_id=factory.id, process_id=proc["process_id"],
                label=proc["label"], kind=proc["kind"], share_of_energy=proc["share_of_energy"],
                benchmark_kgco2e_per_t=None, benchmark_source=proc["benchmark_source"],
                benchmark_confidence=proc["benchmark_confidence"],
            )
            # benchmark value lives in sector_templates(), keyed by sector+process_id
            bench_row = next(
                (t for t in seed_data.sector_templates()[fac_raw["sector"]] if t["id"] == proc["process_id"]),
                None,
            )
            equip.benchmark_kgco2e_per_t = bench_row["benchmark"] if bench_row else 0.0
            session.add(equip)
            stats["equipment"] += 1

            monthly_co2e: list[tuple[str, float]] = []
            for rec in proc["monthly_activity"]:
                month_total_co2e = 0.0
                for fuel_key, qty in rec["fuel_quantities"].items():
                    ef_row = seed_data.emission_factors()[fuel_key]
                    co2e_t, ef_value, ef_source = _co2e_for_activity(fuel_key, qty, ef_row["canonicalUnit"])
                    session.add(db.EnergyRecord(
                        equipment_id=equip_id, month=rec["month"], fuel_key=fuel_key,
                        quantity=qty, canonical_unit=ef_row["canonicalUnit"],
                    ))
                    session.add(db.EmissionRecord(
                        equipment_id=equip_id, month=rec["month"], fuel_key=fuel_key,
                        co2e_t=co2e_t, emission_factor_kgco2e_per_unit=ef_value,
                        emission_factor_source=ef_source,
                    ))
                    month_total_co2e += co2e_t
                    stats["energy_records"] += 1
                    stats["emission_records"] += 1
                monthly_co2e.append((rec["month"], month_total_co2e))

            co2e_tpy = sum(v for _, v in monthly_co2e)
            equip.co2e_tpy = round(co2e_tpy, 2)

            equipment_output_tpy = annual_output_t * proc["share_of_energy"]
            equip.actual_intensity = intensity.intensity_kg_per_t(co2e_tpy, equipment_output_tpy)

            ratio = equip.actual_intensity / equip.benchmark_kgco2e_per_t if equip.benchmark_kgco2e_per_t else 1.0
            equip.severity = intensity.severity_from_ratio(ratio)

            points = anomaly_engine.detect_anomalies(monthly_co2e)
            for p in points:
                if p.anomaly:
                    session.add(db.Anomaly(
                        equipment_id=equip_id, month=p.month, co2e_t=p.co2eT, z_score=p.z, status="open",
                    ))
                    stats["anomalies"] += 1

            node = m.ProcessNode(
                id=equip_id, label=equip.label, kind=equip.kind, co2eTpy=co2e_tpy,
                shareOfTotal=0.0, actualIntensity=equip.actual_intensity,
                benchmarkIntensity=equip.benchmark_kgco2e_per_t, severity=equip.severity,
                monthly=points,
            )
            hits = rootcause.diagnose(node, sector_hint=fac_raw["sector"], output_tpm=equipment_output_tpy / 12, fuel_mix=None)
            equip.root_cause_text = rootcause.narrative(hits, fallback="No rule fired — process runs close to its own historical baseline.")
            equip.root_cause_rules = [h.model_dump() for h in hits]

            equipment_rows.append(equip)

        total_co2e = sum(e.co2e_tpy for e in equipment_rows) or 1.0
        for e in equipment_rows:
            e.share_of_total = round(e.co2e_tpy / total_co2e, 3)

        for equip, node_kind in zip(equipment_rows, [e.kind for e in equipment_rows]):
            equipment_output_tpy = annual_output_t * equip.share_of_energy
            node = m.ProcessNode(
                id=equip.id, label=equip.label, kind=equip.kind, co2eTpy=equip.co2e_tpy,
                shareOfTotal=equip.share_of_total, actualIntensity=equip.actual_intensity,
                benchmarkIntensity=equip.benchmark_kgco2e_per_t, severity=equip.severity,
            )
            for iv in recommender.interventions_for(node, fac_raw["sector"]):
                # recommender.py builds iv.id as f"{equip_id}:{intervention_key}", and
                # equip_id itself is "factory_id:process_id" (contains its own colon), so
                # splitting on the first colon left a stray "process_id:" prefix in the
                # stored intervention_key. Strip the exact equip_id prefix instead.
                key = iv.id[len(equip.id) + 1:]
                session.add(db.Recommendation(
                    id=f"{equip.id}:{key}", equipment_id=equip.id, intervention_key=key,
                    title=iv.title, category=iv.category, capex_inr=iv.capexInr,
                    annual_saving_inr=iv.annualSavingInr, co2_reduction_tpy=iv.co2ReductionTpy,
                    payback_months=iv.paybackMonths, confidence=iv.confidence,
                    description=iv.description, circularity_gain_pct=iv.circularityGainPct,
                    rank=len([r for r in session.new if isinstance(r, db.Recommendation) and r.equipment_id == equip.id]),
                    applied=False,
                ))
                stats["recommendations"] += 1

        session.flush()

    session.commit()
    return stats


def main() -> None:
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)

    session = SessionLocal()
    try:
        _seed_catalogs(session)
        stats = _seed_factories(session)
    finally:
        session.close()

    print("Seed complete:")
    for k, v in stats.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
