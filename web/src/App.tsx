import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import CodeMirror from "@uiw/react-codemirror";
import { json } from "@codemirror/lang-json";
import Viewport from "./Viewport";
import { api, runJob } from "./api";
import type { BuildInfo, BuildSummary, Grid, Photo, RunEvent, Status } from "./api";

type Line = { kind: "text" | "tool" | "ok" | "err" | "warn" | "info"; text: string };

function readPhoto(file: File): Promise<Photo> {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => {
      const url = r.result as string;
      resolve({ name: file.name, data: url.slice(url.indexOf(",") + 1), url });
    };
    r.onerror = reject;
    r.readAsDataURL(file);
  });
}

export default function App() {
  const [status, setStatus] = useState<Status | null>(null);
  const [builds, setBuilds] = useState<BuildSummary[]>([]);
  const [name, setName] = useState<string>("");
  const [info, setInfo] = useState<BuildInfo | null>(null);
  const [grid, setGrid] = useState<Grid | null>(null);
  const [layer, setLayer] = useState(255);
  const [stats, setStats] = useState(false);
  const [running, setRunning] = useState(false);
  const [feed, setFeed] = useState<Line[]>([]);
  const [error, setError] = useState<string | null>(null);
  // new build
  const [newName, setNewName] = useState("");
  const [prompt, setPrompt] = useState("");
  const [photos, setPhotos] = useState<Photo[]>([]);
  const [budget, setBudget] = useState("default");
  const [critique, setCritique] = useState(2);
  // edit
  const [instruction, setInstruction] = useState("");
  const [render, setRender] = useState(false);
  // ops editor
  const [text, setText] = useState("");
  const [tab, setTab] = useState<"ops" | "issues" | "blocks">("ops");
  const feedRef = useRef<HTMLDivElement>(null);

  const refreshBuilds = useCallback(() => api.builds().then(setBuilds).catch((e) => setError(String(e))), []);
  const load = useCallback(async (n: string) => {
    setName(n);
    setError(null);
    try {
      const [i, g] = await Promise.all([api.build(n), api.grid(n)]);
      setInfo(i);
      setText(i.ops);
      setGrid(g);
      setLayer(g.size[1]);
    } catch (e) {
      setError(String((e as Error).message));
    }
  }, []);

  useEffect(() => {
    api.status().then(setStatus).catch((e) => setError(String(e)));
    refreshBuilds();
    const onKey = (e: KeyboardEvent) => { if (e.shiftKey && e.key === "P") setStats((s) => !s); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [refreshBuilds]);
  useEffect(() => { feedRef.current?.scrollTo(0, feedRef.current.scrollHeight); }, [feed]);

  const log = (l: Line) => setFeed((f) => {
    // stream text into the last text line instead of one line per token
    if (l.kind === "text" && f.length && f[f.length - 1].kind === "text") {
      return [...f.slice(0, -1), { kind: "text", text: f[f.length - 1].text + l.text }];
    }
    return [...f, l];
  });

  const onEvent = (e: RunEvent) => {
    switch (e.type) {
      case "started": log({ kind: "info", text: `${e.action === "edit" ? "Editing" : "Designing"} with ${e.model} (budget ${e.budget})` }); break;
      case "text": case "thinking": if (e.text) log({ kind: "text", text: e.text }); break;
      case "tool": break;
      case "applied": log(e.ok ? { kind: "tool", text: `${e.tool}${e.id ? ` ${e.id}` : ""}` }
        : { kind: "err", text: `${e.tool}${e.id ? ` ${e.id}` : ""}: ${e.error}` }); break;
      case "grid": setGrid(e.grid); setLayer(e.grid.size[1]); break;
      case "critique": log({ kind: "info", text: `Critique pass ${e.n}: comparing the build with the photo` }); break;
      case "warning": log({ kind: "warn", text: e.message }); break;
      case "done":
        log({ kind: "ok", text: `${e.stopped} after ${e.turns} turns, $${e.cost_usd.toFixed(2)}` +
          (e.version ? ` - version ${e.version}` : " - no change") });
        if (e.summary) log({ kind: "text", text: e.summary });
        break;
      case "exported": log({ kind: "ok", text: e.load ? `Copied to WorldEdit: ${e.load}, then //paste -a`
        : `Saved ${e.schematic}` }); break;
      case "error": log({ kind: "err", text: e.message }); break;
    }
  };

  const run = async (msg: Record<string, unknown>, target: string) => {
    setRunning(true);
    setError(null);
    setFeed([]);
    await runJob(msg, onEvent);
    setRunning(false);
    await refreshBuilds();
    await load(target).catch(() => undefined);
  };

  const design = () => {
    const n = newName.trim() || "design";
    run({ action: "design", name: n, prompt, budget, photos: photos.map(({ name, data }) => ({ name, data })),
      critique: photos.length ? critique : 0 }, n);
  };
  const edit = () => run({ action: "edit", name, instruction, budget, render }, name);

  const act = async (f: () => Promise<BuildInfo>) => {
    try { const i = await f(); setInfo(i); setText(i.ops); setGrid(await api.grid(i.name)); setError(null); }
    catch (e) { setError((e as Error).message); }
  };
  const exportNow = async () => {
    try {
      const r = await api.exportBuild(name);
      log({ kind: "ok", text: r.load ? `Copied to WorldEdit: ${r.load}, then //paste -a` : "Compiled (no WorldEdit folder)" });
    } catch (e) { setError((e as Error).message); }
  };

  const dirty = info !== null && text !== info.ops;
  const onDrop = async (files: FileList | null) => {
    if (!files) return;
    const list = await Promise.all([...files].filter((f) => f.type.startsWith("image/")).map(readPhoto));
    setPhotos((p) => [...p, ...list]);
  };
  const height = grid?.size[1] ?? 0;
  const issues = info?.issues.filter((i) => i.severity !== "info") ?? [];
  const counts = useMemo(() => Object.entries(grid?.counts ?? {}), [grid]);

  return (
    <div className="app">
      <aside className="left">
        <header>
          <h1>img2schem</h1>
          {status && <div className="badges">
            <span className={status.api_key ? "ok" : "bad"}>{status.api_key ? "API key" : "no API key"}</span>
            <span className={status.worldedit ? "ok" : "bad"}>{status.worldedit ? "WorldEdit" : "no WorldEdit"}</span>
            <span className={status.palette ? "ok" : "bad"}>{status.palette ? "palette" : "no palette"}</span>
          </div>}
        </header>

        <section>
          <h2>New build</h2>
          <input placeholder="name (e.g. villa)" value={newName} onChange={(e) => setNewName(e.target.value)} />
          <textarea rows={3} placeholder={photos.length ? "Notes (optional)" : "Describe the build..."}
            value={prompt} onChange={(e) => setPrompt(e.target.value)} />
          <label className="drop" onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => { e.preventDefault(); onDrop(e.dataTransfer.files); }}>
            <input type="file" accept="image/*" multiple hidden onChange={(e) => onDrop(e.target.files)} />
            {photos.length ? photos.map((p, i) => <img key={i} src={p.url} alt={p.name} title={p.name} />)
              : <span>Drop a photo here, or click to choose</span>}
          </label>
          {photos.length > 0 && <button className="link" onClick={() => setPhotos([])}>clear photos</button>}
          <div className="row">
            <select value={budget} onChange={(e) => setBudget(e.target.value)}>
              {Object.entries(status?.budgets ?? { default: { warn: 1, stop: 5 } }).map(([k, b]) =>
                <option key={k} value={k}>{k}: ${b.warn} / ${b.stop}</option>)}
            </select>
            {photos.length > 0 && <label>critique <input type="number" min={0} max={4} value={critique}
              onChange={(e) => setCritique(Number(e.target.value))} /></label>}
            <button disabled={running || (!prompt.trim() && !photos.length)} onClick={design}>Design</button>
          </div>
        </section>

        <section>
          <h2>Builds</h2>
          <ul className="builds">
            {builds.map((b) => <li key={b.name} className={b.name === name ? "sel" : ""}
              onClick={() => load(b.name)}>{b.name}<small>v{b.current} · ${b.cost_usd.toFixed(2)}</small></li>)}
            {!builds.length && <li className="muted">none yet</li>}
          </ul>
        </section>

        {name && <section>
          <h2>Revise {name}</h2>
          <textarea rows={2} placeholder='e.g. "make the roof steeper"' value={instruction}
            onChange={(e) => setInstruction(e.target.value)} />
          <div className="row">
            <label><input type="checkbox" checked={render} onChange={(e) => setRender(e.target.checked)} /> renders</label>
            <button disabled={running || !instruction.trim()} onClick={edit}>Apply</button>
          </div>
          <div className="row">
            <button disabled={running || !info || info.current <= 1} onClick={() => act(() => api.step(name, "undo"))}>Undo</button>
            <button disabled={running || !info || info.current >= info.versions.length} onClick={() => act(() => api.step(name, "redo"))}>Redo</button>
            <button disabled={running} onClick={exportNow}>To WorldEdit</button>
          </div>
          <ol className="history">
            {info?.versions.map((v) => <li key={v.n} className={v.n === info.current ? "sel" : ""} title={v.summary}>
              <b>v{v.n}</b> {v.kind}: {v.instruction}{v.cost_usd ? <small> ${v.cost_usd.toFixed(2)}</small> : null}
            </li>)}
          </ol>
        </section>}

        <section className="feed" ref={feedRef}>
          {feed.map((l, i) => <div key={i} className={l.kind}>{l.text}</div>)}
          {running && <div className="info">working...</div>}
        </section>
      </aside>

      <main>
        <Viewport grid={grid} layer={layer} stats={stats} frame={name} />
        {grid && <div className="overlay">
          <span>{grid.size.join(" x ")} · {grid.total} blocks</span>
          <label>layer <input type="range" min={0} max={Math.max(0, height - 1)} value={Math.min(layer, height)}
            onChange={(e) => setLayer(Number(e.target.value))} /> {Math.min(layer, height - 1)}</label>
        </div>}
        {error && <div className="error" onClick={() => setError(null)}>{error}</div>}
      </main>

      <aside className="right">
        <nav>
          <button className={tab === "ops" ? "sel" : ""} onClick={() => setTab("ops")}>ops.json{dirty ? " *" : ""}</button>
          <button className={tab === "issues" ? "sel" : ""} onClick={() => setTab("issues")}>Issues ({issues.length})</button>
          <button className={tab === "blocks" ? "sel" : ""} onClick={() => setTab("blocks")}>Blocks</button>
        </nav>
        {tab === "ops" && <div className="editor">
          <CodeMirror value={text} height="100%" theme="dark" extensions={[json()]} onChange={setText}
            onKeyDown={(e) => { if ((e.ctrlKey || e.metaKey) && e.key === "s") { e.preventDefault(); if (dirty) act(() => api.save(name, text)); } }} />
          <div className="row">
            <button disabled={!dirty || running} onClick={() => act(() => api.save(name, text))}>Save (Ctrl+S)</button>
            <button disabled={!dirty} onClick={() => info && setText(info.ops)}>Revert</button>
          </div>
        </div>}
        {tab === "issues" && <ul className="issues">
          {issues.map((i, k) => <li key={k} className={i.severity}><b>{i.rule}</b> {i.message}</li>)}
          {!issues.length && <li className="muted">no issues</li>}
        </ul>}
        {tab === "blocks" && <table className="counts"><tbody>
          {counts.map(([b, n]) => <tr key={b}><td>{b}</td><td>{n}</td><td>{Math.floor(n / 64)} st + {n % 64}</td></tr>)}
        </tbody></table>}
      </aside>
    </div>
  );
}
