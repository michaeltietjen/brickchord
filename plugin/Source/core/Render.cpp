// A port of brickchord/synth.py render_note and _other_engine. Comments name the
// Python they follow, so the two can be kept in step.
#include "Render.h"
#include <algorithm>
#include <cmath>
#include <complex>
#include <random>

namespace brick {
namespace {

constexpr int TABLE = 2048, NH = TABLE / 2, BLOCK = 128;
constexpr float GAIN = 0.12f;
constexpr double PI = 3.14159265358979323846;
using cpx = std::complex<double>;

// In-place iterative radix-2 FFT (inverse when inv); n is a power of two.
void fft(std::vector<cpx>& a, bool inv) {
    const size_t n = a.size();
    for (size_t i = 1, j = 0; i < n; ++i) {
        size_t bit = n >> 1;
        for (; j & bit; bit >>= 1) j ^= bit;
        j ^= bit;
        if (i < j) std::swap(a[i], a[j]);
    }
    for (size_t len = 2; len <= n; len <<= 1) {
        double ang = 2 * PI / (double) len * (inv ? 1 : -1);
        cpx wl(std::cos(ang), std::sin(ang));
        for (size_t i = 0; i < n; i += len) {
            cpx w(1);
            for (size_t j = 0; j < len / 2; ++j) {
                cpx u = a[i + j], v = a[i + j + len / 2] * w;
                a[i + j] = u + v;
                a[i + j + len / 2] = u - v;
                w *= wl;
            }
        }
    }
    if (inv) for (auto& x : a) x /= (double) n;
}

// synth._adsr: attack ramp, then exponential decay to sustain (no release stage)
std::vector<float> adsr(int n, float a, float d, float s, double rate) {
    std::vector<float> e((size_t) n);
    a = std::max(a, 1e-4f);
    d = std::max(d, 1e-4f);
    for (int i = 0; i < n; ++i) {
        double t = i / rate;
        e[(size_t) i] = t < a ? (float) (t / a) : (float) (s + (1 - s) * std::exp(-(t - a) / (d / 3.0)));
    }
    return e;
}

// synth._harm_amps / _vox_amps for harmonic k (1-based) at duty
double harmAmp(Wave w, int k, double duty, double f) {
    switch (w) {
        case Wave::Saw: return 1.0 / k;
        case Wave::Square: return (k % 2 == 1) ? 1.0 / k : 0.0;
        case Wave::Sine: return k == 1 ? 1.0 : 0.0;
        case Wave::Tri: return (k % 2 == 1) ? 1.6 / ((double) k * k) * ((((k - 1) / 2) % 2 == 0) ? 1 : -1) : 0.0;
        case Wave::Pulse: return 2.0 / (PI * k) * std::sin(PI * k * duty);
        case Wave::Vox: {
            double m = std::clamp((duty - 0.1) / 0.8, 0.0, 1.0), hz = k * f, out = 0.04;
            const double F[3][4] = {{800, 450, 110, 1.0}, {1150, 800, 140, 0.6}, {2900, 2830, 220, 0.3}};
            for (auto& q : F) {
                double Fq = q[0] + (q[1] - q[0]) * m, z = (hz - Fq) / q[2];
                out += q[3] * std::exp(-z * z);
            }
            return out / std::pow((double) k, 0.3);
        }
    }
    return 0.0;
}

// synth._other_engine for FM, Pluck and Noise (raw stereo, envelopes applied after)
std::vector<float> otherEngine(const Patch& p, double f0, int n, double attackLen, std::mt19937& rng) {
    std::vector<float> out((size_t) n * 2, 0.f);
    std::uniform_real_distribution<double> U(0, 1);
    if (p.engine == Engine::FM) {
        const auto& q = p.fm;
        int frz = std::min(n - 1, (int) (attackLen * kSR));
        double idxFrz = q.idxS + (q.idx - q.idxS) * std::exp(-(frz / (double) kSR) / std::max(0.01f, q.idxT));
        for (int ch = 0; ch < 2; ++ch) {
            double fc = f0 * std::pow(2.0, (ch == 0 ? -q.det : q.det) / 1200.0), ph = U(rng) * 6.28;
            for (int i = 0; i < n; ++i) {
                double t = i / (double) kSR;
                double idx = t < attackLen ? q.idxS + (q.idx - q.idxS) * std::exp(-t / std::max(0.01f, q.idxT)) : idxFrz;
                double mod = std::sin(2 * PI * fc * q.ratio * t + ph);
                out[(size_t) i * 2 + ch] = (float) (std::sin(2 * PI * fc * t + idx * mod) * 1.5);
            }
        }
        return out;
    }
    if (p.engine == Engine::Pluck) {
        const auto& q = p.pluck;
        double b = q.bright;
        int P = (int) std::ceil(2.0 * kSR / f0);
        double rate = (P + 0.5 - 0.5 * b) * f0;
        int N = (int) (n * rate / kSR) + P + 2;
        std::vector<float> y((size_t) N, 0.f), ex((size_t) P);
        for (auto& e : ex) e = (float) (U(rng) * 2 - 1);
        for (int r = 0; r < (int) ((1 - b) * 4) + 1; ++r) {           // darker pick = smoother excitation
            std::vector<float> e2(ex);
            for (int i = 0; i < P; ++i) e2[(size_t) i] = 0.5f * (ex[(size_t) i] + ex[(size_t) ((i - 1 + P) % P)]);
            ex = e2;
        }
        double mean = 0;
        for (float e : ex) mean += e;
        mean /= P;
        for (int i = 0; i < P; ++i) y[(size_t) i + 1] = (float) (ex[(size_t) i] - mean);
        double t60 = q.t60 * std::pow(261.6 / f0, 0.35);
        double g = std::pow(10.0, -3.0 * (P / rate) / std::max(0.05, t60));
        for (int s0 = P + 1; s0 < N - P; s0 += P)
            for (int j = 0; j < P; ++j)
                y[(size_t) (s0 + j)] = (float) (g * (y[(size_t) (s0 - P + j)] * (0.5 + 0.5 * b) + y[(size_t) (s0 - P - 1 + j)] * (0.5 - 0.5 * b)));
        std::vector<float> sig((size_t) n);
        for (int i = 0; i < n; ++i) {
            double x = i * (rate / kSR);
            int k = (int) x;
            double fr = x - k;
            sig[(size_t) i] = k + 1 < N ? (float) (y[(size_t) k] * (1 - fr) + y[(size_t) k + 1] * fr) : 0.f;
        }
        if (q.body > 0) {
            int d = (int) (kSR * 0.0023);
            for (int i = n - 1; i >= d; --i) sig[(size_t) i] += q.body * sig[(size_t) (i - d)];
        }
        float pk = 1e-9f;
        for (int i = 0; i < n; ++i) {
            out[(size_t) i * 2] = sig[(size_t) i];
            out[(size_t) i * 2 + 1] = i ? sig[(size_t) i - 1] * 0.97f : 0.f;
        }
        for (float v : out) pk = std::max(pk, std::abs(v));
        for (auto& v : out) v *= 1.7f / pk;
        return out;
    }
    if (p.engine == Engine::Noise) {                    // harmonic noise bands, shaped in the spectrum
        const auto& q = p.noiseCfg;
        size_t M = 1;
        while (M < (size_t) n) M <<= 1;
        std::normal_distribution<double> G(0, 1);
        int kmax = (int) std::min(40.0, std::floor(kSR * 0.45 / f0));
        for (int ch = 0; ch < 2; ++ch) {
            std::vector<cpx> F(M);
            for (size_t i = 0; i < M; ++i) F[i] = i < (size_t) n ? G(rng) : 0.0;
            fft(F, false);
            for (size_t i = 0; i <= M / 2; ++i) {
                double hz = i * (double) kSR / M, gg = q.floor;
                for (int k = 1; k <= kmax; ++k) {
                    double z = (hz - k * f0) / (f0 * q.width * std::sqrt((double) k));
                    gg += std::pow((double) k, -q.tilt) * std::exp(-z * z);
                }
                gg *= 1.0 / std::sqrt(1 + std::pow(hz / p.cutoff, 4));
                F[i] *= gg;
                if (i && i < M / 2) F[M - i] = std::conj(F[i]);
            }
            fft(F, true);
            for (int i = 0; i < n; ++i) out[(size_t) i * 2 + ch] = (float) F[(size_t) i].real();
        }
        float pk = 1e-9f;
        for (float v : out) pk = std::max(pk, std::abs(v));
        for (auto& v : out) v *= 1.7f / pk;
        return out;
    }
    return out;
}

}  // namespace

std::shared_ptr<Note> renderNote(int midi, const Patch& p, unsigned seed) {
    std::mt19937 rng(seed * 7919u + (unsigned) midi);
    std::uniform_real_distribution<double> U(0, 1);
    const double f0 = 440.0 * std::pow(2.0, (midi - 69) / 12.0);
    double attackLen = std::max({0.6, (double) p.a + p.d * 0.8, (double) p.fa + p.fd * 0.8}) + 0.2;
    attackLen = std::min(attackLen, 3.0);
    const double loopLen = 3.0, xfade = 0.4, total = attackLen + loopLen + xfade;
    const int n = (int) (total * kSR), nb = n / BLOCK + 2;
    const double brate = (double) kSR / BLOCK;

    // the filter cutoff per block: base x keytrack x envelope, frozen after the attack
    std::vector<float> fenv = adsr(nb, p.fa, p.fd, p.fs, brate);
    int freeze = (int) (attackLen * brate);
    for (int i = freeze; i < nb; ++i) fenv[(size_t) i] = fenv[(size_t) std::min(freeze, nb - 1)];
    const double keytrack = std::pow(f0 / 261.6, 0.5);
    std::vector<double> fc((size_t) nb), duty((size_t) nb);
    for (int i = 0; i < nb; ++i) {
        fc[(size_t) i] = std::clamp(p.cutoff * keytrack * std::pow(2.0, p.fenv * fenv[(size_t) i]), 40.0, kSR * 0.45);
        double tb = i / brate;
        duty[(size_t) i] = std::clamp(0.5 + 0.4 * p.pwm * std::sin(2 * PI * tb * 1.0)   /* 1 Hz: whole cycles in the 3 s loop */, 0.05, 0.95);
    }
    const double q = std::max(0.5f, p.res);

    std::vector<float> out((size_t) n * 2, 0.f);
    if (p.engine != Engine::VA) out = otherEngine(p, f0, n, attackLen, rng);
    else {
        std::vector<float> tables((size_t) nb * TABLE);
        std::vector<cpx> spec(TABLE);
        for (const auto& o : p.oscs) {
            const double f = f0 * std::pow(2.0, o.octave) * std::pow(2.0, o.cents / 1200.0);
            const int hmax = (int) std::min((double) (NH - 1), kSR * 0.46 / f);
            if (hmax < 1) continue;
            for (int bI = 0; bI < nb; ++bI) {          // one band-limited table per control block
                if (bI > 0 && fc[(size_t) bI] == fc[(size_t) bI - 1] && (o.wave != Wave::Pulse && o.wave != Wave::Vox
                                                                       || duty[(size_t) bI] == duty[(size_t) bI - 1])) {
                    std::copy_n(&tables[(size_t) (bI - 1) * TABLE], TABLE, &tables[(size_t) bI * TABLE]);
                    continue;                          // nothing changed (the envelope is frozen): same table
                }
                std::fill(spec.begin(), spec.end(), cpx(0));
                for (int k = 1; k <= hmax; ++k) {
                    double w = k * f / fc[(size_t) bI], filt;
                    if (p.ladder) {                    // Moog-style 4-pole ladder
                        double kk = std::min(3.9, std::max(0.0, q - 0.5));
                        cpx jw(1.0, w);
                        filt = std::min(6.0, 1.0 / std::abs(jw * jw * jw * jw + kk));
                    } else
                        filt = 1.0 / std::sqrt((1 - w * w) * (1 - w * w) + (w / q) * (w / q));
                    double amp = harmAmp(o.wave, k, duty[(size_t) bI], f) * filt;
                    spec[(size_t) k] = cpx(0, -amp * (TABLE / 2));      // sine phase (irfft of -1j*a)
                    spec[(size_t) (TABLE - k)] = std::conj(spec[(size_t) k]);
                }
                fft(spec, true);
                for (int i = 0; i < TABLE; ++i) tables[(size_t) bI * TABLE + i] = (float) spec[(size_t) i].real();
            }
            const double gl = std::cos((o.pan + 1) * PI / 4), gr = std::sin((o.pan + 1) * PI / 4);
            double phase = U(rng);
            const double inc = f / kSR;
            for (int i = 0; i < n; ++i) {
                double pos = phase * TABLE;
                int i0 = (int) pos, i1 = (i0 + 1) % TABLE, b = i / BLOCK;
                float fr = (float) (pos - i0), u = (float) (i % BLOCK) / BLOCK;
                const float* t0 = &tables[(size_t) b * TABLE];
                const float* t1 = &tables[(size_t) (b + 1) * TABLE];
                float s0 = t0[i0] * (1 - fr) + t0[i1] * fr, s1 = t1[i0] * (1 - fr) + t1[i1] * fr;
                float sig = (s0 * (1 - u) + s1 * u) * o.level;
                out[(size_t) i * 2] += (float) (sig * gl);
                out[(size_t) i * 2 + 1] += (float) (sig * gr);
                phase += inc;
                if (phase >= 1) phase -= 1;
            }
        }
    }
    if (p.noise > 0) {                                  // the VA engine's noise (white, or dark: integrated)
        std::mt19937 nr(7);
        std::normal_distribution<double> G(0, 1);
        std::vector<float> nz((size_t) n);
        double acc = 0;
        for (int i = 0; i < n; ++i) {
            double v = G(nr) * p.noise;
            if (p.noiseDark) { acc += v; v = acc * 0.02; }
            nz[(size_t) i] = (float) v;
        }
        std::vector<double> cs((size_t) n + 1, 0.0);      // minus a 64-sample moving average: no DC, no rumble
        for (int i = 0; i < n; ++i) cs[(size_t) i + 1] = cs[(size_t) i] + nz[(size_t) i];
        for (int i = 0; i < n; ++i) {
            int lo = std::max(0, i - 32), hi = std::min(n, i + 32);
            float v = nz[(size_t) i] - (float) ((cs[(size_t) hi] - cs[(size_t) lo]) / 64.0);
            out[(size_t) i * 2] += v * 0.3f;
            out[(size_t) i * 2 + 1] += v * 0.3f;
        }
    }
    if (p.drive > 0)
        for (auto& v : out) v = (float) (std::tanh(v * (1 + 4 * p.drive)) / (1 + 1.5 * p.drive));
    // the amplitude envelope, frozen after the attack
    std::vector<float> aenv = adsr(n, p.a, p.d, p.s, kSR);
    const int na = (int) (attackLen * kSR), nl = (int) (loopLen * kSR), nx = n - na - nl;
    for (int i = 0; i < n; ++i) {
        float e = aenv[(size_t) std::min(i, na - 1)];
        out[(size_t) i * 2] *= e;
        out[(size_t) i * 2 + 1] *= e;
    }
    auto note = std::make_shared<Note>();
    const float g = GAIN * p.gain;
    note->attack.assign(out.begin(), out.begin() + (size_t) na * 2);
    for (auto& v : note->attack) v *= g;
    if (p.s > 0.001f) {                                 // the loop, its end crossfaded into its start
        note->loop.assign(out.begin() + (size_t) na * 2, out.begin() + (size_t) (na + nl) * 2);
        for (int i = 0; i < nx; ++i) {
            float r = nx > 1 ? (float) i / (nx - 1) : 1.f;
            for (int c = 0; c < 2; ++c) {
                float tail = out[(size_t) (na + nl + i) * 2 + c];
                note->loop[(size_t) i * 2 + c] = note->loop[(size_t) i * 2 + c] * r + tail * (1 - r);
            }
        }
        for (auto& v : note->loop) v *= g;
    }
    note->rate = kSR;
    return note;
}

}  // namespace brick
