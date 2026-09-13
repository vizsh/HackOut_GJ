"""SQLAlchemy ORM models — the 12-table schema.

Tables: Cluster, Factory, Equipment, EnergyRecord, WasteRecord, EmissionRecord,
Anomaly, Recommendation, SymbiosisMatch, Intervention, EmissionFactor, Explanation.

EmissionRecord/Anomaly/Recommendation rows are never hand-inserted — they are
written only by db/seed_loader.py calling the real functions in app/engine and
app/intelligence, so every row traces to a function call on real-or-calibrated
input (see data-pipeline/LIMITATIONS.md #5 for why this matters).
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class Organization(Base):
    """A consulting firm / SME group workspace — the unit white-labeled
    reports and portfolio grouping hang off, and (see User below) the unit
    real logged-in users belong to. `tier` gates simulator/symbiosis/report/
    BRSR features in the frontend and the free-report usage meter below."""
    __tablename__ = "organizations"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    tier: Mapped[str] = mapped_column(String, default="free")  # free | pro
    brand_color: Mapped[str] = mapped_column(String, default="#3ea6ff")
    logo_text: Mapped[str] = mapped_column(String, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    factories: Mapped[list["Factory"]] = relationship(back_populates="organization")
    users: Mapped[list["User"]] = relationship(back_populates="organization")


class User(Base):
    """A real logged-in account — see app/auth.py for the password hashing
    (PBKDF2-HMAC-SHA256, stdlib only) and signed session tokens
    (HMAC-SHA256, no JWT library needed) behind POST /api/auth/login. Closes
    a real, previously-disclosed gap: organizations/consent/API-keys were
    real backend objects with zero authentication in front of them."""
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[str] = mapped_column(String, nullable=False)  # sme | consultant | regulator
    organization_id: Mapped[Optional[str]] = mapped_column(ForeignKey("organizations.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    organization: Mapped[Optional["Organization"]] = relationship(back_populates="users")


class UsageEvent(Base):
    """One countable action against the freemium usage meter (report
    generated, chat question asked, factory onboarded). Real counter behind
    the "3 of 5 free reports used" UI — not a client-side guess. Logged by
    routers/business.py's POST /api/usage/track, called from the frontend
    at the moment each action actually happens."""
    __tablename__ = "usage_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    organization_id: Mapped[Optional[str]] = mapped_column(ForeignKey("organizations.id"), nullable=True)
    kind: Mapped[str] = mapped_column(String, nullable=False)  # report_generated | chat_question | factory_onboarded
    factory_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class VendorContact(Base):
    """Seeded static directory — 2-3 illustrative EPC/vendor contacts per
    intervention category (heat-recovery, process-change, etc.), so a
    recommendation can answer "who do I call", not just "what to do". Contact
    details are placeholder/illustrative, not a vetted vendor panel — see
    app/seed.py vendor_directory() docstring."""
    __tablename__ = "vendor_contacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    category: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    contact_email: Mapped[str] = mapped_column(String, nullable=False)
    phone: Mapped[str] = mapped_column(String, nullable=False)
    region: Mapped[str] = mapped_column(String, nullable=False)
    notes: Mapped[str] = mapped_column(Text, nullable=False)


class ApiKey(Base):
    """A minted key for the public read-only API tier (routers/business.py
    require_api_key). Rate limiting is an in-memory sliding window keyed by
    this key (see routers/business.py _RATE_LIMITER) — real for the life of
    one server process, not a distributed/persisted limiter; disclosed as a
    demo simplification, not hidden."""
    __tablename__ = "api_keys"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    organization_id: Mapped[Optional[str]] = mapped_column(ForeignKey("organizations.id"), nullable=True)
    label: Mapped[str] = mapped_column(String, default="")
    rate_limit_per_min: Mapped[int] = mapped_column(Integer, default=30)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    request_count: Mapped[int] = mapped_column(Integer, default=0)


class Cluster(Base):
    __tablename__ = "clusters"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    district: Mapped[str] = mapped_column(String, nullable=False)
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lon: Mapped[float] = mapped_column(Float, nullable=False)
    dominant_sectors: Mapped[str] = mapped_column(String)  # ";"-joined
    source: Mapped[str] = mapped_column(Text)
    confidence: Mapped[str] = mapped_column(String)

    factories: Mapped[list["Factory"]] = relationship(back_populates="cluster")


class Factory(Base):
    __tablename__ = "factories"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    cluster_id: Mapped[str] = mapped_column(ForeignKey("clusters.id"), nullable=False)
    sector: Mapped[str] = mapped_column(String, nullable=False)
    district: Mapped[str] = mapped_column(String)
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)
    data_source: Mapped[str] = mapped_column(String, default="synthetic")  # synthetic | self_reported
    consent_to_share: Mapped[bool] = mapped_column(Boolean, default=True)
    consent_updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    output_tonnes_per_year: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    organization_id: Mapped[Optional[str]] = mapped_column(ForeignKey("organizations.id"), nullable=True)

    cluster: Mapped["Cluster"] = relationship(back_populates="factories")
    organization: Mapped[Optional["Organization"]] = relationship(back_populates="factories")
    equipment: Mapped[list["Equipment"]] = relationship(back_populates="factory", cascade="all, delete-orphan")
    waste_records: Mapped[list["WasteRecord"]] = relationship(back_populates="factory", cascade="all, delete-orphan")
    waste_streams: Mapped[list["WasteStream"]] = relationship(back_populates="factory", cascade="all, delete-orphan")
    accepted_inputs: Mapped[list["AcceptedInput"]] = relationship(back_populates="factory", cascade="all, delete-orphan")


class Equipment(Base):
    """A process node (kiln, boiler, compressor, ...) within a factory."""
    __tablename__ = "equipment"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # f"{factory_id}:{process_id}"
    factory_id: Mapped[str] = mapped_column(ForeignKey("factories.id"), nullable=False)
    process_id: Mapped[str] = mapped_column(String, nullable=False)
    label: Mapped[str] = mapped_column(String, nullable=False)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    share_of_energy: Mapped[float] = mapped_column(Float, nullable=False)
    benchmark_kgco2e_per_t: Mapped[float] = mapped_column(Float, nullable=False)
    benchmark_source: Mapped[str] = mapped_column(Text)
    benchmark_confidence: Mapped[str] = mapped_column(String)

    # computed by db/seed_loader.py via app/engine + app/intelligence, not asserted
    co2e_tpy: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    share_of_total: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    actual_intensity: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    severity: Mapped[Optional[str]] = mapped_column(String, nullable=True)  # ok | warn | crit
    root_cause_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    root_cause_rules: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)

    factory: Mapped["Factory"] = relationship(back_populates="equipment")
    energy_records: Mapped[list["EnergyRecord"]] = relationship(back_populates="equipment", cascade="all, delete-orphan")
    emission_records: Mapped[list["EmissionRecord"]] = relationship(back_populates="equipment", cascade="all, delete-orphan")
    anomalies: Mapped[list["Anomaly"]] = relationship(back_populates="equipment", cascade="all, delete-orphan")
    recommendations: Mapped[list["Recommendation"]] = relationship(back_populates="equipment", cascade="all, delete-orphan")


class EnergyRecord(Base):
    """One fuel/electricity activity reading for one equipment-month. Raw input,
    straight from data-pipeline/synth/factories_synthetic.json — never mutated."""
    __tablename__ = "energy_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    equipment_id: Mapped[str] = mapped_column(ForeignKey("equipment.id"), nullable=False)
    month: Mapped[str] = mapped_column(String, nullable=False)  # "YYYY-MM"
    fuel_key: Mapped[str] = mapped_column(String, nullable=False)
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    canonical_unit: Mapped[str] = mapped_column(String, nullable=False)

    equipment: Mapped["Equipment"] = relationship(back_populates="energy_records")


class WasteRecord(Base):
    __tablename__ = "waste_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    factory_id: Mapped[str] = mapped_column(ForeignKey("factories.id"), nullable=False)
    month: Mapped[str] = mapped_column(String, nullable=False)
    hazardous_waste_t: Mapped[float] = mapped_column(Float, nullable=False)
    general_process_waste_t: Mapped[float] = mapped_column(Float, nullable=False)

    factory: Mapped["Factory"] = relationship(back_populates="waste_records")


class WasteStream(Base):
    """A tagged waste stream a factory outputs — the input side of symbiosis
    matching. Distinct from WasteRecord (monthly aggregate hazardous/general
    tonnage): this is per-tag, sized off that aggregate, and is what the
    Phase 3c matcher (ml/symbiosis_model.py) actually matches on. See
    data-pipeline/clean/waste_stream_profiles.csv for sourcing."""
    __tablename__ = "waste_streams"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    factory_id: Mapped[str] = mapped_column(ForeignKey("factories.id"), nullable=False)
    tag: Mapped[str] = mapped_column(String, nullable=False)
    label: Mapped[str] = mapped_column(String, nullable=False)
    form: Mapped[str] = mapped_column(String, nullable=False)  # solid | liquid | heat
    tpy: Mapped[float] = mapped_column(Float, nullable=False)
    disposal_cost_inr_per_t: Mapped[float] = mapped_column(Float, nullable=False)

    factory: Mapped["Factory"] = relationship(back_populates="waste_streams")


class AcceptedInput(Base):
    """A tagged material a factory could accept as input — the demand side of
    symbiosis matching. See data-pipeline/clean/waste_stream_profiles.csv."""
    __tablename__ = "accepted_inputs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    factory_id: Mapped[str] = mapped_column(ForeignKey("factories.id"), nullable=False)
    tag: Mapped[str] = mapped_column(String, nullable=False)
    label: Mapped[str] = mapped_column(String, nullable=False)
    max_tpy: Mapped[float] = mapped_column(Float, nullable=False)
    virgin_cost_inr_per_t: Mapped[float] = mapped_column(Float, nullable=False)

    factory: Mapped["Factory"] = relationship(back_populates="accepted_inputs")


class EmissionRecord(Base):
    """CO2e for one equipment-month-fuel, computed by app/engine/emissions.co2e_for.
    Formula: tCO2e = canonical_qty * kgco2e_per_unit / 1000. Never hand-entered."""
    __tablename__ = "emission_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    equipment_id: Mapped[str] = mapped_column(ForeignKey("equipment.id"), nullable=False)
    month: Mapped[str] = mapped_column(String, nullable=False)
    fuel_key: Mapped[str] = mapped_column(String, nullable=False)
    co2e_t: Mapped[float] = mapped_column(Float, nullable=False)
    emission_factor_kgco2e_per_unit: Mapped[float] = mapped_column(Float, nullable=False)
    emission_factor_source: Mapped[str] = mapped_column(Text, nullable=False)

    equipment: Mapped["Equipment"] = relationship(back_populates="emission_records")


class Anomaly(Base):
    """A flagged process-month, computed by app/intelligence/anomaly.detect_anomalies
    (leave-one-out z-score against that equipment's own monthly series, +8% relative
    guard) — never a flat threshold. See CLAUDE.md non-negotiable constraint."""
    __tablename__ = "anomalies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    equipment_id: Mapped[str] = mapped_column(ForeignKey("equipment.id"), nullable=False)
    month: Mapped[str] = mapped_column(String, nullable=False)
    co2e_t: Mapped[float] = mapped_column(Float, nullable=False)
    z_score: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String, default="open")  # open | resolved | dismissed

    equipment: Mapped["Equipment"] = relationship(back_populates="anomalies")


class Recommendation(Base):
    """A sized intervention for one equipment, computed by
    app/intelligence/recommender.interventions_for — CAPEX/saving/payback are
    derived from that equipment's own co2e_tpy, not looked up as a flat number."""
    __tablename__ = "recommendations"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # f"{equipment_id}:{intervention_key}"
    equipment_id: Mapped[str] = mapped_column(ForeignKey("equipment.id"), nullable=False)
    intervention_key: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    category: Mapped[str] = mapped_column(String, nullable=False)
    capex_inr: Mapped[float] = mapped_column(Float, nullable=False)
    annual_saving_inr: Mapped[float] = mapped_column(Float, nullable=False)
    co2_reduction_tpy: Mapped[float] = mapped_column(Float, nullable=False)
    payback_months: Mapped[int] = mapped_column(Integer, nullable=False)
    confidence: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    circularity_gain_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    # Whether the user has marked this intervention as actually implemented —
    # the one real, persisted "did this happen" flag in the app (distinct from
    # the Simulate page's ephemeral what-if toggle, which never writes here).
    # Drives factories.py's circularity_ratio computation: see that function's
    # docstring for why summing applied circular interventions' own
    # circularity_gain_pct is the honest replacement for the old hardcoded 0.0.
    applied: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0", nullable=False)

    equipment: Mapped["Equipment"] = relationship(back_populates="recommendations")


class SymbiosisMatch(Base):
    """Populated by ml/symbiosis_model.py (Phase 3c) — MiniLM semantic
    similarity + quantity fit + proximity, weighted 50/25/25 per the Induscope
    vision doc. The full score breakdown is stored, not just the blend, so
    the API/frontend can show why a match ranked where it did rather than a
    bare number. co2_avoided_tpy is always is_placeholder=True: no sourced
    embodied-carbon dataset exists for these waste categories yet."""
    __tablename__ = "symbiosis_matches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider_factory_id: Mapped[str] = mapped_column(ForeignKey("factories.id"), nullable=False)
    recipient_factory_id: Mapped[str] = mapped_column(ForeignKey("factories.id"), nullable=False)
    waste_tag: Mapped[str] = mapped_column(String, nullable=False)
    quantity_tpy: Mapped[float] = mapped_column(Float, nullable=False)
    distance_km: Mapped[float] = mapped_column(Float, nullable=False)
    semantic_score: Mapped[float] = mapped_column(Float, nullable=False)
    quantity_fit_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    proximity_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    overall_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    co2_avoided_tpy: Mapped[float] = mapped_column(Float, nullable=False)
    # Real, computed from the provider's own disposal_cost_inr_per_t and the
    # recipient's own virgin_cost_inr_per_t (data-pipeline/clean/waste_stream_profiles.csv)
    # — the tonnage and cost rates are real, only the assumption that a
    # recipient captures 60% of the virgin-material price as savings is a
    # documented modelling choice (same 60% the pre-existing frontend used).
    provider_saving_inr: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    recipient_saving_inr: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    is_placeholder: Mapped[bool] = mapped_column(Boolean, default=True)


class Intervention(Base):
    """Static catalog — the 17-entry circular-intervention library, unchanged
    from backend/data/interventions.json (Phase 1 audit did not find sourcing
    issues here; see data-pipeline/sources.md)."""
    __tablename__ = "interventions"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    category: Mapped[str] = mapped_column(String, nullable=False)
    applies_to: Mapped[list] = mapped_column(JSON, nullable=False)
    reduction_pct: Mapped[float] = mapped_column(Float, nullable=False)
    capex_base_inr: Mapped[float] = mapped_column(Float, nullable=False)
    saving_inr_per_tco2: Mapped[float] = mapped_column(Float, nullable=False)
    confidence: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)


class EmissionFactor(Base):
    """Static catalog — the sourced fuel/electricity emission factors, loaded
    straight from data-pipeline/clean/emission_factors.csv (Phase 1 output)."""
    __tablename__ = "emission_factors"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    label: Mapped[str] = mapped_column(String, nullable=False)
    canonical_unit: Mapped[str] = mapped_column(String, nullable=False)
    kgco2e_per_unit: Mapped[float] = mapped_column(Float, nullable=False)
    gj_per_unit: Mapped[float] = mapped_column(Float, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[str] = mapped_column(String, nullable=False)


class LeakAssessment(Base):
    """A computed, invoice/nameplate-based leak estimate — compressed air or
    refrigerant — per app/intelligence/leak_estimators.py. Deliberately kept
    separate from the equipment/EmissionRecord engine: these are additional,
    off-engine diagnostics computed from data a plant already has on hand
    (compressor control-panel timing, refrigerant purchase invoices), not a
    re-measurement of an existing equipment row, so they are never double
    counted into total_co2e_tpy — surfaced as their own avoidable_co2e_tpy /
    avoidable_cost_inr on top of the normal per-process diagnosis."""
    __tablename__ = "leak_assessments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    factory_id: Mapped[str] = mapped_column(ForeignKey("factories.id"), nullable=False)
    kind: Mapped[str] = mapped_column(String, nullable=False)  # compressed_air | refrigerant
    method: Mapped[str] = mapped_column(String, nullable=False)
    inputs: Mapped[dict] = mapped_column(JSON, nullable=False)
    leak_rate_pct: Mapped[float] = mapped_column(Float, nullable=False)
    co2e_tpy: Mapped[float] = mapped_column(Float, nullable=False)
    cost_inr_per_year: Mapped[float] = mapped_column(Float, nullable=False)
    note: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Explanation(Base):
    """Reserved for Phase 3 (Ollama LLM + deterministic-fallback explainer).
    Schema exists now so Phase 3 only needs to add write logic, not a migration.
    Empty until that phase — no placeholder text is inserted here."""
    __tablename__ = "explanations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    subject_type: Mapped[str] = mapped_column(String, nullable=False)  # anomaly | recommendation | match
    subject_id: Mapped[str] = mapped_column(String, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    generated_by: Mapped[str] = mapped_column(String, nullable=False)  # "ollama:llama3.1:8b" | "deterministic_fallback"
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
