import { Suspense, lazy, useEffect } from "react";
import { HashRouter, Routes, Route } from "react-router-dom";
import Header from "./components/layout/Header";
import JarvisAssistant from "./components/assistant/JarvisAssistant";
import { useFactoryStore } from "./store/useFactoryStore";

// Route-level code splitting: each page is its own chunk, fetched only when
// actually navigated to, instead of one ~2.3MB bundle upfront. The heaviest
// offenders (react-three-fiber's 3D twin on Diagnose/Simulate, Leaflet maps
// on Regulator/CO2 Exchange, react-markdown on the chat widget's page-level
// usage) now load lazily per-route rather than all at once on first paint.
const FactoryPage = lazy(() => import("./pages/FactoryPage"));
const SimulatorPage = lazy(() => import("./pages/SimulatorPage"));
const ActionPlanPage = lazy(() => import("./pages/ActionPlanPage"));
const RegulatorPage = lazy(() => import("./pages/RegulatorPage"));
const PortfolioPage = lazy(() => import("./pages/PortfolioPage"));
const IntakePage = lazy(() => import("./pages/IntakePage"));
const Co2ExchangePage = lazy(() => import("./pages/Co2ExchangePage"));
const Co2DealPage = lazy(() => import("./pages/Co2DealPage"));
const ReportPage = lazy(() => import("./pages/ReportPage"));
const BrsrReportPage = lazy(() => import("./pages/BrsrReportPage"));
const ConsentLedgerPage = lazy(() => import("./pages/ConsentLedgerPage"));
const DeveloperApiPage = lazy(() => import("./pages/DeveloperApiPage"));
const LeakDiagnosticsPage = lazy(() => import("./pages/LeakDiagnosticsPage"));

function RouteFallback() {
  return (
    <div className="flex flex-1 items-center justify-center bg-[color:var(--color-bg)]">
      <p className="text-sm text-[color:var(--color-muted)]">Loading…</p>
    </div>
  );
}

function App() {
  const hydrated = useFactoryStore((s) => s.hydrated);
  const loading = useFactoryStore((s) => s.loading);
  const loadError = useFactoryStore((s) => s.loadError);
  const load = useFactoryStore((s) => s.load);

  useEffect(() => {
    load();
  }, [load]);

  if (loadError) {
    return (
      <div className="flex h-screen flex-col items-center justify-center gap-3 bg-[color:var(--color-bg)] p-6 text-center">
        <h1 className="text-lg font-semibold text-[color:var(--color-crit)]">Could not reach the Induscope API</h1>
        <p className="max-w-md text-sm text-[color:var(--color-muted)]">{loadError}</p>
        <p className="max-w-md text-xs text-[color:var(--color-muted)]">
          Make sure the backend is running: <code>cd backend &amp;&amp; python -m uvicorn app.main:app --port 8811</code>
        </p>
        <button onClick={() => useFactoryStore.setState({ hydrated: false })} className="mt-2 rounded-lg border border-[color:var(--color-border)] px-4 py-2 text-sm hover:bg-[color:var(--color-panel-2)]">
          Retry
        </button>
      </div>
    );
  }

  if (!hydrated || loading) {
    return (
      <div className="flex h-screen items-center justify-center bg-[color:var(--color-bg)]">
        <p className="text-sm text-[color:var(--color-muted)]">Loading factories from the Induscope API…</p>
      </div>
    );
  }

  return (
    <HashRouter>
      <div className="flex h-screen flex-col overflow-hidden">
        <Header />
        <Suspense fallback={<RouteFallback />}>
          <Routes>
            <Route path="/" element={<FactoryPage />} />
            <Route path="/simulate" element={<SimulatorPage />} />
            <Route path="/plan" element={<ActionPlanPage />} />
            <Route path="/regulator" element={<RegulatorPage />} />
            <Route path="/portfolio" element={<PortfolioPage />} />
            <Route path="/intake" element={<IntakePage />} />
            <Route path="/intake/:factoryId" element={<IntakePage />} />
            <Route path="/co2-exchange" element={<Co2ExchangePage />} />
            <Route path="/co2-exchange/deal/:providerId/:recipientId" element={<Co2DealPage />} />
            <Route path="/report/:factoryId" element={<ReportPage />} />
            <Route path="/report/:factoryId/brsr" element={<BrsrReportPage />} />
            <Route path="/consent" element={<ConsentLedgerPage />} />
            <Route path="/leak-diagnostics" element={<LeakDiagnosticsPage />} />
            <Route path="/developer" element={<DeveloperApiPage />} />
          </Routes>
        </Suspense>
        <JarvisAssistant />
      </div>
    </HashRouter>
  );
}

export default App;
