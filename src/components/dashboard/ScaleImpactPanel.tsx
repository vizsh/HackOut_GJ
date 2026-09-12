import { useEffect, useState } from "react";
import CountUp from "../simulator/CountUp";
import { formatInr } from "../../lib/severity";
import { api, type ApiScaleProjection } from "../../lib/api";

// "If this scaled to N factories" — a real linear extrapolation from the
// 120-factory dataset (GET /api/scale-projection), not a hardcoded headline
// number. The methodology string always ships with the number (see
// backend/app/routers/catalog.py) so this component never separates the
// two — that's the whole point of building it as a real endpoint instead of
// a static "5,000 factories × big number" slide.

const PRESETS = [500, 1000, 2500, 5000, 10000];

export default function ScaleImpactPanel({ defaultCollapsed = false }: { defaultCollapsed?: boolean }) {
  const [factoryCount, setFactoryCount] = useState(5000);
  const [projection, setProjection] = useState<ApiScaleProjection | null>(null);
  const [showMethodology, setShowMethodology] = useState(false);
  const [collapsed, setCollapsed] = useState(defaultCollapsed);

  useEffect(() => {
    let cancelled = false;
    const handle = setTimeout(() => {
      api.scaleProjection(factoryCount).then((p) => {
        if (!cancelled) setProjection(p);
      }).catch(() => {});
    }, 150); // debounce the slider
    return () => { cancelled = true; clearTimeout(handle); };
  }, [factoryCount]);

  return (
    <div className="glass rounded-xl p-4">
      <button onClick={() => setCollapsed((v) => !v)} className="flex w-full flex-wrap items-start justify-between gap-3 text-left">
        <div>
          <h3 className="flex items-center gap-1.5 text-sm font-semibold">
            <span className={`inline-block transition-transform ${collapsed ? "-rotate-90" : ""}`}>▾</span>
            If this scaled across Gujarat
          </h3>
          {!collapsed && (
            <p className="text-[11px] text-[color:var(--color-muted)]">
              Linear extrapolation from the real 120-factory cohort — not a fixed slide number. Drag the slider.
            </p>
          )}
        </div>
        {collapsed && projection && (
          <div className="flex gap-3 text-[11px]">
            <span>{factoryCount.toLocaleString("en-IN")} factories</span>
            <span className="text-[color:var(--color-ok)]">{Math.round(projection.projected_avoidable_co2e_tpy).toLocaleString("en-IN")} t avoidable</span>
          </div>
        )}
      </button>
      {collapsed ? null : (
      <>
      <div className="mt-2 flex justify-end gap-1">
        {PRESETS.map((p) => (
          <button
            key={p}
            onClick={() => setFactoryCount(p)}
            className={`rounded-full border px-2 py-1 text-[10px] ${factoryCount === p ? "border-[color:var(--color-accent)] bg-[color:var(--color-accent)]/15 text-[color:var(--color-accent)]" : "border-[color:var(--color-border)] text-[color:var(--color-muted)]"}`}
          >
            {p.toLocaleString("en-IN")}
          </button>
        ))}
      </div>

      <input
        type="range"
        min={100}
        max={10000}
        step={100}
        value={factoryCount}
        onChange={(e) => setFactoryCount(Number(e.target.value))}
        className="mt-3 w-full accent-[color:var(--color-accent)]"
      />
      <div className="mt-1 text-center text-[11px] text-[color:var(--color-muted)]">
        {factoryCount.toLocaleString("en-IN")} factories
      </div>

      <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-3">
        <div className="rounded-lg border border-[color:var(--color-border)] p-3 text-center">
          <div className="text-[10px] uppercase tracking-wide text-[color:var(--color-muted)]">CO₂e / yr</div>
          <div className="text-xl font-bold text-[color:var(--color-text)]">
            <CountUp value={projection?.projected_total_co2e_tpy ?? 0} format={(n) => Math.round(n).toLocaleString("en-IN")} />
            <span className="ml-1 text-xs font-normal text-[color:var(--color-muted)]">t</span>
          </div>
        </div>
        <div className="rounded-lg border border-[color:var(--color-ok)]/40 bg-[color:var(--color-ok)]/5 p-3 text-center">
          <div className="text-[10px] uppercase tracking-wide text-[color:var(--color-muted)]">Avoidable CO₂e / yr</div>
          <div className="text-xl font-bold text-[color:var(--color-ok)]">
            <CountUp value={projection?.projected_avoidable_co2e_tpy ?? 0} format={(n) => Math.round(n).toLocaleString("en-IN")} />
            <span className="ml-1 text-xs font-normal text-[color:var(--color-muted)]">t</span>
          </div>
        </div>
        <div className="rounded-lg border border-[color:var(--color-accent)]/40 bg-[color:var(--color-accent)]/5 p-3 text-center">
          <div className="flex items-center justify-center gap-1 text-[10px] uppercase tracking-wide text-[color:var(--color-muted)]">
            Carbon-credit value / yr
            <span className="rounded-full border border-[color:var(--color-warn)]/50 px-1 text-[8px] text-[color:var(--color-warn)]">screening</span>
          </div>
          <div className="text-xl font-bold text-[color:var(--color-accent)]">
            <CountUp value={projection?.projected_carbon_credit_value_inr ?? 0} format={(n) => formatInr(n)} />
          </div>
        </div>
      </div>

      <button onClick={() => setShowMethodology((v) => !v)} className="mt-2 text-[10px] text-[color:var(--color-muted)] underline decoration-dotted">
        {showMethodology ? "Hide" : "Show"} methodology
      </button>
      {showMethodology && projection && (
        <p className="mt-1 rounded-lg border border-[color:var(--color-border)] bg-[color:var(--color-panel-2)] p-2 text-[10px] leading-relaxed text-[color:var(--color-muted)]">
          {projection.methodology}
        </p>
      )}
      </>
      )}
    </div>
  );
}
