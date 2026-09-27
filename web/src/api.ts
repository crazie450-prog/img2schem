// The img2schem server's API (img2schem/server/app.py).

export type Box = [number, number, number, number, number, number];
export interface BlockEntry { name: string; shape?: string; color?: string; opacity?: number; parts?: Box[] | null;
  state?: string }
// cells: x, y, z, block (index into blocks), op (index into ops, -1 for none) per visible cell. A cell's design
// coordinates (the ones ops use) are x, y, z minus origin.
export interface Grid { size: [number, number, number]; blocks: BlockEntry[]; cells: number[]; total: number;
  counts: Record<string, number>; ops: { id: string; label: string }[]; origin: [number, number, number] }
export const CELL = 5;
export interface Version { n: number; kind: string; instruction?: string; cost_usd?: number; time?: string;
  summary?: string }
export interface Issue { rule: string; severity: string; message: string; pos?: number[] | null }
export interface BuildInfo { name: string; ops: string; current: number; versions: Version[]; cost_usd: number;
  issues: Issue[] }
export interface BuildSummary { name: string; current: number; versions: number; cost_usd: number; updated: number }
export interface Status { model: string; budgets: Record<string, { warn: number; stop: number }>; api_key: boolean;
  instance: string | null; worldedit: boolean; world: string | null; palette: boolean }

// Events streamed while Claude designs or edits.
export type RunEvent =
  | { type: "started"; action: string; model: string; budget: string }
  | { type: "text" | "thinking" | "tool"; text: string }
  | { type: "applied"; tool: string; id: string | null; ok: boolean; error: string | null }
  | { type: "grid"; grid: Grid }
  | { type: "critique"; n: number }
  | { type: "warning"; message: string }
  | { type: "done"; stopped: string; turns: number; cost_usd: number; summary: string | null;
      version: number | null; warnings: string[] }
  | { type: "exported"; schematic: string; copied_to: string | null; load: string | null; blocks: number }
  | { type: "stopping" }
  | { type: "error"; message: string };

async function call<T>(method: string, url: string, body?: unknown): Promise<T> {
  const res = await fetch(url, {
    method,
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const d = (data as { detail?: unknown }).detail;
    const msg = typeof d === "string" ? d : (d as { message?: string })?.message ?? res.statusText;
    const line = (d as { line?: number })?.line;
    throw new Error(line ? `${msg} (line ${line})` : msg);
  }
  return data as T;
}

export const api = {
  status: () => call<Status>("GET", "/api/status"),
  builds: () => call<BuildSummary[]>("GET", "/api/builds"),
  build: (name: string) => call<BuildInfo>("GET", `/api/builds/${name}`),
  grid: (name: string, hide: string[] = []) =>
    call<Grid>("GET", `/api/builds/${name}/grid${hide.length ? `?hide=${encodeURIComponent(hide.join(","))}` : ""}`),
  save: (name: string, text: string, instruction?: string) =>
    call<BuildInfo>("PUT", `/api/builds/${name}/ops`, instruction ? { text, instruction } : { text }),
  step: (name: string, step: "undo" | "redo") => call<BuildInfo>("POST", `/api/builds/${name}/${step}`),
  exportBuild: (name: string) => call<{ copied_to: string | null; load: string | null; blocks: number }>(
    "POST", `/api/builds/${name}/export`),
};

export interface Photo { name: string; data: string; url: string }

export interface Job { done: Promise<void>; stop: () => void }

// Run a design or edit; calls onEvent for each streamed event. `done` resolves when the run ends; `stop` asks the
// server to stop after the turn in flight (what was built so far is kept as a version).
export function runJob(msg: Record<string, unknown>, onEvent: (e: RunEvent) => void): Job {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/api/ws`);
  const stop = () => { if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ action: "stop" })); };
  const done = new Promise<void>((resolve) => {
    let finished = false;
    let sawDone = false;
    ws.onopen = () => ws.send(JSON.stringify(msg));
    ws.onmessage = (m) => {
      const e = JSON.parse(m.data) as RunEvent;
      onEvent(e);
      if (e.type === "done") sawDone = true;
      // after "done" an "exported" (or a warning) follows when a version was made
      const last = e.type === "error" || e.type === "exported" || (e.type === "done" && e.version === null) ||
        (sawDone && e.type === "warning");
      if (last && !finished) { finished = true; ws.close(); resolve(); }
    };
    ws.onclose = () => {
      if (finished) return;
      finished = true;
      onEvent({ type: "error", message: "Lost the connection to the img2schem server (its WebSocket). If this "
        + "happens at once, run: pip install -e \".[vlm,server]\" and restart img2schem serve." });
      resolve();
    };
  });
  return { done, stop };
}
