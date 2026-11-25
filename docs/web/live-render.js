// Bricklab web live: the note renderer. Renders a sound's notes one at a time
// (the likely ones first) and hands each to the audio thread. A new sound
// cancels the old queue. Rendering here keeps the audio thread from stalling.
const PYODIDE = "https://cdn.jsdelivr.net/pyodide/v0.28.3/full/";
importScripts(PYODIDE + "pyodide.js");
let py, toAudio = null, job = 0;

async function boot(files) {
  py = await loadPyodide({ indexURL: PYODIDE });
  await py.loadPackage("numpy");
  for (const f of files) {
    const dest = "/app/" + f.replace(/^py\//, "");
    py.FS.mkdirTree(dest.slice(0, dest.lastIndexOf("/")));
    py.FS.writeFile(dest, new Uint8Array(await (await fetch(f, { cache: "no-cache" })).arrayBuffer()));
  }
  py.runPython('import sys; sys.path.insert(0, "/app")\nimport json, live, engine, numpy as np\n'
    + 'def pluck(i, m):\n    return np.ascontiguousarray(engine.pluck_note(int(i), int(m), 22050), np.float32).ravel()');
}

// Brickglide: the voices' sounds first, then the strum notes, one at a time.
let gNotes = [], gPlucks = [], gInst = null, gBusy = false;
async function glideWork() {
  if (gBusy) return;
  gBusy = true;
  try {
    while (gNotes.length || gPlucks.length) {
      if (gNotes.length) {
        const [kid, midi, pj] = gNotes.shift();
        const r = py.globals.get("live").render_note(midi, pj);
        const [a, la, l, ll] = r.toJs(); r.destroy();
        toAudio.postMessage({ kind: "amb", kid, a, la, l, ll }, [a.buffer, l.buffer]);
      } else {
        const m = gPlucks.shift(), inst = gInst;
        const r = py.globals.get("pluck")(inst, m), mono = r.toJs(); r.destroy();
        toAudio.postMessage({ kind: "pluck", inst, midi: m, mono }, [mono.buffer]);
      }
      await new Promise((res) => setTimeout(res, 0));
    }
  } finally { gBusy = false; }
}
function glideJobs(w) {
  gNotes.push(...w.notes);
  if (w.inst !== gInst) { gInst = w.inst; gPlucks = []; }
  if (w.plucks.length) gPlucks = [...w.plucks, ...gPlucks.filter(m => !w.plucks.includes(m))];
  glideWork();
}

async function run(my, sound, pj, midis) {
  const render = py.globals.get("live").render_note;
  for (let k = 0; k < midis.length; k++) {
    if (my !== job) return;
    const r = render(midis[k], pj);
    const [a, la, l, ll] = r.toJs(); r.destroy();
    toAudio.postMessage({ sound, midi: midis[k], a, la, l, ll }, [a.buffer, l.buffer]);
    self.postMessage({ progress: { sound, done: k + 1, total: midis.length } });
    await new Promise((res) => setTimeout(res, 0));     // let a newer request in
  }
}

self.onmessage = async (ev) => {
  const { id, op, arg } = ev.data;
  try {
    if (op === "init") { await boot(arg.files); toAudio = ev.ports[0]; toAudio.onmessage = (m) => { if (m.data.glide) glideJobs(m.data.glide); }; }
    else if (op === "render") { job++; run(job, arg.sound, arg.pj, arg.midis); }
    self.postMessage({ id, ok: true });
  } catch (e) { self.postMessage({ id, ok: false, err: String(e && e.message || e) }); }
};
