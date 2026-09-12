import { useState } from "react";
import { useAuthStore } from "../../store/useAuthStore";
import { api } from "../../lib/api";

// Gates a real backend mutation (organization creation, consent changes,
// API-key minting — see backend/app/routers/business.py) behind an actual
// login, not a client-side toggle. Demo accounts are seeded (backend/app/
// db/seed_loader.py) and shown inline so this is usable without a signup
// flow, but the login itself is real: POST /api/auth/login, password
// hashing, a signed session token attached to every subsequent request
// (see src/lib/api.ts's authHeaders()).
export default function LoginGate({ feature, children }: { feature: string; children?: React.ReactNode }) {
  const token = useAuthStore((s) => s.token);
  const setSession = useAuthStore((s) => s.setSession);
  const [email, setEmail] = useState("consultant@induscope.demo");
  const [password, setPassword] = useState("induscope-demo");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (token) return <>{children}</>;

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const result = await api.login(email, password);
      setSession(result.token, result.user);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="rounded-xl border border-[color:var(--color-border)] bg-[color:var(--color-panel-2)] p-4">
      <p className="text-[12px] text-[color:var(--color-muted)]">Sign in to {feature} — this is a real login (backend/app/auth.py), not a demo toggle.</p>
      <form onSubmit={submit} className="mt-2 flex flex-wrap items-end gap-2">
        <label className="text-[10px] uppercase tracking-wide text-[color:var(--color-muted)]">
          Email
          <input value={email} onChange={(e) => setEmail(e.target.value)} className="mt-1 block rounded-md border border-[color:var(--color-border)] bg-[color:var(--color-panel)] px-2 py-1.5 text-sm" />
        </label>
        <label className="text-[10px] uppercase tracking-wide text-[color:var(--color-muted)]">
          Password
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} className="mt-1 block rounded-md border border-[color:var(--color-border)] bg-[color:var(--color-panel)] px-2 py-1.5 text-sm" />
        </label>
        <button disabled={busy} className="rounded-lg bg-[color:var(--color-accent)] px-3 py-1.5 text-xs font-semibold text-[#07101c] disabled:opacity-50">
          {busy ? "Signing in…" : "Sign in"}
        </button>
      </form>
      {error && <p className="mt-1.5 text-[11px] text-[color:var(--color-crit)]">{error}</p>}
      <p className="mt-2 text-[10px] text-[color:var(--color-muted)]">
        Seeded demo accounts: consultant@induscope.demo · sme@induscope.demo · regulator@induscope.demo — password <code>induscope-demo</code> for all three.
      </p>
    </div>
  );
}
