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
  py.runPython('import sys; sys.path.insert(0, "/app")\nimport json, live');
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
    if (op === "init") { await boot(arg.files); toAudio = ev.ports[0]; }
    else if (op === "render") { job++; run(job, arg.sound, arg.pj, arg.midis); }
    self.postMessage({ id, ok: true });
  } catch (e) { self.postMessage({ id, ok: false, err: String(e && e.message || e) }); }
};
