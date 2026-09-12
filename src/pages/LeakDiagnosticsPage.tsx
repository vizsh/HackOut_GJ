import { useEffect, useState } from "react";
import { useFactoryStore } from "../store/useFactoryStore";
import { api, type ApiLeakAssessment, type ApiWaterBenchmark, type ApiCrossProcessInsight } from "../lib/api";
import { formatInr } from "../lib/severity";

// Motivated directly by the HackOut'26 research doc "Industrial Emission
// Leak-Point Detector": compressed-air and refrigerant leaks are computable
// from data a plant already has on invoices/nameplates — no new sensor
// hardware. See backend/app/intelligence/leak_estimators.py for the sourced
// formulas behind every number this page shows.

const REFRIGERANTS = [
  { key: "r22", label: "R-22 (HCFC-22)" },
  { key: "r134a", label: "R-134a" },
  { key: "r404a", label: "R-404A" },
  { key: "r407c", label: "R-407C" },
  { key: "r410a", label: "R-410A" },
  { key: "r717_ammonia", label: "R-717 (Ammonia)" },
  { key: "r744_co2", label: "R-744 (CO2)" },
];

function Card({ title, subtitle, children }: { title: string; subtitle: string; children: React.ReactNode }) {
  return (
    <section className="glass rounded-xl p-4">
      <h3 className="text-sm font-semibold">{title}</h3>
      <p className="mt-0.5 text-[11px] text-[color:var(--color-muted)]">{subtitle}</p>
      <div className="mt-3">{children}</div>
    </section>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="text-[10px] uppercase tracking-wide text-[color:var(--color-muted)]">
      {label}
      <span className="mt-1 block [&_input]:w-full [&_input]:rounded-md [&_input]:border [&_input]:border-[color:var(--color-border)] [&_input]:bg-[color:var(--color-panel-2)] [&_input]:p-2 [&_input]:text-sm [&_input]:text-[color:var(--color-text)] [&_select]:w-full [&_select]:rounded-md [&_select]:border [&_select]:border-[color:var(--color-border)] [&_select]:bg-[color:var(--color-panel-2)] [&_select]:p-2 [&_select]:text-sm [&_select]:text-[color:var(--color-text)]">
        {children}
      </span>
    </label>
  );
}

function CsvImportRow({ label, templateUrl, onUpload, disabled }: {
  label: string; templateUrl: string; onUpload: (file: File) => Promise<void>; disabled: boolean;
}) {
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const handleFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = ""; // allow re-selecting the same file
    if (!file) return;
    setBusy(true);
    setMessage(null);
    try {
      await onUpload(file);
      setMessage("Imported ✓");
    } catch (err) {
      setMessage(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex flex-wrap items-center gap-2 text-[11px]">
      <span className="w-40 shrink-0 font-medium">{label}</span>
      <a href={templateUrl} download className="rounded-md border border-[color:var(--color-border)] px-2 py-1 hover:bg-[color:var(--color-panel-2)]">
        Download template
      </a>
      <label className={`rounded-md border border-[color:var(--color-accent)]/50 px-2 py-1 text-[color:var(--color-accent)] hover:bg-[color:var(--color-accent)]/10 ${disabled || busy ? "pointer-events-none opacity-50" : "cursor-pointer"}`}>
        {busy ? "Uploading…" : "Upload CSV"}
        <input type="file" accept=".csv,text/csv" className="hidden" onChange={handleFile} disabled={disabled || busy} />
      </label>
      {message && <span className={message === "Imported ✓" ? "text-[color:var(--color-ok)]" : "text-[color:var(--color-crit)]"}>{message}</span>}
    </div>
  );
}

function ResultCard({ r }: { r: ApiLeakAssessment }) {
  return (
    <div className="rounded-lg border border-[color:var(--color-accent)]/40 bg-[color:var(--color-accent)]/5 p-3 text-[12px]">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <span className="font-semibold">{r.kind === "compressed_air" ? "Compressed-air leak" : "Refrigerant leak"} — {r.leak_rate_pct.toFixed(1)}%</span>
        <span className="text-[10px] text-[color:var(--color-muted)]">{new Date(r.created_at).toLocaleString("en-IN")}</span>
      </div>
      <div className="mt-1.5 grid grid-cols-2 gap-2 sm:grid-cols-2">
        <div><div className="text-[9px] text-[color:var(--color-muted)]">CO₂e / yr</div><div className="font-semibold">{r.co2e_tpy.toLocaleString("en-IN")} t</div></div>
        <div><div className="text-[9px] text-[color:var(--color-muted)]">Cost / yr</div><div className="font-semibold">{formatInr(r.cost_inr_per_year)}</div></div>
      </div>
      <p className="mt-2 text-[11px] italic text-[color:var(--color-muted)]">{r.note}</p>
    </div>
  );
}

export default function LeakDiagnosticsPage() {
  const factory = useFactoryStore((s) => s.baseline);
  const [history, setHistory] = useState<ApiLeakAssessment[]>([]);
  const [workerFlags, setWorkerFlags] = useState<string[]>([]);
  const [waterBench, setWaterBench] = useState<ApiWaterBenchmark | null>(null);
  const [insights, setInsights] = useState<ApiCrossProcessInsight[]>([]);
  const [error, setError] = useState<string | null>(null);

  // Compressed-air form state
  const [caMode, setCaMode] = useState<"load_unload" | "unaudited">("load_unload");
  const [caCfm, setCaCfm] = useState(500);
  const [caLoadMin, setCaLoadMin] = useState(3);
  const [caUnloadMin, setCaUnloadMin] = useState(7);
  const [caHours, setCaHours] = useState(6000);
  const [caRate, setCaRate] = useState(8);
  const [caBusy, setCaBusy] = useState(false);
  const [caResult, setCaResult] = useState<ApiLeakAssessment | null>(null);

  // Refrigerant form state
  const [refKey, setRefKey] = useState("r404a");
  const [refCharge, setRefCharge] = useState(1000);
  const [refTopup, setRefTopup] = useState(142);
  const [refCost, setRefCost] = useState(1200);
  const [refBusy, setRefBusy] = useState(false);
  const [refResult, setRefResult] = useState<ApiLeakAssessment | null>(null);

  // Water benchmark form state
  const [litresPerKg, setLitresPerKg] = useState(160);

  const reload = () => {
    if (!factory.id) return;
    api.leakAssessments(factory.id).then(setHistory).catch(() => {});
    api.factory(factory.id).then((f) => setWorkerFlags(f.worker_exposure_flags ?? [])).catch(() => {});
    api.crossProcessInsights(factory.id).then(setInsights).catch(() => {});
    api.waterBenchmark(factory.id).then(setWaterBench).catch(() => {});
  };
  useEffect(reload, [factory.id]);

  const submitCompressedAir = async () => {
    setCaBusy(true);
    setError(null);
    try {
      const r = caMode === "load_unload"
        ? await api.compressedAirLoadUnloadTest(factory.id, {
            rated_capacity_cfm: caCfm, load_time_min: caLoadMin, unload_time_min: caUnloadMin,
            operating_hours_per_year: caHours, electricity_rate_inr_per_kwh: caRate,
          })
        : await api.compressedAirUnauditedEstimate(factory.id, {
            rated_capacity_cfm: caCfm, operating_hours_per_year: caHours, electricity_rate_inr_per_kwh: caRate,
          });
      setCaResult(r);
      reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setCaBusy(false);
    }
  };

  const submitRefrigerant = async () => {
    setRefBusy(true);
    setError(null);
    try {
      const r = await api.refrigerantLeak(factory.id, {
        refrigerant_key: refKey, nameplate_charge_kg: refCharge, annual_topup_kg: refTopup, refrigerant_cost_inr_per_kg: refCost,
      });
      setRefResult(r);
      reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setRefBusy(false);
    }
  };

  const checkWater = async () => {
    try {
      setWaterBench(await api.waterBenchmark(factory.id, litresPerKg));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <main className="flex flex-1 flex-col gap-3 overflow-y-auto p-4">
      <div>
        <h2 className="text-base font-semibold">Leak diagnostics</h2>
        <p className="text-[12px] text-[color:var(--color-muted)]">
          Compressed-air and refrigerant leak estimates computed from invoice/nameplate data you already
          have — no new sensor hardware. For <b>{factory.name}</b>.
        </p>
      </div>

      {error && <p className="text-[12px] text-[color:var(--color-crit)]">{error}</p>}

      <Card title="Bulk import from CSV" subtitle="Already have a utility bill, a compressor load/unload log, or a year of refrigerant top-up invoices? Upload the whole file instead of retyping it row by row.">
        <div className="space-y-2">
          <CsvImportRow
            label="Monthly activity"
            templateUrl={api.activityCsvTemplateUrl()}
            disabled={!factory.id}
            onUpload={async (file) => { await api.importActivityCsv(factory.id, file); reload(); }}
          />
          <CsvImportRow
            label="Leak assessments"
            templateUrl={api.leakAssessmentsCsvTemplateUrl()}
            disabled={!factory.id}
            onUpload={async (file) => { await api.importLeakAssessmentsCsv(factory.id, file); reload(); }}
          />
        </div>
      </Card>

      {workerFlags.length > 0 && (
        <section className="glass rounded-xl border border-[color:var(--color-warn)]/40 p-4">
          <h3 className="text-sm font-semibold text-[color:var(--color-warn)]">Worker exposure risk flags</h3>
          <p className="mt-0.5 text-[11px] text-[color:var(--color-muted)]">Keyword heuristic on process labels, not a measured exposure reading.</p>
          <ul className="mt-2 space-y-1 text-[11px]">
            {workerFlags.map((f) => <li key={f}>⚠ {f}</li>)}
          </ul>
        </section>
      )}

      <div className="grid gap-3 lg:grid-cols-2">
        <Card title="Compressed-air leak estimator" subtitle="DOE / Compressed Air Challenge load-unload test method, or an unaudited-range fallback.">
          <div className="mb-2 flex gap-2 text-[11px]">
            <button onClick={() => setCaMode("load_unload")} className={`rounded-md border px-2 py-1 ${caMode === "load_unload" ? "border-[color:var(--color-accent)] text-[color:var(--color-accent)]" : "border-[color:var(--color-border)]"}`}>Load/unload test</button>
            <button onClick={() => setCaMode("unaudited")} className={`rounded-md border px-2 py-1 ${caMode === "unaudited" ? "border-[color:var(--color-accent)] text-[color:var(--color-accent)]" : "border-[color:var(--color-border)]"}`}>No timing data (estimate)</button>
          </div>
          <div className="grid grid-cols-2 gap-2">
            <Field label="Rated capacity (cfm)"><input type="number" value={caCfm} onChange={(e) => setCaCfm(Number(e.target.value))} /></Field>
            <Field label="Operating hours/yr"><input type="number" value={caHours} onChange={(e) => setCaHours(Number(e.target.value))} /></Field>
            {caMode === "load_unload" && (
              <>
                <Field label="Load time / cycle (min)"><input type="number" step="0.1" value={caLoadMin} onChange={(e) => setCaLoadMin(Number(e.target.value))} /></Field>
                <Field label="Unload time / cycle (min)"><input type="number" step="0.1" value={caUnloadMin} onChange={(e) => setCaUnloadMin(Number(e.target.value))} /></Field>
              </>
            )}
            <Field label="Electricity rate (₹/kWh)"><input type="number" step="0.1" value={caRate} onChange={(e) => setCaRate(Number(e.target.value))} /></Field>
          </div>
          <button onClick={submitCompressedAir} disabled={caBusy} className="mt-3 rounded-lg bg-[color:var(--color-accent)] px-3 py-1.5 text-xs font-semibold text-[#07101c] disabled:opacity-50">
            {caBusy ? "Computing…" : "Estimate leak"}
          </button>
          {caResult && <div className="mt-3"><ResultCard r={caResult} /></div>}
        </Card>

        <Card title="Refrigerant leak estimator" subtitle="A top-up is compensation for a continuous leak, not routine maintenance.">
          <div className="grid grid-cols-2 gap-2">
            <Field label="Refrigerant">
              <select value={refKey} onChange={(e) => setRefKey(e.target.value)}>
                {REFRIGERANTS.map((r) => <option key={r.key} value={r.key}>{r.label}</option>)}
              </select>
            </Field>
            <Field label="Nameplate charge (kg)"><input type="number" value={refCharge} onChange={(e) => setRefCharge(Number(e.target.value))} /></Field>
            <Field label="Annual top-up (kg)"><input type="number" value={refTopup} onChange={(e) => setRefTopup(Number(e.target.value))} /></Field>
            <Field label="Refrigerant cost (₹/kg)"><input type="number" value={refCost} onChange={(e) => setRefCost(Number(e.target.value))} /></Field>
          </div>
          <button onClick={submitRefrigerant} disabled={refBusy} className="mt-3 rounded-lg bg-[color:var(--color-accent)] px-3 py-1.5 text-xs font-semibold text-[#07101c] disabled:opacity-50">
            {refBusy ? "Computing…" : "Estimate leak"}
          </button>
          {refResult && <div className="mt-3"><ResultCard r={refResult} /></div>}
        </Card>
      </div>

      <div className="grid gap-3 lg:grid-cols-2">
        <Card title="Water-intensity benchmark" subtitle="Sourced only for textile dyeing/finishing (TERI Tirupur study) — honestly unavailable elsewhere.">
          <div className="flex items-end gap-2">
            <Field label="Litres per kg output"><input type="number" value={litresPerKg} onChange={(e) => setLitresPerKg(Number(e.target.value))} /></Field>
            <button onClick={checkWater} className="rounded-lg border border-[color:var(--color-border)] px-3 py-2 text-xs hover:bg-[color:var(--color-panel-2)]">Check</button>
          </div>
          {waterBench && (
            <div className="mt-3 rounded-lg border border-[color:var(--color-border)] p-3 text-[11px]">
              {waterBench.available ? (
                <>
                  <div>Sourced range: <b>{waterBench.benchmark_low_litres_per_kg}–{waterBench.benchmark_high_litres_per_kg} l/kg</b></div>
                  <div className="mt-1 text-[color:var(--color-muted)]">{waterBench.deviation_note}</div>
                </>
              ) : (
                <div className="italic text-[color:var(--color-muted)]">{waterBench.source}</div>
              )}
            </div>
          )}
        </Card>

        <Card title="Cross-process insights" subtitle="Structural patterns across equipment your per-process diagnosis doesn't check — e.g. a heat source and a heat sink coexisting with no capture link.">
          {insights.length === 0 ? (
            <div className="text-[11px] text-[color:var(--color-muted)]">No heat-source/heat-sink pairing found on this factory's process list.</div>
          ) : (
            <div className="space-y-2">
              {insights.map((i, idx) => (
                <div key={idx} className="rounded-lg border border-[color:var(--color-border)] p-2.5 text-[11px]">
                  <div className="font-medium">{i.equipment_a} → {i.equipment_b}</div>
                  <div className="mt-1 text-[color:var(--color-muted)]">{i.note}</div>
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>

      <Card title="Assessment history" subtitle="Every leak assessment ever run for this factory, persisted.">
        {history.length === 0 ? (
          <div className="text-[11px] text-[color:var(--color-muted)]">No leak assessments recorded yet.</div>
        ) : (
          <div className="space-y-2">
            {history.map((r) => <ResultCard key={r.id} r={r} />)}
          </div>
        )}
      </Card>
    </main>
  );
}
