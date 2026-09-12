import { useEffect, useMemo, useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import { useFactoryStore } from "../store/useFactoryStore";
import { useAuthStore } from "../store/useAuthStore";
import { severityColor, formatInr } from "../lib/severity";
import { api, type ApiOrganization } from "../lib/api";
import LoginGate from "../components/business/LoginGate";
import type { Factory, Severity } from "../types";

type SortKey = "co2" | "deviation" | "hotspots" | "avoidable";

function deviationPct(f: Factory): number {
  const w = f.nodes.reduce((a, n) => a + n.co2eTpy, 0) || 1;
  return Math.round((f.nodes.reduce((a, n) => a + ((n.actualIntensity - n.benchmarkIntensity) / n.benchmarkIntensity) * n.co2eTpy, 0) / w) * 100);
}
// Best single recommendation per process — matches the backend's convention
// (backend/app/routers/factories.py). Falls back to a local computation only
// for factories the API hasn't tagged yet (e.g. a just-added intake draft).
function avoidable(f: Factory): number {
  return f.avoidableCo2eTpy ?? f.nodes.reduce((a, n) => a + ([...n.interventions].sort((x, y) => y.co2ReductionTpy - x.co2ReductionTpy)[0]?.co2ReductionTpy ?? 0), 0);
}
function worst(f: Factory): Severity {
  if (f.nodes.some((n) => n.severity === "crit")) return "crit";
  if (f.nodes.some((n) => n.severity === "warn")) return "warn";
  return "ok";
}

export default function PortfolioPage() {
  const factories = useFactoryStore((s) => s.factories);
  const current = useFactoryStore((s) => s.baseline);
  const setFactory = useFactoryStore((s) => s.setFactory);
  const navigate = useNavigate();
  const [sort, setSort] = useState<SortKey>("avoidable");
  const [cluster, setCluster] = useState<string>("all");
  const [orgs, setOrgs] = useState<ApiOrganization[]>([]);
  const [orgByFactoryId, setOrgByFactoryId] = useState<Record<string, string | null>>({});
  const [newOrgName, setNewOrgName] = useState("");
  const [orgError, setOrgError] = useState<string | null>(null);
  const token = useAuthStore((s) => s.token);

  const loadOrgs = () => {
    api.organizations().then(setOrgs).catch(() => {});
    api.factoriesSummary().then((rows) => {
      setOrgByFactoryId(Object.fromEntries(rows.map((r) => [r.id, r.organization_id])));
    }).catch(() => {});
  };
  useEffect(loadOrgs, []);

  const createOrg = async () => {
    if (!newOrgName.trim()) return;
    setOrgError(null);
    try {
      await api.createOrganization(newOrgName.trim());
      setNewOrgName("");
      loadOrgs();
    } catch (e) {
      setOrgError(e instanceof Error ? e.message : String(e));
    }
  };

  const assign = async (factoryId: string, organizationId: string) => {
    const prevValue = orgByFactoryId[factoryId] ?? null;
    setOrgByFactoryId((prev) => ({ ...prev, [factoryId]: organizationId || null }));
    setOrgError(null);
    try {
      await api.assignFactoryOrganization(factoryId, organizationId || null);
      loadOrgs();
    } catch (e) {
      setOrgByFactoryId((prev) => ({ ...prev, [factoryId]: prevValue })); // roll back the optimistic update
      setOrgError(e instanceof Error ? e.message : String(e));
    }
  };

  const rows = useMemo(() => {
    const r = factories
      .filter((f) => cluster === "all" || f.cluster.startsWith(cluster))
      .map((f) => ({ f, dev: deviationPct(f), hot: f.nodes.filter((n) => n.severity === "crit").length, avoid: avoidable(f), sev: worst(f) }));
    const key = { co2: (x: (typeof r)[0]) => x.f.totalCo2eTpy, deviation: (x: (typeof r)[0]) => x.dev, hotspots: (x: (typeof r)[0]) => x.hot, avoidable: (x: (typeof r)[0]) => x.avoid }[sort];
    return r.sort((a, b) => key(b) - key(a));
  }, [factories, sort, cluster]);

  const clusters = [...new Set(factories.map((f) => f.cluster.split(",")[0]))];
  const totalAvoid = rows.reduce((a, r) => a + r.avoid, 0);
  const totalCreditValue = rows.reduce((a, r) => a + (r.f.carbonCreditValueInrPerYear ?? 0), 0);

  const open = (id: string) => {
    setFactory(id);
    navigate("/");
  };

  return (
    <main className="flex flex-1 flex-col gap-3 overflow-hidden p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-base font-semibold">Consultant portfolio</h2>
          <p className="text-[12px] text-[color:var(--color-muted)]">Every client factory through the same diagnostic engine. Click a row to open its twin.</p>
        </div>
        <div className="flex gap-2 text-[12px]">
          <select value={cluster} onChange={(e) => setCluster(e.target.value)} className="rounded-md border border-[color:var(--color-border)] bg-[color:var(--color-panel)] px-2 py-1">
            <option value="all">All clusters</option>
            {clusters.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
          <select value={sort} onChange={(e) => setSort(e.target.value as SortKey)} className="rounded-md border border-[color:var(--color-border)] bg-[color:var(--color-panel)] px-2 py-1">
            <option value="avoidable">Sort: avoidable CO₂e</option>
            <option value="deviation">Sort: deviation</option>
            <option value="hotspots">Sort: hotspots</option>
            <option value="co2">Sort: total CO₂e</option>
          </select>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
        {[
          ["Factories", String(rows.length)],
          ["Portfolio CO₂e / yr", `${rows.reduce((a, r) => a + r.f.totalCo2eTpy, 0).toLocaleString("en-IN")} t`],
          ["Avoidable CO₂e / yr", `${totalAvoid.toLocaleString("en-IN")} t`],
          ["Hotspot processes", String(rows.reduce((a, r) => a + r.hot, 0))],
          ["Carbon-credit value / yr*", formatInr(totalCreditValue)],
        ].map(([k, v]) => (
          <div key={k} className="glass rounded-xl px-4 py-3">
            <div className="text-[11px] uppercase tracking-wide text-[color:var(--color-muted)]">{k}</div>
            <div className="text-lg font-semibold">{v}</div>
          </div>
        ))}
      </div>
      <p className="-mt-2 text-[10px] italic text-[color:var(--color-muted)]">
        *Illustrative — indicative CCTS pricing, not an official or mandated price.
      </p>

      <div className="glass flex flex-wrap items-center gap-2 rounded-xl px-4 py-2.5">
        <span className="text-[11px] font-semibold">Organizations (white-labeled workspaces):</span>
        {orgs.map((o) => (
          <span key={o.id} className="flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px]" style={{ borderColor: o.brand_color, color: o.brand_color }}>
            {o.logo_text || o.name} · {o.factory_count} factories · {o.tier}
          </span>
        ))}
        {token ? (
          <>
            <input
              value={newOrgName}
              onChange={(e) => setNewOrgName(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && createOrg()}
              placeholder="New organization name"
              className="rounded-md border border-[color:var(--color-border)] bg-[color:var(--color-panel-2)] px-2 py-1 text-[11px] outline-none"
            />
            <button onClick={createOrg} className="rounded-md border border-[color:var(--color-border)] px-2 py-1 text-[11px] hover:bg-[color:var(--color-panel-2)]">+ Create</button>
          </>
        ) : (
          <span className="text-[11px] text-[color:var(--color-muted)]">Sign in below to create an organization or assign factories to one.</span>
        )}
      </div>
      {!token && <LoginGate feature="manage organizations and factory assignments" />}
      {orgError && <p className="text-[11px] text-[color:var(--color-crit)]">{orgError}</p>}

      <div className="glass flex-1 overflow-auto rounded-xl">
        <table className="w-full text-[12px]">
          <thead className="sticky top-0 bg-[color:var(--color-panel)] text-[11px] uppercase tracking-wide text-[color:var(--color-muted)]">
            <tr>
              <th className="px-4 py-2.5 text-left font-medium">Factory</th>
              <th className="px-3 py-2.5 text-left font-medium">Cluster · sector</th>
              <th className="px-3 py-2.5 text-right font-medium">CO₂e / yr</th>
              <th className="px-3 py-2.5 text-right font-medium">vs benchmark</th>
              <th className="px-3 py-2.5 text-right font-medium">Hotspots</th>
              <th className="px-3 py-2.5 text-right font-medium">Avoidable</th>
              <th className="px-3 py-2.5 text-right font-medium">Circularity</th>
              <th className="px-3 py-2.5 text-right font-medium">Implemented</th>
              <th className="px-3 py-2.5 text-left font-medium">Data</th>
              <th className="px-3 py-2.5 text-left font-medium">Organization</th>
              <th className="px-3 py-2.5 text-right font-medium">Report</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(({ f, dev, hot, avoid, sev }) => (
              <tr
                key={f.id}
                onClick={() => open(f.id)}
                className={`cursor-pointer border-t border-[color:var(--color-border)] hover:bg-[color:var(--color-panel-2)]/60 ${f.id === current.id ? "bg-[color:var(--color-panel-2)]/80" : ""}`}
              >
                <td className="px-4 py-2.5">
                  <div className="flex items-center gap-2">
                    <span className="h-2.5 w-2.5 rounded-full" style={{ background: severityColor[sev], boxShadow: `0 0 6px ${severityColor[sev]}` }} />
                    <span className="font-medium">{f.name}</span>
                    {f.id === current.id && <span className="rounded border border-[color:var(--color-accent)]/50 px-1 text-[9px] uppercase text-[color:var(--color-accent)]">active</span>}
                  </div>
                </td>
                <td className="px-3 py-2.5 text-[color:var(--color-muted)]">{f.cluster.split(",")[0]} · {f.sector}</td>
                <td className="px-3 py-2.5 text-right">{f.totalCo2eTpy.toLocaleString("en-IN")} t</td>
                <td className="px-3 py-2.5 text-right" style={{ color: severityColor[dev < 10 ? "ok" : dev < 30 ? "warn" : "crit"] }}>{dev > 0 ? "+" : ""}{dev}%</td>
                <td className="px-3 py-2.5 text-right">{hot} / {f.nodes.length}</td>
                <td className="px-3 py-2.5 text-right font-semibold">{avoid.toLocaleString("en-IN")} t</td>
                <td className="px-3 py-2.5 text-right">{Math.round(f.circularityRatio * 100)}%</td>
                <td className="px-3 py-2.5 text-right">{f.implementedInterventionIds.length}</td>
                <td className="px-3 py-2.5">
                  <span className="rounded-full border border-[color:var(--color-warn)]/50 px-1.5 py-0.5 text-[10px] text-[color:var(--color-warn)]">{f.dataSource}</span>
                </td>
                <td className="px-3 py-2.5" onClick={(e) => e.stopPropagation()}>
                  <select
                    value={orgByFactoryId[f.id] ?? ""}
                    onChange={(e) => assign(f.id, e.target.value)}
                    className="rounded-md border border-[color:var(--color-border)] bg-[color:var(--color-panel-2)] px-1.5 py-1 text-[10px]"
                  >
                    <option value="">Unassigned</option>
                    {orgs.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
                  </select>
                </td>
                <td className="px-3 py-2.5 text-right" onClick={(e) => e.stopPropagation()}>
                  <Link to={`/report/${f.id}`} className="text-[11px] text-[color:var(--color-accent)] hover:underline">
                    Open →
                  </Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </main>
  );
}
