// Bricklab web live: the audio thread. Runs live.py (the Brick's engine) and
// keeps a few blocks ready for the worklet. Notes arrive from the render worker.
const PYODIDE = "https://cdn.jsdelivr.net/pyodide/v0.28.3/full/";
importScripts(PYODIDE + "pyodide.js");
let py, L, out = null, produced = 0, used = 0, under = 0, ahead = 3 * 512, busy = false;

async function boot(files) {
  py = await loadPyodide({ indexURL: PYODIDE });
  await py.loadPackage("numpy");
  for (const f of files) {
    const dest = "/app/" + f.replace(/^py\//, "");
    py.FS.mkdirTree(dest.slice(0, dest.lastIndexOf("/")));
    py.FS.writeFile(dest, new Uint8Array(await (await fetch(f, { cache: "no-cache" })).arrayBuffer()));
  }
  py.FS.mkdirTree("/app/samples");
  py.runPython('import sys; sys.path.insert(0, "/app")\nimport json, numpy as np, live\nL = live.Live()');
  L = py.globals.get("L");
}

function fill() {                     // keep `ahead` frames queued in the worklet
  if (!out || busy || !L) return;
  busy = true;
  try {
    while (produced - used < ahead) {
      const pb = L.block(), blk = pb.toJs(); pb.destroy();
      produced += blk.length >> 1;
      out.postMessage(blk, [blk.buffer]);
    }
  } finally { busy = false; }
}

self.onmessage = async (ev) => {
  const { id, op, arg } = ev.data;
  try {
    let r = null;
    if (op === "init") { await boot(arg.files); r = JSON.parse(L.names()); }
    else if (op === "out") { out = ev.ports[0]; out.onmessage = (m) => { used = m.data.used; under = m.data.under; fill(); }; fill(); }
    else if (op === "notes") { const p = ev.ports[0]; p.onmessage = (m) => { const d = m.data;
        L.add_note(d.sound, d.midi, py.toPy(d.a), d.la, py.toPy(d.l), d.ll); }; }
    else if (op === "sound") { const w = L.wanted(); r = { pj: L.set_sound(arg.i), wanted: w.toJs() }; w.destroy(); }
    else if (op === "key") { L.set_key(arg.key, arg.scale); const w = L.wanted(); r = { names: JSON.parse(L.names()).chords[0], wanted: w.toJs() }; w.destroy(); }
    else if (op === "exact") { r = JSON.parse(L.chord_exact(JSON.stringify(arg.notes))); fill(); }
    else if (op === "chord") { r = JSON.parse(L.chord(arg.degree, JSON.stringify(arg.mods || {}))); fill(); }
    else if (op === "release") { L.release(); }
    else if (op === "mode") { L.set_mode(arg.mode); }
    else if (op === "lead") { r = JSON.parse(L.lead_on(arg.degree, !!arg.up, !!arg.down, !!arg.sharp)); fill(); }
    else if (op === "lead_off") { L.lead_off(); }
    else if (op === "lead_mod") { L.lead_mod(arg.bend, arg.vib); }
    else if (op === "drone") { r = JSON.parse(L.drone(arg.degree, !!arg.third)); fill(); }
    else if (op === "drone_off") { L.drone_off(); }
    else if (op === "drone_mod") { L.drone_mod(arg.x, arg.y); }
    else if (op === "chord_mod") { r = L.chord_mod(arg.x, arg.y); r = r === undefined ? null : r; }
    else if (op === "right") { L.right_stick(arg.x, arg.y); }
    else if (op === "fx") { L.set_fx(arg.name, !!arg.on, arg.amount, arg.rate); }
    else if (op === "space") { L.set_space(arg.rev, arg.dly, arg.time, arg.vol); }
    else if (op === "bass") { L.set_bass(arg.mode); }
    else if (op === "beat") { L.beat(arg.on, arg.i, arg.bpm); }
    else if (op === "ahead") { ahead = arg.frames; }
    else if (op === "stats") { r = { buffered: produced - used, under }; }
    self.postMessage({ id, ok: true, r });
  } catch (e) { self.postMessage({ id, ok: false, err: String(e && e.message || e) }); }
};
