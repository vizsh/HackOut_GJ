import { useEffect } from "react";
import { MapContainer, TileLayer, CircleMarker, Tooltip, Polyline, Marker, useMap, ZoomControl } from "react-leaflet";
import "leaflet/dist/leaflet.css";
import { divIcon } from "leaflet";
import type { ClusterRollup, StateRollup } from "../../lib/rollup";
import { clusterById } from "../../data/clusters";
import type { Factory } from "../../types";

const GUJARAT_CENTER: [number, number] = [21.9, 71.9];
const GUJARAT_ZOOM = 7;

function deviationColor(pct: number): string {
  if (pct < 10) return "#22c55e";
  if (pct < 25) return "#f5a524";
  return "#ef4444";
}

interface Props {
  state: StateRollup;
  selectedId: string | null;
  onSelect: (id: string | null) => void;
  factories: Factory[];
  selectedFactoryId: string | null;
  onFactorySelect: (id: string | null) => void;
}

function ClusterFocus({ cluster }: { cluster: ClusterRollup | null }) {
  const map = useMap();
  useEffect(() => {
    if (cluster) map.flyTo([cluster.cluster.lat, cluster.cluster.lon], 12, { duration: 0.85 });
    else map.flyTo(GUJARAT_CENTER, GUJARAT_ZOOM, { duration: 0.85 });
  }, [cluster?.cluster.id]);
  return null;
}

function ResetViewControl({ onReset }: { onReset: () => void }) {
  const map = useMap();
  return (
    <button
      onClick={() => { onReset(); map.flyTo(GUJARAT_CENTER, GUJARAT_ZOOM, { duration: 0.85 }); }}
      className="absolute right-3 top-3 z-[1000] rounded-lg border border-[color:var(--color-border)] bg-[color:var(--color-panel)]/90 px-2.5 py-1.5 text-[11px] text-[color:var(--color-text)] shadow backdrop-blur hover:bg-[color:var(--color-panel-2)]"
      title="Reset map view"
    >
      ⟲ Reset view
    </button>
  );
}

function factoryIcon(index: number, color: string) {
  return divIcon({
    className: "factory-marker-wrap",
    iconSize: [44, 56],
    iconAnchor: [22, 52],
    html: `<div class="factory-marker" style="--build-delay:${index * 95}ms;--factory-glow:${color}"><i></i><b></b><em></em></div>`,
  });
}

export default function ClusterMap({ state, selectedId, onSelect, factories, selectedFactoryId, onFactorySelect }: Props) {
  const max = Math.max(...state.clusters.map((c) => c.avoidableCo2eTpy), 1);
  const selectedCluster = state.clusters.find((c) => c.cluster.id === selectedId) ?? null;
  const clusterFactories = selectedCluster ? factories.filter((f) => f.cluster.startsWith(selectedCluster.cluster.name)) : [];

  // symbiosis lines between clusters (only cross-cluster, aggregated)
  const links = new Map<string, number>();
  for (const m of state.matches) {
    const a = state.clusterOf[m.sourceId];
    const b = state.clusterOf[m.targetId];
    if (!a || !b || a === b) continue;
    const key = [a, b].sort().join("|");
    links.set(key, (links.get(key) ?? 0) + 1);
  }

  return (
    <MapContainer center={GUJARAT_CENTER} zoom={GUJARAT_ZOOM} minZoom={6} maxZoom={14} className="h-full w-full cluster-map" zoomControl={false} attributionControl={false} style={{ background: "#0a0e14" }}>
      <TileLayer url="https://tile.openstreetmap.org/{z}/{x}/{y}.png" />
      <ZoomControl position="bottomright" />
      <ClusterFocus cluster={selectedCluster} />
      <ResetViewControl onReset={() => { onSelect(null); onFactorySelect(null); }} />

      {[...links.entries()].map(([key, n]) => {
        const [a, b] = key.split("|").map((id) => clusterById[id]);
        return <Polyline key={key} positions={[[a.lat, a.lon], [b.lat, b.lon]]} pathOptions={{ color: "#3ea6ff", weight: 1 + n, opacity: 0.45, dashArray: "6 6" }} />;
      })}

      {state.clusters.map((c: ClusterRollup) => {
        const r = 12 + Math.sqrt(c.avoidableCo2eTpy / max) * 26;
        const color = deviationColor(c.avgDeviationPct);
        const sel = selectedId === c.cluster.id;
        return (
          <CircleMarker
            key={c.cluster.id}
            center={[c.cluster.lat, c.cluster.lon]}
            radius={r}
            pathOptions={{ color: sel ? "#ffffff" : color, weight: sel ? 3 : 1.5, fillColor: color, fillOpacity: sel ? 0.6 : 0.35 }}
            eventHandlers={{
              click: () => onSelect(sel ? null : c.cluster.id),
              mouseover: (e) => e.target.setStyle({ fillOpacity: 0.75, weight: 3 }),
              mouseout: (e) => e.target.setStyle({ fillOpacity: sel ? 0.6 : 0.35, weight: sel ? 3 : 1.5 }),
            }}
          >
            <Tooltip direction="top" offset={[0, -r - 4]} opacity={1} sticky>
              <div style={{ fontSize: 12 }}>
                <b>{c.cluster.name}</b> · {c.factories} units
                <br />
                Avoidable {c.avoidableCo2eTpy.toLocaleString("en-IN")} tCO₂e/yr · +{c.avgDeviationPct}% vs benchmark
                <br />
                <span style={{ opacity: 0.75 }}>Click to zoom in for the factory-level view →</span>
              </div>
            </Tooltip>
          </CircleMarker>
        );
      })}

      {/* Always-visible cluster name labels — non-interactive so clicks pass
          through to the CircleMarker beneath; avoids the "which bubble is
          which" problem when several clusters sit close together at the
          zoomed-out view. */}
      {state.clusters.map((c: ClusterRollup) => (
        <Marker
          key={`label-${c.cluster.id}`}
          position={[c.cluster.lat, c.cluster.lon]}
          interactive={false}
          icon={divIcon({
            className: "cluster-name-label",
            html: `<span>${c.cluster.name}</span>`,
            iconSize: [0, 0],
          })}
        />
      ))}

      {clusterFactories.map((f, index) => {
        const hotspot = f.nodes.some((n) => n.severity === "crit");
        const color = hotspot ? "#ef4444" : "#3ea6ff";
        const privateName = `Participant factory ${String(index + 1).padStart(2, "0")} (private)`;
        return (
          <Marker
            key={f.id}
            position={[f.lat, f.lon]}
            icon={factoryIcon(index, color)}
            zIndexOffset={selectedFactoryId === f.id ? 500 : index}
            eventHandlers={{ click: () => onFactorySelect(selectedFactoryId === f.id ? null : f.id) }}
          >
            <Tooltip direction="top" offset={[0, -48]} opacity={1}>
              <div style={{ fontSize: 12 }}>
                <b>{f.consentToShare ? f.name : privateName}</b><br />
                {f.totalCo2eTpy.toLocaleString("en-IN")} tCO₂e/yr · {f.nodes.filter((n) => n.severity === "crit").length} hotspots
              </div>
            </Tooltip>
          </Marker>
        );
      })}
    </MapContainer>
  );
}
