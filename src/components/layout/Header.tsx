import { NavLink } from "react-router-dom";
import { useFactoryStore } from "../../store/useFactoryStore";
import { useTranslation } from "../../store/useLanguageStore";
import { useRoleStore, type Role } from "../../store/useRoleStore";
import { useAuthStore } from "../../store/useAuthStore";
import { languageNames, type Language, type Translations } from "../../lib/i18n";
import UsageMeter from "../business/UsageMeter";

const linkConfigs: { to: string; labelKey?: keyof Translations; label?: string; pro?: boolean }[] = [
  { to: "/", labelKey: "navDiagnose" },
  { to: "/simulate", labelKey: "navSimulate", pro: true },
  { to: "/plan", labelKey: "navActionPlan" },
  { to: "/regulator", labelKey: "navRegulator" },
  { to: "/portfolio", labelKey: "navPortfolio" },
  { to: "/co2-exchange", labelKey: "navCo2Exchange", pro: true },
  { to: "/intake", labelKey: "navIntake" },
  { to: "/leak-diagnostics", label: "Leaks" },
  { to: "/consent", label: "Consent" },
  { to: "/developer", label: "API" },
];

const ROLE_LABEL: Record<Role, string> = { sme: "SME owner", consultant: "Consultant", regulator: "Regulator" };

export default function Header() {
  const factory = useFactoryStore((s) => s.baseline);
  const factories = useFactoryStore((s) => s.factories);
  const setFactory = useFactoryStore((s) => s.setFactory);
  const { lang, setLanguage, t } = useTranslation();
  const role = useRoleStore((s) => s.role);
  const setRole = useRoleStore((s) => s.setRole);
  const tier = useRoleStore((s) => s.tier);
  const authUser = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);

  return (
    <header className="flex items-center justify-between border-b border-[color:var(--color-border)] px-4 md:px-6 py-2.5">
      <div className="flex items-center gap-3">
        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-[color:var(--color-accent)]/15 text-[color:var(--color-accent)]">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
            <path
              d="M12 2 L21 7 V17 L12 22 L3 17 V7 Z"
              stroke="currentColor"
              strokeWidth="1.6"
              strokeLinejoin="round"
            />
            <circle cx="12" cy="12" r="3" fill="currentColor" />
          </svg>
        </div>
        <div>
          <div className="text-sm font-semibold leading-tight">{t("brandTitle")}</div>
          <div className="text-[11px] leading-tight text-[color:var(--color-muted)]">{t("brandSubtitle")}</div>
        </div>
      </div>

      <nav className="hidden items-center gap-1 md:flex">
        {linkConfigs.map((l) => (
          <NavLink
            key={l.to}
            to={l.to}
            end={l.to === "/"}
            className={({ isActive }) =>
              `flex items-center gap-1 rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
                isActive ? "bg-[color:var(--color-panel-2)] text-[color:var(--color-text)]" : "text-[color:var(--color-muted)] hover:text-[color:var(--color-text)]"
              }`
            }
          >
            {l.labelKey ? t(l.labelKey) : l.label}
            {l.pro && tier === "free" && (
              <span className="rounded border border-[#f5a524]/60 px-1 text-[8px] font-bold uppercase text-[#f5a524]">Pro</span>
            )}
          </NavLink>
        ))}
      </nav>

      <div className="flex items-center gap-3 text-right">
        {authUser && (
          <span className="hidden items-center gap-1.5 rounded-full border border-[color:var(--color-ok)]/50 px-2.5 py-1 text-[10px] text-[color:var(--color-ok)] lg:flex" title={`Logged in as ${authUser.email}`}>
            {authUser.email}
            <button onClick={logout} className="text-[color:var(--color-muted)] hover:text-[color:var(--color-text)]">Log out</button>
          </span>
        )}
        <UsageMeter kind="report_generated" />
        {/* Role switcher — no real auth, a demo persona toggle that gates nav/features */}
        <select
          value={role}
          onChange={(e) => setRole(e.target.value as Role)}
          className="hidden rounded-md border border-[color:var(--color-border)] bg-[color:var(--color-panel)] px-2 py-1 text-[11px] lg:inline-block"
          title="Demo role (no real auth)"
        >
          {(["sme", "consultant", "regulator"] as Role[]).map((r) => (
            <option key={r} value={r}>{ROLE_LABEL[r]}</option>
          ))}
        </select>
        {/* Language Switcher */}
        <div className="flex items-center rounded-lg border border-[color:var(--color-border)] bg-[color:var(--color-panel)] p-0.5 text-xs font-medium shadow-sm">
          {(["en", "gu", "hi"] as Language[]).map((l) => (
            <button
              key={l}
              onClick={() => setLanguage(l)}
              className={`rounded-md px-2 py-1 transition-all text-[11px] ${
                lang === l
                  ? "bg-[color:var(--color-accent)] text-[#07101c] font-bold shadow-sm"
                  : "text-[color:var(--color-muted)] hover:text-[color:var(--color-text)]"
              }`}
              title={languageNames[l].label}
            >
              {languageNames[l].native}
            </button>
          ))}
        </div>

        <div>
          <select
            value={factory.id}
            onChange={(e) => setFactory(e.target.value)}
            className="max-w-[220px] cursor-pointer rounded-md border border-[color:var(--color-border)] bg-[color:var(--color-panel)] px-2 py-1 text-sm font-medium text-[color:var(--color-text)] outline-none hover:bg-[color:var(--color-panel-2)]"
            title={t("switchFactory")}
          >
            {factories.map((f) => (
              <option key={f.id} value={f.id}>{f.name}</option>
            ))}
          </select>
          <div className="mt-0.5 text-[11px] leading-tight text-[color:var(--color-muted)]">
            {factory.cluster} · {factory.sector}
          </div>
        </div>
        <span
          className={`hidden sm:inline-block rounded-full border px-2.5 py-1 text-[10px] font-medium uppercase tracking-wide ${
            factory.dataSource === "synthetic"
              ? "border-[color:var(--color-warn)] text-[color:var(--color-warn)]"
              : "border-[color:var(--color-ok)] text-[color:var(--color-ok)]"
          }`}
        >
          {factory.dataSource === "synthetic" ? t("illustrativeData") : t("selfReportedData")}
        </span>
      </div>
    </header>
  );
}
