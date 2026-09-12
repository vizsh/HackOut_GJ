"""API response schemas (pydantic v2, from_attributes=True — built straight off
the SQLAlchemy ORM rows in app/db/models.py, no separate hand-maintained copy
of the same fields drifting out of sync)."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class ClusterOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    district: str
    lat: float
    lon: float
    dominant_sectors: str
    source: str
    confidence: str
    factory_count: int = 0
    open_anomaly_count: int = 0


class FactorySummaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    cluster_id: str
    sector: str
    district: str
    lat: float
    lon: float
    data_source: str
    consent_to_share: bool = True
    output_tonnes_per_year: Optional[float] = None


class EquipmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    process_id: str
    label: str
    kind: str
    share_of_energy: float
    benchmark_kgco2e_per_t: float
    benchmark_source: str
    benchmark_confidence: str
    co2e_tpy: Optional[float]
    share_of_total: Optional[float]
    actual_intensity: Optional[float]
    severity: Optional[str]
    root_cause_text: Optional[str]


class FactoryDetailOut(FactorySummaryOut):
    total_co2e_tpy: float
    equipment: list[EquipmentOut]


class EquipmentFullOut(EquipmentOut):
    recommendations: list["RecommendationOut"] = []


class FactoryFullOut(FactorySummaryOut):
    """Everything a client needs to render the dashboard/twin/simulator/rollup
    for one factory in a single request — equipment with nested recommendations.
    Used by the bulk GET /api/factories listing so the frontend can load the
    whole (small, ~120-factory) dataset once, the same way the pre-existing
    static-mock store held every factory in memory at once."""
    total_co2e_tpy: float
    total_energy_mwh_per_year: float
    total_waste_tpy: float
    circularity_ratio: float
    avoidable_co2e_tpy: float
    carbon_credit_value_inr_per_year: float
    carbon_credit_is_placeholder: bool = True
    carbon_credit_note: str
    equipment: list[EquipmentFullOut]
    anomaly_check_status: str = "available"  # available | partial | not_available — see routers/factories._anomaly_check_status
    worker_exposure_flags: list[str] = []  # keyword-heuristic VOC/solvent exposure risk notes, see routers/factories._worker_exposure_flags


class FactorySummaryLiteOut(BaseModel):
    """Cheap map/portfolio-view variant of FactoryFullOut — no nested equipment
    or recommendations, so listing all factories doesn't cost a full detail
    fetch per factory. Fetch FactoryFullOut on demand for the selected one."""
    id: str
    name: str
    cluster_id: str
    sector: str
    lat: float
    lon: float
    data_source: str
    total_co2e_tpy: float
    worst_severity: str  # ok | warn | crit — worst across this factory's equipment
    anomaly_check_status: str
    organization_id: Optional[str] = None


class EmissionMonthOut(BaseModel):
    month: str
    fuel_key: str
    co2e_t: float
    emission_factor_kgco2e_per_unit: float
    emission_factor_source: str


class BenchmarkLevelOut(BaseModel):
    level: str  # global | india | gujarat_cluster | factory
    available: bool
    value_kgco2e_per_t: Optional[float] = None
    source: Optional[str] = None
    confidence: Optional[str] = None
    note: Optional[str] = None


class BenchmarkOut(BaseModel):
    equipment_id: str
    process_label: str
    actual_intensity_kgco2e_per_t: Optional[float]
    deviation_pct: Optional[float]
    severity: Optional[str]
    levels: list[BenchmarkLevelOut]


class AnomalyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    equipment_id: str
    month: str
    co2e_t: float
    z_score: float
    status: str


class DiagnosisOut(BaseModel):
    anomaly: AnomalyOut
    equipment_label: str
    root_cause_text: str
    root_cause_rules: list[dict]
    explanation_source: str  # "deterministic_fallback" until Phase 3's LLM explainer lands


class RecommendationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    equipment_id: str
    intervention_key: str
    title: str
    category: str
    capex_inr: float
    annual_saving_inr: float
    co2_reduction_tpy: float
    payback_months: int
    confidence: str
    description: str
    circularity_gain_pct: Optional[float]
    rank: int


class InterventionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    key: str
    title: str
    category: str
    applies_to: list
    reduction_pct: float
    capex_base_inr: float
    saving_inr_per_tco2: float
    confidence: str
    description: str
    source: str


class EmissionFactorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    key: str
    label: str
    canonical_unit: str
    kgco2e_per_unit: float
    gj_per_unit: float
    source: str
    confidence: str


class ScaleProjectionOut(BaseModel):
    factory_count: int
    projected_total_co2e_tpy: float
    projected_avoidable_co2e_tpy: float
    projected_carbon_credit_value_inr: float
    sample_factory_count: int
    sample_avg_co2e_tpy: float
    sample_avg_avoidable_co2e_tpy: float
    methodology: str


class OnboardActivityIn(BaseModel):
    fuel_key: str
    unit: str
    quantity: float
    month: str


class OnboardProcessIn(BaseModel):
    process_id: str
    label: str
    kind: str
    share_of_energy: float
    activities: list[OnboardActivityIn]


class OnboardFactoryIn(BaseModel):
    name: str
    cluster_id: str
    sector: str
    output_tonnes_total: float
    processes: list[OnboardProcessIn]


class OnboardFactoryOut(BaseModel):
    id: str
    name: str
    total_co2e_t: float
    anomaly_check_status: str  # "not_available" — honest, see data-pipeline/LIMITATIONS.md
    recommendations: list[RecommendationOut]


class ActivityAppendIn(BaseModel):
    """Append another real month of submitted activity for one already-onboarded
    process — the only way a self-reported factory accumulates the >= 4 monthly
    points app/intelligence/anomaly.py needs before detection can activate."""
    process_id: str
    activities: list[OnboardActivityIn]


class RecomputeEquipmentOut(BaseModel):
    equipment_id: str
    anomaly_check_status: str  # available | not_available
    n_months: int
    anomalies_found: int


class RecomputeOut(BaseModel):
    factory_id: str
    anomaly_check_status: str  # available | partial | not_available
    equipment: list[RecomputeEquipmentOut]


class SymbiosisMatchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    provider_factory_id: str
    provider_factory_name: Optional[str] = None
    recipient_factory_id: str
    recipient_factory_name: Optional[str] = None
    waste_tag: str
    quantity_tpy: float
    distance_km: float
    semantic_score: float
    quantity_fit_score: float
    proximity_score: float
    overall_score: float
    co2_avoided_tpy: float
    provider_saving_inr: float
    recipient_saving_inr: float
    is_placeholder: bool


# --- Business-feature layer (organizations, usage metering, consent ledger,
# vendor directory, BRSR export, public API tier) ---------------------------

class OrganizationIn(BaseModel):
    name: str
    brand_color: str = "#3ea6ff"
    logo_text: str = ""


class OrganizationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    tier: str
    brand_color: str
    logo_text: str
    factory_count: int = 0


class OrganizationTierIn(BaseModel):
    tier: str  # free | pro


class AssignFactoryIn(BaseModel):
    organization_id: Optional[str]  # null unassigns


class UsageTrackIn(BaseModel):
    kind: str  # report_generated | chat_question | factory_onboarded
    organization_id: Optional[str] = None
    factory_id: Optional[str] = None


class UsageSummaryOut(BaseModel):
    organization_id: Optional[str]
    tier: str
    period: str  # "YYYY-MM"
    counts: dict[str, int]
    free_limits: dict[str, int]
    note: str


class ConsentToggleIn(BaseModel):
    consent_to_share: bool


class ConsentLedgerRowOut(BaseModel):
    factory_id: str
    factory_name: str
    data_source: str
    consent_to_share: bool
    consent_updated_at: datetime
    visible_to_regulator: bool


class VendorContactOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    category: str
    name: str
    contact_email: str
    phone: str
    region: str
    notes: str


class BrsrPrincipleOut(BaseModel):
    principle: str
    title: str
    disclosures: list[dict]


class BrsrReportOut(BaseModel):
    factory_id: str
    factory_name: str
    reporting_period: str
    principles: list[BrsrPrincipleOut]
    methodology_note: str


class ApiKeyCreateIn(BaseModel):
    organization_id: Optional[str] = None
    label: str = ""
    rate_limit_per_min: int = 30


class ApiKeyOut(BaseModel):
    key: str
    organization_id: Optional[str]
    label: str
    rate_limit_per_min: int
    created_at: datetime


class CompressedAirLoadUnloadIn(BaseModel):
    rated_capacity_cfm: float
    load_time_min: float
    unload_time_min: float
    operating_hours_per_year: float = 8760.0
    electricity_rate_inr_per_kwh: float
    specific_power_kw_per_100cfm: Optional[float] = None


class CompressedAirUnauditedIn(BaseModel):
    rated_capacity_cfm: float
    operating_hours_per_year: float = 8760.0
    electricity_rate_inr_per_kwh: float
    specific_power_kw_per_100cfm: Optional[float] = None


class RefrigerantLeakIn(BaseModel):
    refrigerant_key: str
    nameplate_charge_kg: float
    annual_topup_kg: float
    refrigerant_cost_inr_per_kg: float


class LeakAssessmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    factory_id: str
    kind: str
    method: str
    inputs: dict
    leak_rate_pct: float
    co2e_tpy: float
    cost_inr_per_year: float
    note: str
    created_at: datetime


class WaterBenchmarkOut(BaseModel):
    factory_id: str
    available: bool
    litres_per_kg_submitted: Optional[float] = None
    benchmark_low_litres_per_kg: Optional[float] = None
    benchmark_high_litres_per_kg: Optional[float] = None
    deviation_note: Optional[str] = None
    source: str


class CrossProcessInsightOut(BaseModel):
    finding: str
    equipment_a: str
    equipment_b: str
    note: str


class PublicFactoryOut(BaseModel):
    """Deliberately narrow — the public API tier exposes a read-only summary,
    not the full per-equipment detail an authenticated frontend session gets."""
    id: str
    name: str
    sector: str
    cluster_id: str
    total_co2e_tpy: float
    worst_severity: str
    data_source: str
