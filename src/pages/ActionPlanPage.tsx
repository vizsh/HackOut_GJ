import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { motion } from "framer-motion";
import { useFactoryStore } from "../store/useFactoryStore";
import { buildActionPlan, planToMarkdown, type PlanItem, type PhaseSummary } from "../lib/actionplan";
import { formatInr, severityColor, confidenceLabel } from "../lib/severity";
import { api, type ApiVendorContact } from "../lib/api";

// "Apply" persists Recommendation.applied on the backend (see
// backend/app/routers/factories.py set_recommendation_applied) — distinct
// from picking a scenario in the Simulate page, which is an ephemeral
// what-if that never writes anything. Applying a circularity-tagged
// intervention (recycling-loop / waste-to-input / material-substitution)
// is what actually moves the factory's circularity_ratio off 0.

const phaseAccent: Record<PhaseSummary["phase"], string> = { "30": "#22c55e", "90": "#3ea6ff", "365": "#a78bfa" };

function VendorFinder({ category }: { category: string }) {
  const [open, setOpen] = useState(false);
  const [vendors, setVendors] = useState<ApiVendorContact[] | null>(null);

  const toggle = () => {
    setOpen((o) => !o);
    if (!vendors) api.vendors(category).then(setVendors).catch(() => setVendors([]));
  };

  return (
    <div className="mt-2 border-t border-[color:var(--color-border)] pt-2">
      <button onClick={toggle} className="text-[11px] text-[color:var(--color-accent)] hover:underline">
        {open ? "Hide vendors ▲" : "Find a vendor →"}
      </button>
      {open && (
        <div className="mt-1.5 space-y-1.5">
          {vendors === null ? (
            <div className="text-[10px] text-[color:var(--color-muted)]">Loading…</div>
          ) : vendors.length === 0 ? (
            <div className="text-[10px] text-[color:var(--color-muted)]">No vendor contacts on file for this category yet.</div>
          ) : vendors.map((v) => (
            <div key={v.id} className="rounded-md border border-[color:var(--color-border)] bg-[color:var(--color-panel)] p-2 text-[10px]">
              <div className="font-semibold">{v.name} <span className="font-normal text-[color:var(--color-muted)]">· {v.region}</span></div>
              <div className="text-[color:var(--color-muted)]">{v.contact_email} · {v.phone}</div>
              <div className="mt-0.5 italic text-[color:var(--color-muted)]">{v.notes}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function ItemCard({ item, accent, factoryId, onApplied }: {
  item: PlanItem; accent: string; factoryId: string; onApplied: () => void;
}) {
  const iv = item.intervention;
  const [busy, setBusy] = useState(false);
  const isCircular = iv.circularityGainPct != null && iv.circularityGainPct > 0;

  const toggleApplied = async () => {
    if (!factoryId || busy) return;
    setBusy(true);
    try {
      await api.applyRecommendation(factoryId, iv.id, !iv.applied);
      onApplied();
    } catch {
      /* surfaced implicitly — the button just stays in its current state */
    } finally {
      setBusy(false);
    }
  };

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      className="rounded-lg border border-[color:var(--color-border)] bg-[color:var(--color-panel-2)] p-3"
    >
      <div className="flex items-start gap-2.5">
        <div className="flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-full text-[11px] font-bold text-black" style={{ background: accent }}>
          {item.priority}
        </div>
        <div className="min-w-0 flex-1">
          <div className="text-[13px] font-medium leading-snug">{iv.title}</div>
          <div className="mt-0.5 flex items-center gap-1.5 text-[11px] text-[color:var(--color-muted)]">
            <span className="h-1.5 w-1.5 rounded-full" style={{ background: severityColor[item.process.severity] }} />
            {item.process.label} · {iv.category.replace(/-/g, " ")}
          </div>
        </div>
        <button
          onClick={toggleApplied}
          disabled={busy}
          title={isCircular ? `Applying this raises circularity ratio by ${Math.round((iv.circularityGainPct ?? 0) * 100)}pp` : "Mark this intervention as actually implemented"}
          className={`shrink-0 rounded-md border px-2 py-1 text-[10px] font-medium disabled:opacity-50 ${
            iv.applied
              ? "border-[color:var(--color-ok)] bg-[color:var(--color-ok)]/15 text-[color:var(--color-ok)]"
              : "border-[color:var(--color-border)] text-[color:var(--color-muted)] hover:bg-[color:var(--color-panel)]"
          }`}
        >
          {busy ? "…" : iv.applied ? "Applied ✓" : "Mark applied"}
        </button>
      </div>

      <div className="mt-2.5 grid grid-cols-4 gap-1.5 text-center">
        {[
          ["CAPEX", formatInr(iv.capexInr)],
          ["Saving/yr", formatInr(iv.annualSavingInr)],
          ["CO₂ cut", `${iv.co2ReductionTpy} t`],
          ["Payback", `${iv.paybackMonths} mo`],
        ].map(([k, v]) => (
          <div key={k} className="rounded border border-[color:var(--color-border)] px-1 py-1">
            <div className="text-[9px] uppercase tracking-wide text-[color:var(--color-muted)]">{k}</div>
            <div className="text-[11px] font-semibold">{v}</div>
          </div>
        ))}
      </div>

      <dl className="mt-2.5 space-y-1 text-[11px]">
        <div className="flex gap-2">
          <dt className="w-20 flex-shrink-0 text-[color:var(--color-muted)]">Owner</dt>
          <dd>{item.owner}</dd>
        </div>
        <div className="flex gap-2">
          <dt className="w-20 flex-shrink-0 text-[color:var(--color-muted)]">Prerequisite</dt>
          <dd>{item.prerequisite ?? "None — can start immediately"}</dd>
        </div>
        <div className="flex gap-2">
          <dt className="w-20 flex-shrink-0 text-[color:var(--color-muted)]">Confidence</dt>
          <dd>{confidenceLabel[iv.confidence]}</dd>
        </div>
      </dl>
      <VendorFinder category={iv.category} />
    </motion.div>
  );
}

export default function ActionPlanPage() {
  const baseline = useFactoryStore((s) => s.baseline);
  const selected = useFactoryStore((s) => s.selectedInterventionIds);
  const refreshFactoryFromApi = useFactoryStore((s) => s.refreshFactoryFromApi);
  const plan = useMemo(() => buildActionPlan(baseline, selected), [baseline, selected]);
  const [copied, setCopied] = useState(false);
  const onApplied = () => { if (baseline.id) refreshFactoryFromApi(baseline.id); };

  const copyMarkdown = async () => {
    try {
      await navigator.clipboard.writeText(planToMarkdown(baseline, plan));
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    } catch {
      /* clipboard unavailable — ignore */
    }
  };

  const maxCum = plan.cumulative[plan.cumulative.length - 1]?.co2ReductionTpy || 1;

  return (
    <main className="flex flex-1 flex-col gap-3 overflow-hidden p-4 print:overflow-visible">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-base font-semibold">Costed action plan</h2>
          <p className="text-[12px] text-[color:var(--color-muted)]">
            {plan.usingAllRecommended ? (
              <>
                Showing all recommended interventions.{" "}
                <Link to="/simulate" className="text-[color:var(--color-accent)] hover:underline">
                  Pick a scenario in the simulator
                </Link>{" "}
                to plan only what you intend to fund.
              </>
            ) : (
              <>Built from your simulator scenario ({selected.size} interventions). Phased by payback and CAPEX; prioritised by tCO₂e per ₹ lakh.</>
            )}
          </p>
        </div>
        <div className="flex gap-2 print:hidden">
          <button onClick={copyMarkdown} className="rounded-lg border border-[color:var(--color-border)] px-3 py-1.5 text-xs hover:bg-[color:var(--color-panel-2)]">
            {copied ? "Copied ✓" : "Copy as Markdown"}
          </button>
          <button onClick={() => window.print()} className="rounded-lg border border-[color:var(--color-border)] bg-[color:var(--color-accent)]/15 px-3 py-1.5 text-xs text-[color:var(--color-accent)] hover:bg-[color:var(--color-accent)]/25">
            Print / PDF
          </button>
        </div>
      </div>

      {/* totals + cumulative strip */}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-[1fr_1fr_1fr_1fr_2fr]">
        {[
          ["Total CAPEX", formatInr(plan.totals.capexInr)],
          ["Annual saving", formatInr(plan.totals.annualSavingInr)],
          ["CO₂e avoided / yr", `${plan.totals.co2ReductionTpy.toLocaleString("en-IN")} t`],
          ["Blended payback", plan.totals.paybackMonths === null ? "—" : `${plan.totals.paybackMonths} mo`],
        ].map(([k, v]) => (
          <div key={k} className="glass rounded-xl px-4 py-3">
            <div className="text-[11px] uppercase tracking-wide text-[color:var(--color-muted)]">{k}</div>
            <div className="text-lg font-semibold">{v}</div>
          </div>
        ))}
        <div className="glass col-span-2 rounded-xl px-4 py-3 lg:col-span-1">
          <div className="text-[11px] uppercase tracking-wide text-[color:var(--color-muted)]">Cumulative CO₂e avoided by phase</div>
          <div className="mt-2 flex items-end gap-2">
            {plan.cumulative.map((c) => (
              <div key={c.phase} className="flex flex-1 flex-col items-center gap-1">
                <div className="text-[11px] font-semibold">{c.co2ReductionTpy.toLocaleString("en-IN")} t</div>
                <div className="h-8 w-full overflow-hidden rounded bg-[color:var(--color-panel-2)]">
                  <div
                    className="h-full transition-[width] duration-500"
                    style={{ background: phaseAccent[c.phase], width: `${(c.co2ReductionTpy / maxCum) * 100}%` }}
                  />
                </div>
                <div className="text-[10px] text-[color:var(--color-muted)]">{c.phase === "365" ? "12 mo" : `${c.phase} d`}</div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* three phase columns */}
      <div className="grid flex-1 grid-cols-1 gap-3 overflow-hidden lg:grid-cols-3 print:overflow-visible">
        {plan.phases.map((p) => (
          <div key={p.phase} className="glass flex flex-col overflow-hidden rounded-xl">
            <div className="border-b border-[color:var(--color-border)] px-4 py-3" style={{ borderTop: `3px solid ${phaseAccent[p.phase]}` }}>
              <div className="flex items-baseline justify-between">
                <h3 className="text-sm font-semibold">{p.label}</h3>
                <span className="text-[11px] text-[color:var(--color-muted)]">{p.items.length} action{p.items.length === 1 ? "" : "s"}</span>
              </div>
              <div className="text-[11px] text-[color:var(--color-muted)]">{p.window}</div>
              <div className="mt-2 grid grid-cols-3 gap-1 text-center text-[11px]">
                <div><span className="text-[color:var(--color-muted)]">CAPEX </span><b>{formatInr(p.capexInr)}</b></div>
                <div><span className="text-[color:var(--color-muted)]">Save </span><b className="text-[color:var(--color-ok)]">{formatInr(p.annualSavingInr)}</b></div>
                <div><span className="text-[color:var(--color-muted)]">CO₂ </span><b>{p.co2ReductionTpy} t</b></div>
              </div>
            </div>
            <div className="flex flex-1 flex-col gap-2 overflow-y-auto p-3">
              {p.items.length === 0 ? (
                <div className="flex flex-1 items-center justify-center p-6 text-center text-[12px] text-[color:var(--color-muted)]">
                  Nothing phased here for this scenario.
                </div>
              ) : (
                p.items.map((it) => <ItemCard key={it.intervention.id} item={it} accent={phaseAccent[p.phase]} factoryId={baseline.id} onApplied={onApplied} />)
              )}
            </div>
          </div>
        ))}
      </div>

      <div className="text-[10px] text-[color:var(--color-muted)]">
        Modelled estimates calibrated to public sector statistics and Indian emission factors — not measured plant data. Phasing rule: 30-day = payback ≤ 6 mo or CAPEX &lt; ₹5 L; 90-day = payback ≤ 18 mo; else 6–12 month.
      </div>
    </main>
  );
}
