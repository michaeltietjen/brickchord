// Bricklab web: the engine thread. Loads Python (Pyodide) with NumPy and the
// Brick's own engine.py, synth.py and songrender.py, then answers the page:
//   init                      -> {catalog}
//   patch {machine,i,smp}     -> {pj, name}
//   sample {name, bytes}      -> {samples}   (adds a WAV to the sample folder)
//   render {song, secs, tail} -> {left, right, sr}
const PYODIDE = "https://cdn.jsdelivr.net/pyodide/v0.28.3/full/";
importScripts(PYODIDE + "pyodide.js");
let py = null;

async function boot() {
  py = await loadPyodide({ indexURL: PYODIDE });
  await py.loadPackage("numpy");
  const man = await (await fetch("manifest.json", { cache: "no-cache" })).json();
  for (const f of man.files) {
    const dest = "/app/" + f.replace(/^py\//, "");
    py.FS.mkdirTree(dest.slice(0, dest.lastIndexOf("/")));
    const buf = new Uint8Array(await (await fetch(f, { cache: "no-cache" })).arrayBuffer());
    py.FS.writeFile(dest, buf);
  }
  py.FS.mkdirTree("/app/samples");
  py.runPython('import sys; sys.path.insert(0, "/app")\nimport json, numpy as np, songrender');
  return JSON.parse(py.runPython("songrender.catalog()"));
}

function call(code, vars) {
  const g = py.globals;
  for (const [k, v] of Object.entries(vars || {})) g.set(k, v);
  return py.runPython(code);
}

self.onmessage = async (ev) => {
  const { id, op, arg } = ev.data;
  try {
    let out;
    if (op === "init") {
      out = { catalog: await boot(), version: man_version() };
    } else if (op === "patch") {
      const r = call("json.dumps(songrender.patch_json(mc, int(i), 0.0, 0.0, json.loads(smp)))",
                     { mc: arg.machine, i: arg.i, smp: JSON.stringify(arg.smp || {}) });
      const [pj, name] = JSON.parse(r);
      out = { pj, name };
    } else if (op === "sample") {
      py.FS.writeFile("/app/samples/" + arg.name, new Uint8Array(arg.bytes));
      call("songrender.forget_samples()");
      out = { catalog: JSON.parse(call("songrender.catalog()")) };
    } else if (op === "render") {
      const t0 = performance.now();
      // a JS null reaches Python as JsNull, not None: send -1 for "the whole song"
      call("_a = songrender.render(json.loads(src), None if float(secs) < 0 else float(secs), tail=float(tail))\n" +
           "_L = np.ascontiguousarray(_a[:, 0], dtype=np.float32)\n_R = np.ascontiguousarray(_a[:, 1], dtype=np.float32)",
           { src: JSON.stringify(arg.song), secs: arg.secs ?? -1, tail: arg.tail ?? 2.0 });
      const L = py.globals.get("_L").toJs(), R = py.globals.get("_R").toJs();
      out = { left: L, right: R, sr: 22050, ms: Math.round(performance.now() - t0) };
      self.postMessage({ id, ok: true, out }, [L.buffer, R.buffer]);
      return;
    }
    self.postMessage({ id, ok: true, out });
  } catch (e) {
    self.postMessage({ id, ok: false, err: String(e && e.message || e) });
  }
};

function man_version() { return "0.1"; }
