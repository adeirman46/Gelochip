export interface Chat {
  id: string;
  title: string;
  project_id?: string | null;
  created_at: string;
  updated_at: string;
}

export interface MessageFile {
  name: string;
  kind: string; // image | pdf | file
  object_key?: string;
}

export interface Message {
  id: string;
  chat_id: string;
  role: "user" | "assistant" | "system";
  content: string;
  files: MessageFile[];
  created_at: string;
}

export interface Block {
  kind: string; // markdown | code | success | error | image | caption | ...
  payload: any[];
  slot?: string; // live-updating blocks (librelane log tail / stage panel / LLM stream) update in place by slot
}

export interface TranscriptRecord {
  node: string;
  blocks: Block[];
}

export interface RunRef {
  id: string;
  status: string;
  design_dir?: string;
}

export interface KnowledgeStats {
  total: number;
  by_kind: Record<string, number>;
}

// Build constraints (the picker shown on every new chat)
export interface RunConstraints {
  use_web: boolean;
  run_harden: boolean;  // run the Glayout layout + DRC/LVS after the specs pass
  deep_steps: boolean;
  gain_db?: number | null;   // target min gain (dB) — OPTIONAL
  bw_hz?: number | null;     // target min bandwidth / GBW (Hz) — OPTIONAL
  sim_types: string[];       // which analyses to run: any of "dc" | "ac" | "tran"
  num_ctx: number;      // Ollama context window (tokens) — slider sized to GPU VRAM
  model?: string;       // Ollama chat model (picker) — empty/undefined → server default
  // kept for backend compatibility (unused by the analog flow)
  clock_port: string;
  clock_period: number;
  die_um: number;
  core_util: number;
}

// An installed Ollama model (GET /api/system/models) for the model picker.
export interface OllamaModel {
  name: string;
  size: number;            // bytes (tiny for a cloud stub)
  family?: string;
  parameter_size?: string; // e.g. "9.0B"
  cloud?: boolean;         // true → Ollama cloud model (runs on Ollama's servers, not this box)
}

export const DEFAULT_CONSTRAINTS: RunConstraints = {
  use_web: true,
  run_harden: false,
  deep_steps: true,
  gain_db: null,
  bw_hz: null,
  sim_types: ["dc", "ac", "tran"],
  num_ctx: 32768,
  clock_port: "clk",
  clock_period: 24,
  die_um: 600,
  core_util: 25,
};

// Hardware-aware limits for the chat parameters (GET /api/system/caps).
export interface SystemCaps {
  device: string;        // "cuda" | "cpu"
  total_gb: number;      // detected VRAM (cuda) or RAM (cpu)
  num_ctx_min: number;
  num_ctx_max: number;
  num_ctx_step: number;
  num_ctx_default: number;
  model?: string;
}

// --- projects (group many chats / IPs) --------------------------------------
export interface Project {
  id: string;
  name: string;
  chats?: number;
  created_at?: string;
  updated_at?: string;
}

// --- IP library -------------------------------------------------------------
export interface IPPort {
  name: string;
  dir: "input" | "output" | "inout";
  width: string;
}

export interface IP {
  id: string;
  name: string;
  category: string;
  subtitle?: string;
  source?: string;
  top: string;
  ports: IPPort[];
  rtl: string[];
  status: "rtl" | "sim" | "hardening" | "hardened" | "harden_failed";
  metrics?: Record<string, number>;
  gds?: string | null;
  png?: string | null;
  lines?: number;
  tb?: string[];
  sim_status?: "untested" | "no_tb" | "pass" | "fail";
  sim_log?: string;
  tapeout_ready?: boolean;
  signoff?: Record<string, any>;
  files?: Record<string, string>;
}

export interface IPLibraryResponse {
  ips: IP[];
  categories: string[];
  labels: Record<string, string>;
  icons: Record<string, string>;
  counts: Record<string, number>;
}

// --- simulation workspaces --------------------------------------------------
export interface SimWorkspaceMeta {
  id: string;
  name: string;
  files: number;
  updated_at?: string;
}

export interface SimWorkspace {
  id: string;
  name: string;
  files: Record<string, string>;
}

export interface WaveSignal {
  name: string;
  width: number;
  wave: [number, number | null][];
}

export interface Waveform {
  tmax: number;
  signals: WaveSignal[];
}

export interface SimResult {
  ok: boolean;
  compiled: boolean;
  log: string;
  waveform?: Waveform | null;
  vcd?: boolean;
  hint?: string;
  status?: number;   // HTTP status when the request itself failed (e.g. 404 stale workspace)
  gone?: boolean;    // the workspace no longer exists on the server (stale selection)
}

// --- chip studio ------------------------------------------------------------
export interface Padframe {
  image_url: string | null;
  width: number;
  height: number;
  source: string;
}

export interface PlacedBlock {
  uid: string;
  ip_id: string;
  name: string;
  x: number;
  y: number;
  w: number;
  h: number;
  ports: IPPort[];
}

export interface Floorplan {
  id: string;
  name: string;
  placed: PlacedBlock[];
  nets: { from: string; to: string }[];
  updated_at?: string;
}

// SSE event shapes
export type RunEvent =
  | { type: "step"; node: string }
  | { type: "block"; node: string; kind: string; payload: any[] }
  | { type: "block_live"; node: string; slot: string; kind: string; payload: any[] } // in-place update
  | { type: "trim" }                        // drop the trailing partial card (continue re-runs it)
  | { type: "knowledge"; total: number }    // store changed at a meaningful event
  | { type: "end"; status: string };
