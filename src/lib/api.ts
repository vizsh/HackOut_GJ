// Typed fetch client for the Induscope backend (backend/app/main.py).
// See backend/README.md for the endpoint list — every field returned here
// traces to a real computation (app/engine + app/intelligence over
// data-pipeline output), not a mock.

import { useAuthStore } from "../store/useAuthStore";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8811";

// Real session token (backend/app/auth.py), attached automatically to every
// request when the user is logged in — the protected mutating endpoints
// (organizations, consent, API keys) 401 without it, see business.py.
function authHeaders(): Record<string, string> {
  const token = useAuthStore.getState().token;
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { headers: authHeaders() });
  if (!res.ok) throw new Error(`GET ${path} failed: ${res.status} ${res.statusText}`);
  return res.json() as Promise<T>;
}

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => null);
    throw new Error(`POST ${path} failed: ${res.status} ${detail?.detail ?? res.statusText}`);
  }
  return res.json() as Promise<T>;
}

export type AskStreamEvent =
  | { type: "token"; text: string }
  | { type: "final"; answer: string; verified_data: Record<string, unknown> | null; source: string };

/** Reads backend/app/routers/explainer.py's POST /api/ask/stream (Server-Sent
 * Events, one `data: {json}\n\n` frame per event). Native fetch + a stream
 * reader rather than EventSource, since EventSource can't send a POST body
 * (the question). Every "token" event is a real piece of the LLM's answer as
 * Ollama generates it — see ml/explainer.py's ask_stream() docstring for why
 * this is safe to show live (the empty-result safety check runs before
 * generation starts, so nothing streamed here is ever a fabrication that
 * needs retracting mid-stream). */
async function postSse(path: string, body: unknown, onEvent: (event: AskStreamEvent) => void): Promise<void> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok || !res.body) {
    const detail = await res.json().catch(() => null);
    throw new Error(`POST ${path} failed: ${res.status} ${detail?.detail ?? res.statusText}`);
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const frames = buffer.split("\n\n");
    buffer = frames.pop() ?? ""; // last piece may be incomplete — keep for next chunk
    for (const frame of frames) {
      const line = frame.split("\n").find((l) => l.startsWith("data: "));
      if (!line) continue;
      onEvent(JSON.parse(line.slice("data: ".length)) as AskStreamEvent);
    }
  }
}

export interface ApiCluster {
  id: string;
  name: string;
  district: string;
  lat: number;
  lon: number;
  dominant_sectors: string;
  source: string;
  confidence: string;
  factory_count: number;
  open_anomaly_count: number;
}

export interface ApiRecommendation {
  id: string;
  equipment_id: string;
  intervention_key: string;
  title: string;
  category: string;
  capex_inr: number;
  annual_saving_inr: number;
  co2_reduction_tpy: number;
  payback_months: number;
  confidence: "high" | "medium" | "low";
  description: string;
  circularity_gain_pct: number | null;
  rank: number;
}

export interface ApiEquipment {
  id: string;
  process_id: string;
  label: string;
  kind: string;
  share_of_energy: number;
  benchmark_kgco2e_per_t: number;
  benchmark_source: string;
  benchmark_confidence: string;
  co2e_tpy: number | null;
  share_of_total: number | null;
  actual_intensity: number | null;
  severity: "ok" | "warn" | "crit" | null;
  root_cause_text: string | null;
  recommendations: ApiRecommendation[];
}

export interface ApiLeakAssessment {
  id: number;
  factory_id: string;
  kind: "compressed_air" | "refrigerant";
  method: string;
  inputs: Record<string, unknown>;
  leak_rate_pct: number;
  co2e_tpy: number;
  cost_inr_per_year: number;
  note: string;
  created_at: string;
}

export interface ApiWaterBenchmark {
  factory_id: string;
  available: boolean;
  litres_per_kg_submitted: number | null;
  benchmark_low_litres_per_kg: number | null;
  benchmark_high_litres_per_kg: number | null;
  deviation_note: string | null;
  source: string;
}

export interface ApiCrossProcessInsight {
  finding: string;
  equipment_a: string;
  equipment_b: string;
  note: string;
}

export interface ApiFactory {
  id: string;
  name: string;
  cluster_id: string;
  sector: string;
  district: string;
  lat: number;
  lon: number;
  data_source: string;
  consent_to_share: boolean;
  output_tonnes_per_year: number | null;
  total_co2e_tpy: number;
  total_energy_mwh_per_year: number;
  total_waste_tpy: number;
  circularity_ratio: number;
  avoidable_co2e_tpy: number;
  carbon_credit_value_inr_per_year: number;
  carbon_credit_is_placeholder: boolean;
  carbon_credit_note: string;
  equipment: ApiEquipment[];
  anomaly_check_status?: string;
  worker_exposure_flags?: string[];
}

export interface ApiAnomaly {
  id: number;
  equipment_id: string;
  month: string;
  co2e_t: number;
  z_score: number;
  status: string;
}

export interface ApiScaleProjection {
  factory_count: number;
  projected_total_co2e_tpy: number;
  projected_avoidable_co2e_tpy: number;
  projected_carbon_credit_value_inr: number;
  sample_factory_count: number;
  sample_avg_co2e_tpy: number;
  sample_avg_avoidable_co2e_tpy: number;
  methodology: string;
}

export interface ApiAskResult {
  answer: string;
  verified_data: Record<string, unknown> | null;
  source: string;
}

export interface ApiSymbiosisMatch {
  id: number;
  provider_factory_id: string;
  provider_factory_name: string | null;
  recipient_factory_id: string;
  recipient_factory_name: string | null;
  waste_tag: string;
  quantity_tpy: number;
  distance_km: number;
  semantic_score: number;
  quantity_fit_score: number;
  proximity_score: number;
  overall_score: number;
  co2_avoided_tpy: number;
  provider_saving_inr: number;
  recipient_saving_inr: number;
  is_placeholder: boolean;
}

async function patchJson<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => null);
    throw new Error(`PATCH ${path} failed: ${res.status} ${detail?.detail ?? res.statusText}`);
  }
  return res.json() as Promise<T>;
}

// --- Business-feature layer types (organizations, usage, consent, vendors,
// BRSR export, public API keys) — see backend/app/routers/business.py -------

export interface ApiOrganization {
  id: string;
  name: string;
  tier: "free" | "pro";
  brand_color: string;
  logo_text: string;
  factory_count: number;
}

export interface ApiUsageSummary {
  organization_id: string | null;
  tier: string;
  period: string;
  counts: Record<string, number>;
  free_limits: Record<string, number>;
  note: string;
}

export interface ApiConsentRow {
  factory_id: string;
  factory_name: string;
  data_source: string;
  consent_to_share: boolean;
  consent_updated_at: string;
  visible_to_regulator: boolean;
}

export interface ApiVendorContact {
  id: number;
  category: string;
  name: string;
  contact_email: string;
  phone: string;
  region: string;
  notes: string;
}

export interface ApiBrsrReport {
  factory_id: string;
  factory_name: string;
  reporting_period: string;
  principles: { principle: string; title: string; disclosures: { disclosure: string; value: number | string | null; source: string }[] }[];
  methodology_note: string;
}

export interface ApiKeyResult {
  key: string;
  organization_id: string | null;
  label: string;
  rate_limit_per_min: number;
  created_at: string;
}

export interface ApiFactorySummaryLite {
  id: string;
  name: string;
  cluster_id: string;
  sector: string;
  lat: number;
  lon: number;
  data_source: string;
  total_co2e_tpy: number;
  worst_severity: "ok" | "warn" | "crit";
  anomaly_check_status: string;
  organization_id: string | null;
}

export interface ApiLoginResult {
  token: string;
  user: { id: string; email: string; role: "sme" | "consultant" | "regulator"; organization_id: string | null };
}

export const api = {
  // Real session auth (backend/app/auth.py)
  login: (email: string, password: string) => postJson<ApiLoginResult>("/api/auth/login", { email, password }),
  me: () => getJson<ApiLoginResult["user"]>("/api/auth/me"),

  clusters: () => getJson<ApiCluster[]>("/api/clusters"),
  factories: () => getJson<ApiFactory[]>("/api/factories"),
  factoriesSummary: () => getJson<ApiFactorySummaryLite[]>("/api/factories/summary"),
  factory: (id: string) => getJson<ApiFactory>(`/api/factories/${id}`),
  anomalies: (factoryId: string) => getJson<ApiAnomaly[]>(`/api/factories/${factoryId}/anomalies`),
  symbiosisNetwork: () => getJson<ApiSymbiosisMatch[]>("/api/symbiosis/network"),
  onboardFactory: (payload: unknown) => postJson<{ id: string; total_co2e_t: number; anomaly_check_status: string }>("/api/factories", payload),
  scaleProjection: (factoryCount: number) => getJson<ApiScaleProjection>(`/api/scale-projection?factory_count=${factoryCount}`),
  ask: (question: string, factoryId?: string | null) =>
    postJson<ApiAskResult>("/api/ask", { question, factory_id: factoryId ?? null }),
  askStream: (question: string, factoryId: string | null, onEvent: (event: AskStreamEvent) => void) =>
    postSse("/api/ask/stream", { question, factory_id: factoryId ?? null }, onEvent),

  // Organizations / white-labeling
  organizations: () => getJson<ApiOrganization[]>("/api/organizations"),
  createOrganization: (name: string, brandColor = "#3ea6ff", logoText = "") =>
    postJson<ApiOrganization>("/api/organizations", { name, brand_color: brandColor, logo_text: logoText }),
  setOrganizationTier: (orgId: string, tier: "free" | "pro") =>
    patchJson<ApiOrganization>(`/api/organizations/${orgId}/tier`, { tier }),
  assignFactoryOrganization: (factoryId: string, organizationId: string | null) =>
    patchJson<ApiFactorySummaryLite>(`/api/factories/${factoryId}/organization`, { organization_id: organizationId }),

  // Usage metering
  trackUsage: (kind: "report_generated" | "chat_question" | "factory_onboarded", organizationId?: string | null, factoryId?: string | null) =>
    postJson<{ status: string }>("/api/usage/track", { kind, organization_id: organizationId ?? null, factory_id: factoryId ?? null }),
  usageSummary: (organizationId?: string | null) =>
    getJson<ApiUsageSummary>(`/api/usage${organizationId ? `?organization_id=${organizationId}` : ""}`),

  // Consent ledger
  consentLedger: () => getJson<ApiConsentRow[]>("/api/consent-ledger"),
  setFactoryConsent: (factoryId: string, consent: boolean) =>
    patchJson<ApiConsentRow>(`/api/factories/${factoryId}/consent`, { consent_to_share: consent }),

  // Vendor directory
  vendors: (category?: string) => getJson<ApiVendorContact[]>(`/api/vendors${category ? `?category=${category}` : ""}`),

  // BRSR export
  brsrReport: (factoryId: string) => getJson<ApiBrsrReport>(`/api/factories/${factoryId}/brsr-report`),

  // Public API tier
  createApiKey: (orgId: string, label = "") => postJson<ApiKeyResult>(`/api/organizations/${orgId}/api-keys`, { label }),

  // CSV bulk importers — the "dark data" closer: upload the bill/log you
  // already have instead of retyping it field by field.
  activityCsvTemplateUrl: () => `${API_BASE}/api/csv-templates/activity`,
  leakAssessmentsCsvTemplateUrl: () => `${API_BASE}/api/csv-templates/leak-assessments`,
  importActivityCsv: async (factoryId: string, file: File) => {
    const body = new FormData();
    body.append("file", file);
    const res = await fetch(`${API_BASE}/api/factories/${factoryId}/activity/csv`, { method: "POST", body });
    if (!res.ok) {
      const detail = await res.json().catch(() => null);
      throw new Error(detail?.detail ?? `Upload failed: ${res.status}`);
    }
    return res.json();
  },
  importLeakAssessmentsCsv: async (factoryId: string, file: File) => {
    const body = new FormData();
    body.append("file", file);
    const res = await fetch(`${API_BASE}/api/factories/${factoryId}/leak-assessments/csv`, { method: "POST", body });
    if (!res.ok) {
      const detail = await res.json().catch(() => null);
      throw new Error(detail?.detail ?? `Upload failed: ${res.status}`);
    }
    return res.json() as Promise<ApiLeakAssessment[]>;
  },

  // Leak diagnostics (compressed air / refrigerant / water / cross-process)
  leakAssessments: (factoryId: string) => getJson<ApiLeakAssessment[]>(`/api/factories/${factoryId}/leak-assessments`),
  compressedAirLoadUnloadTest: (factoryId: string, body: {
    rated_capacity_cfm: number; load_time_min: number; unload_time_min: number;
    operating_hours_per_year: number; electricity_rate_inr_per_kwh: number; specific_power_kw_per_100cfm?: number;
  }) => postJson<ApiLeakAssessment>(`/api/factories/${factoryId}/leak-assessments/compressed-air/load-unload-test`, body),
  compressedAirUnauditedEstimate: (factoryId: string, body: {
    rated_capacity_cfm: number; operating_hours_per_year: number; electricity_rate_inr_per_kwh: number; specific_power_kw_per_100cfm?: number;
  }) => postJson<ApiLeakAssessment>(`/api/factories/${factoryId}/leak-assessments/compressed-air/unaudited-estimate`, body),
  refrigerantLeak: (factoryId: string, body: {
    refrigerant_key: string; nameplate_charge_kg: number; annual_topup_kg: number; refrigerant_cost_inr_per_kg: number;
  }) => postJson<ApiLeakAssessment>(`/api/factories/${factoryId}/leak-assessments/refrigerant`, body),
  waterBenchmark: (factoryId: string, litresPerKg?: number) =>
    getJson<ApiWaterBenchmark>(`/api/factories/${factoryId}/water-benchmark${litresPerKg != null ? `?litres_per_kg=${litresPerKg}` : ""}`),
  crossProcessInsights: (factoryId: string) => getJson<ApiCrossProcessInsight[]>(`/api/factories/${factoryId}/cross-process-insights`),
};
