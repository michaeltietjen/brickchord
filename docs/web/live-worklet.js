// Bricklab web live: plays the engine's blocks as they arrive. The engine runs
// at 22050 Hz; if the device runs at another rate this resamples (linear).
// Tells the audio worker how many engine frames it has used, so the worker
// keeps a small cushion ready and no more (that cushion is the delay you feel).
class BrickOut extends AudioWorkletProcessor {
  constructor() {
    super();
    this.q = [];          // interleaved L R blocks
    this.pos = 0;         // fractional read position in q[0] (frames)
    this.used = 0;        // engine frames consumed
    this.under = 0;
    this.ratio = 22050 / sampleRate;
    this.port.onmessage = (e) => {
      if (e.data.port) { this.eng = e.data.port; this.eng.onmessage = (m) => this.q.push(m.data); }
    };
    this.tick = 0;
  }
  frame(i) {               // engine frame i (relative to the head of the queue), L and R
    let b = 0;
    while (b < this.q.length) {
      const n = this.q[b].length >> 1;
      if (i < n) return [this.q[b][2 * i], this.q[b][2 * i + 1]];
      i -= n; b++;
    }
    return null;
  }
  process(_, outputs) {
    const L = outputs[0][0], R = outputs[0][1] || outputs[0][0];
    for (let k = 0; k < L.length; k++) {
      const i = Math.floor(this.pos), f = this.pos - i;
      const a = this.frame(i), b = this.frame(i + 1);
      if (!a || !b) { L[k] = 0; R[k] = 0; if (this.q.length === 0 && this.started) this.under++; continue; }
      this.started = true;
      L[k] = a[0] + (b[0] - a[0]) * f; R[k] = a[1] + (b[1] - a[1]) * f;
      this.pos += this.ratio;
      while (this.q.length && this.pos >= (this.q[0].length >> 1)) { const n = this.q[0].length >> 1; this.pos -= n; this.used += n; this.q.shift(); }
    }
    if (this.eng && (++this.tick & 3) === 0) this.eng.postMessage({ used: this.used + Math.floor(this.pos), under: this.under });
    return true;
  }
}
registerProcessor("brick-out", BrickOut);
