export type Severity = "ok" | "warn" | "crit";

export type Confidence = "high" | "medium" | "low";

export interface Intervention {
  id: string;
  title: string;
  category: "material-substitution" | "waste-to-input" | "recycling-loop" | "process-change" | "heat-recovery";
  capexInr: number;
  annualSavingInr: number;
  co2ReductionTpy: number; // tonnes CO2e per year
  paybackMonths: number;
  confidence: Confidence;
  description: string;
  /** optional lift to the site circularity ratio (0-1) for recycling/waste-to-input measures */
  circularityGainPct?: number;
  /** whether the user has persisted this as actually implemented (backend recommendations.applied) */
  applied?: boolean;
}

export interface ProcessNode {
  id: string;
  label: string;
  kind: "kiln" | "boiler" | "compressor" | "dryer" | "effluent" | "furnace" | "generic";
  position: [number, number, number];
  scale: [number, number, number];
  co2eTpy: number; // this process's annual CO2e
  shareOfTotal: number; // 0-1
  benchmarkIntensity: number; // sector benchmark, kgCO2e/tonne output
  actualIntensity: number; // this factory's actual, kgCO2e/tonne output
  severity: Severity;
  confidence: Confidence;
  rootCause: string;
  interventions: Intervention[];
  /** optional monthly series (from CSV intake) with z-score anomaly flags */
  monthly?: MonthlyPoint[];
}

export interface MonthlyPoint {
  month: string; // YYYY-MM
  co2eT: number;
  z: number;
  anomaly: boolean;
}

export interface Factory {
  id: string;
  name: string;
  sector: string;
  cluster: string; // e.g. Morbi, Vapi
  outputTonnesPerMonth: number;
  totalCo2eTpy: number;
  totalEnergyMwhPerYear: number;
  totalWasteTpy: number;
  circularityRatio: number; // 0-1
  /** Best single recommendation per process, summed — not fabricated, from the backend. */
  avoidableCo2eTpy?: number;
  /** Illustrative CCTS-indicative valuation of avoidableCo2eTpy — always is_placeholder. */
  carbonCreditValueInrPerYear?: number;
  carbonCreditIsPlaceholder?: boolean;
  carbonCreditNote?: string;
  dataSource: "synthetic" | "self-reported" | "verified";
  nodes: ProcessNode[];
  lat: number;
  lon: number;
  /** waste streams this factory generates (candidate symbiosis outputs) */
  wasteStreams: WasteStream[];
  /** material inputs this factory could accept from another unit's waste */
  acceptedInputs: AcceptedInput[];
  /** intervention ids already implemented (feeds regulator uptake %) */
  implementedInterventionIds: string[];
  /** factory consents to being named in symbiosis matches / regulator drill-downs */
  consentToShare: boolean;
  /** Original intake values, retained so a self-reported factory can be revised later. */
  intakeProfile?: {
    clusterId: string;
    sector: string;
    subSector: string;
    outputTonnesPerMonth: number;
    wasteTpy: number;
    recoveredTpy: number;
  };
  sourceActivities?: { process: string; fuel: string; quantity: number; unit: string; month?: string }[];
  /** Per-process placement captured by the layout editor for the schematic twin. */
  layoutOverrides?: Record<string, [number, number, number]>;
}

export interface WasteStream {
  tag: string; // e.g. "ceramic_sludge"
  label: string;
  tpy: number;
  form: "solid" | "liquid" | "heat";
  /** what it costs today to dispose of it, ₹/t */
  disposalCostInrPerT: number;
}

export interface AcceptedInput {
  tag: string;
  label: string;
  maxTpy: number;
  /** what the virgin equivalent costs, ₹/t */
  virginCostInrPerT: number;
}
