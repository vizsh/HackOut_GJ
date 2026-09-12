import { useState } from "react";
import { useRoleStore } from "../store/useRoleStore";
import { useAuthStore } from "../store/useAuthStore";
import { api, type ApiKeyResult } from "../lib/api";
import LoginGate from "../components/business/LoginGate";

// A real, documented, rate-limited public API tier — GET /api/public/v1/factories/{id}
// scoped to an X-API-Key header, backed by backend/app/routers/business.py's
// ApiKey table and an in-memory sliding-window rate limiter. This is the
// difference between "an app" and "infrastructure other software (ERP,
// accounting) builds on" — minting a key here is a real database write, and
// the curl example below is copy-pasteable against the running backend.
export default function DeveloperApiPage() {
  const organizationId = useRoleStore((s) => s.organizationId);
  const token = useAuthStore((s) => s.token);
  const [minted, setMinted] = useState<ApiKeyResult | null>(null);
  const [label, setLabel] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const mint = async () => {
    if (!organizationId) { setError("Select an organization first (role switcher, top right)."); return; }
    setBusy(true);
    setError(null);
    try {
      setMinted(await api.createApiKey(organizationId, label));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const apiBase = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8811";
  const exampleKey = minted?.key ?? "isk_your_key_here";

  return (
    <main className="flex flex-1 flex-col gap-4 overflow-y-auto p-6">
      <div>
        <h2 className="text-base font-semibold">Developer API</h2>
        <p className="text-[12px] text-[color:var(--color-muted)]">
          A narrow, rate-limited, read-only slice of the Induscope API for ERP/accounting-software
          integrations — the same real per-factory numbers the frontend shows, gated by an API key
          instead of open like the rest of this dev-only backend.
        </p>
      </div>

      <section className="glass rounded-xl p-4">
        <h3 className="text-sm font-semibold">Generate an API key</h3>
        {!token ? (
          <div className="mt-2"><LoginGate feature="mint an API key" /></div>
        ) : (
          <div className="mt-2 flex gap-2">
            <input
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              placeholder="Key label (e.g. 'Tally ERP integration')"
              className="flex-1 rounded-md border border-[color:var(--color-border)] bg-[color:var(--color-panel-2)] px-3 py-2 text-xs outline-none focus:border-[color:var(--color-accent)]"
            />
            <button onClick={mint} disabled={busy} className="rounded-lg bg-[color:var(--color-accent)] px-4 py-2 text-xs font-semibold text-[#07101c] disabled:opacity-50">
              {busy ? "Generating…" : "Generate key"}
            </button>
          </div>
        )}
        {error && <p className="mt-2 text-[11px] text-[color:var(--color-crit)]">{error}</p>}
        {minted && (
          <div className="mt-3 rounded-lg border border-[color:var(--color-ok)]/40 bg-[color:var(--color-ok)]/5 p-3">
            <div className="text-[10px] uppercase tracking-wide text-[color:var(--color-muted)]">Your API key (shown once — store it)</div>
            <code className="mt-1 block break-all text-[12px] font-semibold">{minted.key}</code>
            <div className="mt-1 text-[11px] text-[color:var(--color-muted)]">Rate limit: {minted.rate_limit_per_min} requests/minute</div>
          </div>
        )}
      </section>

      <section className="glass rounded-xl p-4">
        <h3 className="text-sm font-semibold">Endpoint</h3>
        <p className="mt-1 text-[12px] text-[color:var(--color-muted)]">
          <code>GET /api/public/v1/factories/&#123;factory_id&#125;</code> — returns id, name, sector,
          cluster, total CO₂e/yr, worst process severity, data source. Requires an <code>X-API-Key</code> header.
        </p>
        <pre className="mt-2 overflow-x-auto rounded-lg border border-[color:var(--color-border)] bg-black/30 p-3 text-[11px] text-[#b9dcff]">
{`curl -H "X-API-Key: ${exampleKey}" \\
  ${apiBase}/api/public/v1/factories/morbi-ceramics-01`}
        </pre>
      </section>

      <section className="text-[10px] leading-relaxed text-[color:var(--color-muted)]">
        Rate limiting is an in-memory sliding window for the life of one server process — real for
        this demo, but not a distributed/persisted limiter (would need Redis or similar in
        production). Disclosed here rather than hidden. See backend/app/routers/business.py.
      </section>
    </main>
  );
}
