import { useMemo, useState } from "react";
import ClusterMap from "../components/map/ClusterMap";
import ScaleImpactPanel from "../components/dashboard/ScaleImpactPanel";
import { allFactories } from "../data/factories";
import { rollup, MIN_CELL } from "../lib/rollup";
import { formatInr } from "../lib/severity";
import { useFactoryStore } from "../store/useFactoryStore";

const catLabel: Record<string, string> = {
  "material-substitution": "Material substitution",
  "waste-to-input": "Waste → input",
  "recycling-loop": "Recycling loop",
  "process-change": "Process change",
  "heat-recovery": "Heat recovery",
};
const kindLabel: Record<string, string> = { kiln: "Kilns", boiler: "Boilers / heaters", furnace: "Furnaces / reactors", dryer: "Dryers / stenters", compressor: "Compressed air", effluent: "Effluent / waste", generic: "Process lines" };

function Kpi({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="glass rounded-xl px-4 py-3">
      <div className="text-[11px] uppercase tracking-wide text-[color:var(--color-muted)]">{label}</div>
      <div className="text-lg font-semibold">{value}</div>
      {sub && <div className="text-[11px] text-[color:var(--color-muted)]">{sub}</div>}
    </div>
  );
}

export default function RegulatorPage() {
  const factories = useFactoryStore((s) => s.factories);
  const symbiosisMatches = useFactoryStore((s) => s.symbiosisMatches);
  const state = useMemo(() => rollup(factories, symbiosisMatches), [factories, symbiosisMatches]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selectedFactoryId, setSelectedFactoryId] = useState<string | null>(null);
  const sel = state.clusters.find((c) => c.cluster.id === selectedId) ?? null;
  const selMatches = sel ? state.matches.filter((m) => state.clusterOf[m.sourceId] === sel.cluster.id || state.clusterOf[m.targetId] === sel.cluster.id) : [];
  const drilldownFactories = sel ? factories.filter((f) => f.cluster.startsWith(sel.cluster.name)) : [];
  const drilldownFactory = drilldownFactories.find((f) => f.id === selectedFactoryId) ?? null;
  const selectCluster = (id: string | null) => {
    setSelectedId(id);
    setSelectedFactoryId(null);
  };

  return (
    <main className="flex flex-1 flex-col gap-3 overflow-y-auto p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-base font-semibold">Regulator rollup — Gujarat industrial clusters</h2>
          <p className="text-[12px] text-[color:var(--color-muted)]">
            Where avoidable emissions concentrate, by cluster and sector — for evidence-based scheme targeting. Bubble size = avoidable CO₂e; colour = average deviation from sub-sector benchmark.
          </p>
        </div>
        <span className="rounded-full border border-[color:var(--color-warn)] px-3 py-1 text-[11px] text-[color:var(--color-warn)]">
          Aggregated & anonymised · cells with &lt; {MIN_CELL} units suppressed · synthetic demo cohort
        </span>
      </div>

      <ScaleImpactPanel defaultCollapsed />

      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-6">
        <Kpi label="Units in cohort" value={String(state.factories)} sub={`${state.clusters.length} clusters`} />
        <Kpi label="Cohort CO₂e / yr" value={`${state.co2eTpy.toLocaleString("en-IN")} t`} />
        <Kpi label="Avoidable CO₂e / yr" value={`${state.avoidableCo2eTpy.toLocaleString("en-IN")} t`} sub={`${Math.round((state.avoidableCo2eTpy / state.co2eTpy) * 100)}% of cohort`} />
        <Kpi label="Avoidable cost / yr" value={formatInr(state.avoidableSavingInr)} sub="best measure per process" />
        <Kpi label="Avg deviation" value={`${state.avgDeviationPct > 0 ? "+" : ""}${state.avgDeviationPct}%`} sub="vs sub-sector benchmark" />
        <Kpi label="Symbiosis matches" value={String(state.symbiosisMatches)} sub={`${state.uptakePct}% intervention uptake`} />
      </div>

      <div className="grid h-[640px] grid-cols-1 gap-3 lg:grid-cols-[1fr_400px]">
        <div className="glass relative overflow-hidden rounded-xl">
          <ClusterMap state={state} selectedId={selectedId} onSelect={selectCluster} factories={factories} selectedFactoryId={selectedFactoryId} onFactorySelect={setSelectedFactoryId} />
          {sel && (
            <div className="pointer-events-none absolute left-3 top-3 max-w-[300px] rounded-lg border border-[color:var(--color-accent)]/50 bg-[color:var(--color-panel)]/90 px-3 py-2 backdrop-blur">
              <div className="text-xs font-semibold text-[color:var(--color-text)]">{sel.cluster.name} factory scene</div>
              <div className="text-[11px] text-[color:var(--color-muted)]">{drilldownFactories.length} factories rising from the industrial ground plane · select one to inspect its contribution</div>
            </div>
          )}
          <div className="pointer-events-none absolute bottom-3 left-3 flex gap-3 rounded-lg border border-[color:var(--color-border)] bg-[color:var(--color-panel)]/85 px-3 py-1.5 text-[11px] backdrop-blur">
            {[["#22c55e", "< 10%"], ["#f5a524", "10–25%"], ["#ef4444", "> 25% above benchmark"]].map(([c, l]) => (
              <span key={l} className="flex items-center gap-1.5 text-[color:var(--color-muted)]">
                <span className="h-2.5 w-2.5 rounded-full" style={{ background: c }} /> {l}
              </span>
            ))}
            <span className="flex items-center gap-1.5 text-[color:var(--color-muted)]">
              <span className="h-0 w-4 border-t border-dashed border-[color:var(--color-accent)]" /> cross-cluster symbiosis
            </span>
          </div>
        </div>

        <div className="glass flex flex-col overflow-hidden rounded-xl">
          {!sel ? (
            <div className="flex flex-1 flex-col overflow-y-auto">
              <div className="border-b border-[color:var(--color-border)] px-4 py-3">
                <h3 className="text-sm font-semibold">Clusters ranked by avoidable CO₂e</h3>
                <p className="text-[11px] text-[color:var(--color-muted)]">Click a bubble or a row for the sector breakdown</p>
              </div>
              {state.clusters.map((c) => (
                <button key={c.cluster.id} onClick={() => selectCluster(c.cluster.id)} className="flex items-center justify-between border-b border-[color:var(--color-border)] px-4 py-2.5 text-left hover:bg-[color:var(--color-panel-2)]/60">
                  <div>
                    <div className="text-sm font-medium">{c.cluster.name}</div>
                    <div className="text-[11px] text-[color:var(--color-muted)]">{c.factories} units · {c.hotspotProcesses} hotspot processes · {c.avgDeviationPct > 0 ? "+" : ""}{c.avgDeviationPct}%</div>
                  </div>
                  <div className="text-right">
                    <div className="text-sm font-semibold">{c.avoidableCo2eTpy.toLocaleString("en-IN")} t</div>
                    <div className="text-[11px] text-[color:var(--color-ok)]">{formatInr(c.avoidableSavingInr)}/yr</div>
                  </div>
                </button>
              ))}
            </div>
          ) : (
            <div className="flex flex-1 flex-col overflow-y-auto">
              <div className="flex items-start justify-between border-b border-[color:var(--color-border)] px-4 py-3">
                <div>
                  <h3 className="text-sm font-semibold">{sel.cluster.name} cluster</h3>
                  <p className="text-[11px] text-[color:var(--color-muted)]">{sel.cluster.district} district · {sel.factories} units in cohort</p>
                </div>
                <button onClick={() => selectCluster(null)} className="rounded-md border border-[color:var(--color-border)] px-2 py-1 text-[11px] hover:bg-[color:var(--color-panel-2)]">← All</button>
              </div>

              <div className="grid grid-cols-2 gap-2 p-3">
                {[
                  ["Cluster CO₂e", `${sel.co2eTpy.toLocaleString("en-IN")} t/yr`],
                  ["Avoidable", `${sel.avoidableCo2eTpy.toLocaleString("en-IN")} t/yr`],
                  ["Avoidable cost", `${formatInr(sel.avoidableSavingInr)}/yr`],
                  ["Uptake so far", `${sel.uptakePct}%`],
                ].map(([k, v]) => (
                  <div key={k} className="rounded-lg border border-[color:var(--color-border)] p-2.5">
                    <div className="text-[10px] text-[color:var(--color-muted)]">{k}</div>
                    <div className="text-sm font-semibold">{v}</div>
                  </div>
                ))}
              </div>

              <Section title="By sector">
                <table className="w-full text-[11px]">
                  <thead className="text-[color:var(--color-muted)]">
                    <tr><th className="py-1 text-left font-medium">Sector</th><th className="text-right font-medium">Units</th><th className="text-right font-medium">Avoidable</th><th className="text-right font-medium">Dev.</th><th className="text-right font-medium">Uptake</th></tr>
                  </thead>
                  <tbody>
                    {sel.sectors.map((s) => (
                      <tr key={s.sector} className="border-t border-[color:var(--color-border)]">
                        <td className="py-1.5">{s.sector}</td>
                        <td className="text-right">{s.factories}</td>
                        {s.suppressed ? (
                          <td colSpan={3} className="text-right italic text-[color:var(--color-muted)]">suppressed (&lt; {MIN_CELL} units)</td>
                        ) : (
                          <>
                            <td className="text-right">{s.avoidableCo2eTpy?.toLocaleString("en-IN")} t</td>
                            <td className="text-right">{(s.avgDeviationPct ?? 0) > 0 ? "+" : ""}{s.avgDeviationPct}%</td>
                            <td className="text-right">{s.uptakePct}%</td>
                          </>
                        )}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </Section>

              <Section title="Where the emissions sit">
                {sel.topProcessKinds.slice(0, 4).map((k) => (
                  <div key={k.kind} className="mb-1.5">
                    <div className="flex justify-between text-[11px]"><span>{kindLabel[k.kind] ?? k.kind}</span><span className="text-[color:var(--color-muted)]">{Math.round(k.share * 100)}%</span></div>
                    <div className="h-1.5 w-full rounded bg-[color:var(--color-panel-2)]"><div className="h-full rounded bg-[color:var(--color-accent)]" style={{ width: `${k.share * 100}%` }} /></div>
                  </div>
                ))}
              </Section>

              <Section title={`Factory contributions (${drilldownFactories.length})`}>
                <p className="mb-2 text-[11px] text-[color:var(--color-muted)]">The map buildings are this exact cohort. Select a building or a row to reveal its contribution; private participants remain anonymised.</p>
                <div className="space-y-1.5">
                  {drilldownFactories.map((f, index) => {
                    const active = drilldownFactory?.id === f.id;
                    const label = f.consentToShare ? f.name : `Participant factory ${String(index + 1).padStart(2, "0")} (private)`;
                    return <button key={f.id} onClick={() => setSelectedFactoryId(active ? null : f.id)} className={`w-full rounded-lg border px-2.5 py-2 text-left transition-colors ${active ? "border-[color:var(--color-accent)] bg-[color:var(--color-accent)]/10" : "border-[color:var(--color-border)] hover:bg-[color:var(--color-panel-2)]"}`}>
                      <div className="flex items-center justify-between gap-2 text-[11px]"><span className="font-medium">{label}</span><span className="shrink-0 font-semibold">{f.totalCo2eTpy.toLocaleString("en-IN")} t</span></div>
                      <div className="mt-0.5 flex justify-between text-[10px] text-[color:var(--color-muted)]"><span>{f.sector}</span><span>{f.nodes.filter((n) => n.severity === "crit").length} hotspots</span></div>
                    </button>;
                  })}
                </div>
                {drilldownFactory && <FactoryContribution factory={drilldownFactory} />}
              </Section>

              <Section title="Intervention types to target (avoidable tCO₂e)">
                {sel.topCategories.map((c) => (
                  <div key={c.category} className="flex justify-between border-b border-[color:var(--color-border)] py-1 text-[11px] last:border-0">
                    <span>{catLabel[c.category]}</span><span className="font-semibold">{c.co2eTpy.toLocaleString("en-IN")} t</span>
                  </div>
                ))}
              </Section>

              <Section title={`Symbiosis matches (${selMatches.length})`}>
                {selMatches.length === 0 ? (
                  <div className="text-[11px] text-[color:var(--color-muted)]">No waste→input matches within 60 km in this cohort.</div>
                ) : (
                  selMatches.map((m) => (
                    <div key={m.id} className="mb-2 rounded-lg border border-[color:var(--color-border)] p-2 text-[11px]">
                      <div className="font-medium">{m.label}</div>
                      <div className="text-[color:var(--color-muted)]">{m.sourceName} → {m.targetName} · {m.distanceKm} km</div>
                      <div className="mt-1 flex gap-3">
                        <span>{m.tonnesMatched.toLocaleString("en-IN")} t/yr</span>
                        <span className="text-[color:var(--color-ok)]">−{m.co2AvoidedTpy} tCO₂e</span>
                        <span>{formatInr(m.sourceSavingInr + m.targetSavingInr)} both parties</span>
                      </div>
                    </div>
                  ))
                )}
              </Section>
            </div>
          )}
        </div>
      </div>
    </main>
  );
}

function FactoryContribution({ factory }: { factory: typeof allFactories[number] }) {
  const total = factory.totalCo2eTpy || 1;
  return (
    <div className="mt-2 rounded-lg border border-[color:var(--color-accent)]/40 bg-[color:var(--color-panel-2)]/60 p-2.5">
      <div className="mb-2 text-[11px] font-semibold">What this factory adds to the region</div>
      <div className="grid grid-cols-3 gap-1.5 text-center">
        <div><div className="text-sm font-semibold">{factory.totalCo2eTpy.toLocaleString("en-IN")}</div><div className="text-[9px] text-[color:var(--color-muted)]">tCO₂e / yr</div></div>
        <div><div className="text-sm font-semibold">{factory.totalEnergyMwhPerYear.toLocaleString("en-IN")}</div><div className="text-[9px] text-[color:var(--color-muted)]">MWh / yr</div></div>
        <div><div className="text-sm font-semibold">{Math.round(factory.circularityRatio * 100)}%</div><div className="text-[9px] text-[color:var(--color-muted)]">circularity</div></div>
      </div>
      <div className="mt-2 space-y-1">
        {factory.nodes.filter((n) => n.co2eTpy > 0).sort((a, b) => b.co2eTpy - a.co2eTpy).slice(0, 3).map((n) => <div key={n.id}>
          <div className="flex justify-between text-[10px]"><span>{n.label}</span><span>{n.co2eTpy.toLocaleString("en-IN")} t</span></div>
          <div className="h-1 rounded bg-[color:var(--color-border)]"><div className="h-full rounded bg-[color:var(--color-accent)]" style={{ width: `${(n.co2eTpy / total) * 100}%` }} /></div>
        </div>)}
      </div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="border-t border-[color:var(--color-border)] px-4 py-3">
      <h4 className="mb-2 text-[10px] font-semibold uppercase tracking-wide text-[color:var(--color-muted)]">{title}</h4>
      {children}
    </div>
  );
}
