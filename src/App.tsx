import { useEffect } from "react";
import { HashRouter, Routes, Route } from "react-router-dom";
import Header from "./components/layout/Header";
import FactoryPage from "./pages/FactoryPage";
import SimulatorPage from "./pages/SimulatorPage";
import ActionPlanPage from "./pages/ActionPlanPage";
import RegulatorPage from "./pages/RegulatorPage";
import PortfolioPage from "./pages/PortfolioPage";
import IntakePage from "./pages/IntakePage";
import Co2ExchangePage from "./pages/Co2ExchangePage";
import Co2DealPage from "./pages/Co2DealPage";
import ReportPage from "./pages/ReportPage";
import BrsrReportPage from "./pages/BrsrReportPage";
import ConsentLedgerPage from "./pages/ConsentLedgerPage";
import DeveloperApiPage from "./pages/DeveloperApiPage";
import LeakDiagnosticsPage from "./pages/LeakDiagnosticsPage";
import JarvisAssistant from "./components/assistant/JarvisAssistant";
import { useFactoryStore } from "./store/useFactoryStore";

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
        <JarvisAssistant />
      </div>
    </HashRouter>
  );
}

export default App;
