import { useEffect, useState } from "react";
import { api, type ApiConsentRow } from "../lib/api";
import { useAuthStore } from "../store/useAuthStore";
import LoginGate from "../components/business/LoginGate";

// A real "Data sharing & consent" audit page over Factory.consent_to_share —
// the exact due-diligence artifact a government data-partnership pitch
// needs: who opted in, when, and what's visible to the Regulator rollup as
// a result (RegulatorPage.tsx anonymises any factory with consent_to_share
// = false). Toggling here calls the real PATCH /api/factories/{id}/consent
// endpoint, which stamps a real consent_updated_at timestamp — not a
// client-only checkbox.
export default function ConsentLedgerPage() {
  const [rows, setRows] = useState<ApiConsentRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const token = useAuthStore((s) => s.token);

  const reload = () => {
    setLoading(true);
    api.consentLedger().then((r) => { setRows(r); setError(null); }).catch((e) => setError(e instanceof Error ? e.message : String(e))).finally(() => setLoading(false));
  };
  useEffect(reload, []);

  const toggle = async (row: ApiConsentRow) => {
    setBusyId(row.factory_id);
    try {
      const updated = await api.setFactoryConsent(row.factory_id, !row.consent_to_share);
      setRows((prev) => prev.map((r) => (r.factory_id === updated.factory_id ? updated : r)));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusyId(null);
    }
  };

  const optedIn = rows.filter((r) => r.consent_to_share).length;

  return (
    <main className="flex flex-1 flex-col gap-3 overflow-hidden p-4">
      <div>
        <h2 className="text-base font-semibold">Data sharing & consent ledger</h2>
        <p className="text-[12px] text-[color:var(--color-muted)]">
          Who opted in, when, and what that opt-in makes visible to the Regulator rollup. Backed by
          the real <code>consent_to_share</code> / <code>consent_updated_at</code> fields on every
          factory — toggling here is a genuine write, not a UI-only checkbox.
        </p>
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
        <div className="glass rounded-xl px-4 py-3"><div className="text-[11px] uppercase tracking-wide text-[color:var(--color-muted)]">Total factories</div><div className="text-lg font-semibold">{rows.length}</div></div>
        <div className="glass rounded-xl px-4 py-3"><div className="text-[11px] uppercase tracking-wide text-[color:var(--color-muted)]">Opted in</div><div className="text-lg font-semibold text-[color:var(--color-ok)]">{optedIn}</div></div>
        <div className="glass rounded-xl px-4 py-3"><div className="text-[11px] uppercase tracking-wide text-[color:var(--color-muted)]">Opted out (anonymised)</div><div className="text-lg font-semibold text-[color:var(--color-warn)]">{rows.length - optedIn}</div></div>
      </div>

      {error && <p className="text-[12px] text-[color:var(--color-crit)]">{error}</p>}
      {!token && <LoginGate feature="grant or revoke a factory's consent" />}

      <div className="glass flex-1 overflow-auto rounded-xl">
        <table className="w-full text-[12px]">
          <thead className="sticky top-0 bg-[color:var(--color-panel)] text-[11px] uppercase tracking-wide text-[color:var(--color-muted)]">
            <tr>
              <th className="px-4 py-2.5 text-left font-medium">Factory</th>
              <th className="px-3 py-2.5 text-left font-medium">Data source</th>
              <th className="px-3 py-2.5 text-left font-medium">Consent status</th>
              <th className="px-3 py-2.5 text-left font-medium">Last updated</th>
              <th className="px-3 py-2.5 text-left font-medium">Visible to regulator</th>
              <th className="px-3 py-2.5 text-right font-medium">Action</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={6} className="px-4 py-6 text-center text-[color:var(--color-muted)]">Loading consent ledger…</td></tr>
            ) : rows.map((r) => (
              <tr key={r.factory_id} className="border-t border-[color:var(--color-border)]">
                <td className="px-4 py-2.5 font-medium">{r.factory_name}</td>
                <td className="px-3 py-2.5 text-[color:var(--color-muted)]">{r.data_source}</td>
                <td className="px-3 py-2.5">
                  <span className={`rounded-full border px-2 py-0.5 text-[10px] ${r.consent_to_share ? "border-[color:var(--color-ok)] text-[color:var(--color-ok)]" : "border-[color:var(--color-warn)] text-[color:var(--color-warn)]"}`}>
                    {r.consent_to_share ? "Opted in" : "Opted out"}
                  </span>
                </td>
                <td className="px-3 py-2.5 text-[color:var(--color-muted)]">{new Date(r.consent_updated_at).toLocaleString("en-IN")}</td>
                <td className="px-3 py-2.5">{r.visible_to_regulator ? "By real name" : "Anonymised"}</td>
                <td className="px-3 py-2.5 text-right">
                  <button
                    onClick={() => toggle(r)}
                    disabled={busyId === r.factory_id || !token}
                    title={!token ? "Sign in above to change consent" : undefined}
                    className="rounded-md border border-[color:var(--color-border)] px-2.5 py-1 text-[11px] hover:bg-[color:var(--color-panel-2)] disabled:opacity-50"
                  >
                    {busyId === r.factory_id ? "Updating…" : r.consent_to_share ? "Revoke consent" : "Grant consent"}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </main>
  );
}
