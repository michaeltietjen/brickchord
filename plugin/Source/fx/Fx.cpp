// See Fx.h. The granular engine runs at 32 kHz and is brought to the host's rate here; the strings
// run at the host's rate with their tuning corrected for it.
#include "Fx.h"
#include "clouds/dsp/granular_processor.h"
#include "rings/dsp/part.h"
#include <cmath>
#include <cstring>

namespace brick {

static inline float herm(const float* h, float f) {
    float c1 = 0.5f * (h[2] - h[0]), c2 = h[0] - 2.5f * h[1] + 2.0f * h[2] - 0.5f * h[3], c3 = 0.5f * (h[3] - h[0]) + 1.5f * (h[1] - h[2]);
    return ((c3 * f + c2) * f + c1) * f + h[1];
}

// A stereo stream made in blocks at one rate and read at another.
struct Bus {
    double ratio = 1, frac = 0;
    float h[2][4] = {{0, 0, 0, 0}, {0, 0, 0, 0}};
    float blk[2][32]; int bi = 0, bn = 0;
    template <class Fill> void read(Fill&& fill, float* L, float* R, int n, float gain) {
        for (int i = 0; i < n; i++) {
            while (frac >= 1.0) {
                if (bi >= bn) { bn = fill(blk[0], blk[1]); bi = 0; }
                for (int c = 0; c < 2; c++) { h[c][0] = h[c][1]; h[c][1] = h[c][2]; h[c][2] = h[c][3]; h[c][3] = blk[c][bi]; }
                bi++; frac -= 1.0;
            }
            L[i] += gain * herm(h[0], (float) frac); R[i] += gain * herm(h[1], (float) frac);
            frac += ratio;
        }
    }
};

struct Cloud::Impl {
    clouds::GranularProcessor g;
    uint8_t* large = nullptr; uint8_t* small = nullptr;
    double step = 1.5, t = 0;                    // host samples per 32 kHz sample
    float hin[2][4] = {{0, 0, 0, 0}, {0, 0, 0, 0}}, lp[2][2] = {{0, 0}, {0, 0}}, a = 1;
    clouds::ShortFrame in[32] = {}, out[32] = {}; int nin = 0;
    float fifo[2][256] = {}; int w = 0, r = 0, have = 0;
    Bus up;
    Impl() {
        large = new uint8_t[118784]; small = new uint8_t[65536 - 128];
        std::memset(large, 0, 118784); std::memset(small, 0, 65536 - 128);
        std::memset((void*) &g, 0, sizeof(g));
        g.Init(large, 118784, small, 65536 - 128);
        g.set_num_channels(2); g.set_low_fidelity(false); g.set_playback_mode(clouds::PLAYBACK_MODE_GRANULAR);
        clouds::Parameters* p = g.mutable_parameters();
        std::memset(p, 0, sizeof(*p));
        p->position = 0.3f; p->size = 0.5f; p->density = 0.7f; p->texture = 0.6f; p->dry_wet = 1.0f; p->stereo_spread = 0.6f;
        g.Prepare();
        for (int i = 0; i < 96; i++) push(0, 0);
    }
    ~Impl() { delete[] large; delete[] small; }
    void push(float l, float rr) { if (have < 256) { fifo[0][w] = l; fifo[1][w] = rr; w = (w + 1) & 255; have++; } }
};

Cloud::Cloud() : d(new Impl) {}
Cloud::~Cloud() {}
void Cloud::prepare(double sampleRate) {
    if (sampleRate < 8000) sampleRate = 48000;
    d->step = sampleRate / 32000.0; d->up.ratio = 32000.0 / sampleRate;
    float fc = 13500.0f;
    d->a = fc >= sampleRate * 0.45 ? 1.0f : 1.0f - (float) std::exp(-6.283185307179586 * fc / sampleRate);
}
void Cloud::set(float position, float size, float pitchOct, float density, float texture, float spread, float feedback, float reverb) {
    clouds::Parameters* p = d->g.mutable_parameters();
    auto c = [](float x) { return x < 0 ? 0.0f : (x > 1 ? 1.0f : x); };
    p->position = c(position); p->size = c(size); p->pitch = 12.0f * (pitchOct < -2 ? -2 : (pitchOct > 2 ? 2 : pitchOct));
    p->density = c(density); p->texture = c(texture); p->stereo_spread = c(spread); p->feedback = c(feedback); p->reverb = c(reverb);
    p->dry_wet = 1.0f; p->freeze = false; p->trigger = false; p->gate = false;
}
void Cloud::process(const float* inL, const float* inR, float* outL, float* outR, int n, float gain) {
    Impl& s = *d;
    for (int i = 0; i < n; i++) {
        const float x[2] = {inL[i], inR[i]};
        for (int c = 0; c < 2; c++) {
            s.lp[c][0] += s.a * (x[c] - s.lp[c][0]); s.lp[c][1] += s.a * (s.lp[c][0] - s.lp[c][1]);
            s.hin[c][0] = s.hin[c][1]; s.hin[c][1] = s.hin[c][2]; s.hin[c][2] = s.hin[c][3]; s.hin[c][3] = s.lp[c][1];
        }
        while (s.t < 1.0) {
            float l = herm(s.hin[0], (float) s.t), r = herm(s.hin[1], (float) s.t);
            l = l < -1 ? -1 : (l > 1 ? 1 : l); r = r < -1 ? -1 : (r > 1 ? 1 : r);
            s.in[s.nin].l = (short) (l * 32767.0f); s.in[s.nin].r = (short) (r * 32767.0f);
            if (++s.nin == 32) {
                s.g.Process(s.in, s.out, 32); s.g.Prepare(); s.nin = 0;
                for (int k = 0; k < 32; k++) s.push(s.out[k].l * (1.0f / 32768.0f), s.out[k].r * (1.0f / 32768.0f));
            }
            s.t += s.step;
        }
        s.t -= 1.0;
    }
    s.up.read([&](float* l, float* r) {
        int k = 0;
        for (; k < 16; k++) {
            if (s.have > 0) { l[k] = s.fifo[0][s.r]; r[k] = s.fifo[1][s.r]; s.r = (s.r + 1) & 255; s.have--; }
            else { l[k] = r[k] = 0; }
        }
        return k;
    }, outL, outR, n, gain);
}

// ---------------------------------------------------------------- the sympathetic strings
struct SympStrings::Impl {
    rings::Part part;
    uint16_t rev[32768];
    float in[24], out[24], aux[24];
    float pendL[24], pendR[24];
    int fill = 0, have = 0, rd = 0;
    Impl() {
        std::memset((void*) &part, 0, sizeof(part));
        std::memset(rev, 0, sizeof(rev));
        std::memset(in, 0, sizeof(in)); std::memset(pendL, 0, sizeof(pendL)); std::memset(pendR, 0, sizeof(pendR));
        part.Init(rev);
        part.set_polyphony(1);
        part.set_model(rings::RESONATOR_MODEL_SYMPATHETIC_STRING);
    }
};

SympStrings::SympStrings() : d(new Impl) {}
SympStrings::~SympStrings() {}
void SympStrings::prepare(double sampleRate) {
    if (sampleRate < 8000) sampleRate = 48000;
    comp_ = (float) (12.0 * std::log2(48000.0 / sampleRate));   // the engine counts in 48 kHz samples
}
void SympStrings::process(const float* inL, const float* inR, float* outL, float* outR, int n, float gain) {
    Impl& s = *d;
    rings::PerformanceState ps;
    ps.strum = false; ps.internal_exciter = false; ps.internal_strum = false; ps.internal_note = false;
    ps.tonic = 0; ps.note = note_ + comp_; ps.fm = 0; ps.chord = 0;
    rings::Patch patch;
    patch.structure = 0.45f; patch.brightness = 0.55f; patch.damping = 0.82f; patch.position = 0.45f;
    for (int i = 0; i < n; ++i) {                             // in blocks of 24, one block behind
        if (s.have > 0) { outL[i] += gain * s.pendL[s.rd]; outR[i] += gain * s.pendR[s.rd]; ++s.rd; --s.have; }
        s.in[s.fill++] = 0.5f * (inL[i] + inR[i]);
        if (s.fill == 24) {
            s.part.Process(ps, patch, s.in, s.out, s.aux, 24);
            for (int k = 0; k < 24; ++k) { s.pendL[k] = s.out[k]; s.pendR[k] = s.aux[k]; }
            s.fill = 0; s.have = 24; s.rd = 0;
        }
    }
}

}  // namespace brick
