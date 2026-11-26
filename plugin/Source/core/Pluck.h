// The strum and arp over the drone (ambient.py amb_strum and amb_arp_tick; engine.py PLUCKS,
// _pluck_recipe, _pluck_job, c_pluck). The handheld's own strum instruments: each a recipe of
// partials (ratio, level, decay, onset delay, swell, detune) with touches of its own. Plucked
// strings use a string model: harmonics shaped by where the string is plucked, the high ones
// dying sooner, which is what makes a harp or a guitar sound like one.
#pragma once
#include <algorithm>
#include <array>
#include <atomic>
#include <cmath>
#include <condition_variable>
#include <memory>
#include <mutex>
#include <string>
#include <thread>
#include <vector>
#include "Render.h"

namespace brick {

inline const char* const kPluckNames[] = {"Harp", "Nylon", "Koto", "Kalimba", "Celesta", "Steel Pan", "Bell", "Glass Harp",
                                          "Marimba", "Music Box", "Shimmer Harp", "Tape Harp", "Sparkle", "Analog Pluck"};
constexpr int kNumPlucks = 14;

inline std::shared_ptr<Note> renderPluck(int inst, int midi, int sr) {
    struct P { double ratio, lv, dk, delay, swell, det; };
    const double pi = 3.14159265358979323846;
    const double f = 440.0 * std::pow(2.0, (midi - 69) / 12.0);
    std::vector<P> p;
    double len = 2.2, noise = 0, ncut = 0.5, drop = 0, dtau = 0.05, wow = 0, att = 0.002;
    auto string = [&](double pos, int n, double d0, double dk, double tilt) {
        for (int k = 1; k <= n; ++k) {
            const double a = std::abs(std::sin(pi * k * pos)) / std::pow((double) k, tilt);
            if (a > 0.004) p.push_back({(double) k, a, d0 * (1 + dk * std::pow(k - 1.0, 1.6)) * std::pow(f / 260.0, 0.35), 0, 0, 0});
        }
    };
    const std::string name = kPluckNames[((inst % kNumPlucks) + kNumPlucks) % kNumPlucks];
    if (name == "Harp") { string(0.21, 12, 1.1, 0.22, 0.95); noise = 0.05; ncut = 0.25; }
    else if (name == "Nylon") { string(0.14, 14, 1.4, 0.35, 1.05); p.push_back({1.003, 0.25, 1.6, 0, 0, 0}); noise = 0.08; ncut = 0.12; len = 2.0; }
    else if (name == "Koto") { string(0.07, 14, 1.9, 0.18, 0.85); noise = 0.12; ncut = 0.5; drop = 38.0; dtau = 0.045; len = 1.8; }
    else if (name == "Kalimba") { p = {{1, 1.0, 2.0, 0, 0, 0}, {1, 0.5, 2.1, 0, 0, 0.7}, {5.95, 0.32, 13.0, 0, 0, 0}, {10.9, 0.12, 28.0, 0, 0, 0}, {2.0, 0.06, 6.0, 0, 0, 0}}; noise = 0.22; ncut = 0.08; len = 2.0; }
    else if (name == "Celesta") { p = {{1, 1.0, 1.4, 0, 0, 0}, {4.0, 0.38, 5.5, 0, 0, 0}, {8.12, 0.14, 11.0, 0, 0, 0}, {2.0, 0.16, 2.8, 0, 0, 0}, {12.3, 0.05, 18.0, 0, 0, 0}}; noise = 0.05; ncut = 0.6; len = 2.4; }
    else if (name == "Steel Pan") { p = {{1, 1.0, 1.25, 0, 0, 0}, {2, 0.75, 1.9, 0, 0, 0}, {3, 0.4, 3.0, 0, 0, 0}, {4.02, 0.2, 4.6, 0, 0, 0}, {2.0, 0.3, 1.3, 0, 0.03, 1.1}}; noise = 0.06; ncut = 0.4; drop = -14.0; dtau = 0.03; len = 2.4; }
    else if (name == "Bell") { p = {{1, 1.0, 0.7, 0, 0, 0}, {2.756, 0.62, 0.95, 0, 0, 0}, {5.404, 0.42, 1.5, 0, 0, 0}, {8.933, 0.26, 2.3, 0, 0, 0}, {13.34, 0.12, 3.6, 0, 0, 0}, {0.5, 0.14, 0.45, 0, 0, 0}, {2.756, 0.3, 0.95, 0, 0, 0.9}}; noise = 0.03; ncut = 0.7; len = 3.2; }
    else if (name == "Glass Harp") { p = {{1, 1.0, 0.55, 0, 0.012, 0}, {1, 0.85, 0.55, 0, 0.012, 1.3}, {3.0, 0.18, 1.1, 0, 0.02, 0}, {5.0, 0.06, 1.8, 0, 0.02, 0.6}}; len = 3.2; att = 0.012; }
    else if (name == "Marimba") { p = {{1, 1.3, 2.6, 0, 0, 0}, {3.93, 0.42, 8.5, 0, 0, 0}, {9.24, 0.12, 21.0, 0, 0, 0}, {1.0, 0.25, 1.4, 0, 0.02, 0.4}}; noise = 0.18; ncut = 0.15; len = 2.0; }
    else if (name == "Music Box") { p = {{1, 1.0, 1.7, 0, 0, 0}, {1, 0.6, 1.8, 0, 0, 2.2}, {2.98, 0.28, 4.6, 0, 0, 0}, {5.95, 0.12, 8.5, 0, 0, 0}, {9.9, 0.05, 14.0, 0, 0, 0}}; noise = 0.07; ncut = 0.9; len = 2.4; }
    else if (name == "Shimmer Harp") {
        string(0.21, 10, 1.0, 0.22, 0.95);
        for (P q : std::vector<P>{{2, 0.32, 0.55, 0.06, 0.35, 0.8}, {2, 0.28, 0.55, 0.06, 0.35, -0.8}, {3, 0.16, 0.7, 0.12, 0.45, 0.5}, {4, 0.1, 0.8, 0.18, 0.5, -0.5}}) p.push_back(q);   // it blooms upward
        noise = 0.04; ncut = 0.25; len = 3.2;
    } else if (name == "Tape Harp") { string(0.23, 8, 1.3, 0.45, 1.1); noise = 0.04; ncut = 0.1; wow = 1.0; len = 2.4; }
    else if (name == "Sparkle") {
        uint32_t r = (uint32_t) (f * 10) % 9973u + 17u;
        auto rnd = [&] { r = r * 1664525u + 1013904223u; return (double) (r >> 8) / 16777216.0; };
        static const double pick[] = {2, 3, 4, 5, 6, 8};
        p = {{1, 0.7, 2.2, 0, 0, 0}};
        for (int i = 0; i < 9; ++i) p.push_back({pick[(int) (rnd() * 6) % 6], 0.08 + 0.22 * rnd(), 5 + 7 * rnd(), 0.18 * rnd(), 0.004, -2 + 4 * rnd()});   // glints: high partials that start a little late
        noise = 0.02; ncut = 0.9; len = 2.0;
    } else {                                                  // Analog Pluck: a saw through a closing filter
        for (int k = 1; k <= 16; ++k) p.push_back({(double) k, 1.0 / k, 2.2 * (1 + 0.55 * std::pow(k - 1.0, 1.35)), 0, 0, 0});
        len = 1.6;
    }
    const int n = (int) (len * sr);
    std::vector<double> ph((size_t) n);
    {
        double acc = 0;
        for (int i = 0; i < n; ++i) {
            const double t = (double) i / sr;
            double cents = 0;
            if (drop != 0) cents += drop * std::exp(-t / dtau);
            if (wow != 0) cents += 11.0 * std::sin(2 * pi * 0.55 * t) + 3.0 * std::sin(2 * pi * 6.7 * t + 1.0);
            ph[(size_t) i] = acc;
            acc += 2 * pi * f / sr * std::pow(2.0, cents / 1200.0);
        }
    }
    std::vector<float> x((size_t) n, 0.0f);
    const double nyq = 0.45 * sr;
    for (const P& q : p) {
        if (f * q.ratio >= nyq) continue;
        const double e1 = std::exp(-q.dk / sr);
        double env = 1;
        for (int i = 0; i < n; ++i) {
            const double t = (double) i / sr;
            if (t < q.delay) continue;
            const double tt = t - q.delay;
            double e = env;
            if (q.swell > 0) e *= std::min(1.0, tt / q.swell);
            x[(size_t) i] += (float) (std::sin(q.ratio * ph[(size_t) i] + 2 * pi * q.det * t) * q.lv * e);
            env *= e1;
        }
    }
    if (noise > 0) {                                           // a breath of noise for the pluck or mallet
        const int k = (int) (0.02 * sr);
        uint32_t r = (uint32_t) (midi + 31 * inst) * 2654435761u + 1u;
        float z = 0;
        for (int i = 0; i < k && i < n; ++i) {
            r = r * 1664525u + 1013904223u;
            const float u = (float) (r >> 8) / 8388608.0f - 1.0f;
            z = i == 0 ? u : z + (float) ncut * (u - z);
            const float w = 1.0f - (float) i / (float) k;
            x[(size_t) i] += z * (float) noise * w * w;
        }
    }
    const int tail = (int) (0.05 * sr);
    float peak = 1e-6f;
    for (int i = 0; i < n; ++i) {
        x[(size_t) i] *= (float) std::min(1.0, ((double) i / sr) / att);
        if (i >= n - tail) x[(size_t) i] *= (float) (n - 1 - i) / (float) tail;
        peak = std::max(peak, std::abs(x[(size_t) i]));
    }
    const float g = 0.17f / peak * (float) std::min(1.0, std::pow(220.0 / f, 0.25) + 0.35);
    auto note = std::make_shared<Note>();
    note->rate = sr;
    note->attack.resize((size_t) n * 2);
    for (int i = 0; i < n; ++i) note->attack[(size_t) i * 2] = note->attack[(size_t) i * 2 + 1] = x[(size_t) i] * g;
    return note;
}

// the strum's notes for one instrument, made off the audio thread
class PluckBank {
public:
    static constexpr int kLo = 48, kHi = 92;
    PluckBank() : th_([this] { run(); }) {}
    ~PluckBank() { { std::lock_guard<std::mutex> l(mx_); quit_ = true; } cv_.notify_all(); th_.join(); }
    void set(int inst, int rate) {                           // which instrument, at which sample rate: makes them all again
        std::lock_guard<std::mutex> l(mx_);
        if (inst == inst_ && rate == rate_) return;
        inst_ = inst; rate_ = rate; ++gen_;
        for (auto& n : notes_) n.reset();
        cv_.notify_all();
    }
    std::shared_ptr<Note> get(int midi) const {              // that note, or the nearest one made so far (and how far off it is)
        std::unique_lock<std::mutex> l(mx_, std::try_to_lock);
        if (!l.owns_lock()) return nullptr;
        midi = std::clamp(midi, kLo, kHi);
        return notes_[(size_t) (midi - kLo)];
    }

private:
    void run() {
        std::unique_lock<std::mutex> l(mx_);
        int done = -1;
        for (;;) {
            cv_.wait(l, [&] { return quit_ || done != gen_; });
            if (quit_) return;
            const int gen = gen_, inst = inst_, rate = rate_;
            for (int d = 0; d <= 22 && gen == gen_ && !quit_; ++d)
                for (int m : {70 + d, 70 - d}) {             // from the middle out
                    if (m < kLo || m > kHi || (d == 0 && m != 70) || notes_[(size_t) (m - kLo)]) continue;
                    l.unlock();
                    auto note = renderPluck(inst, m, rate);
                    l.lock();
                    if (gen != gen_ || quit_) break;
                    notes_[(size_t) (m - kLo)] = note;
                }
            if (gen == gen_) done = gen;
        }
    }
    mutable std::mutex mx_;
    std::condition_variable cv_;
    std::array<std::shared_ptr<Note>, kHi - kLo + 1> notes_{};
    int inst_ = -1, rate_ = 0, gen_ = 0;
    bool quit_ = false;
    std::thread th_;
};

class Plucker {
public:
    explicit Plucker(PluckBank& bank) : bank_(bank) {}
    void prepare(double sr) { sr_ = sr; v_.clear(); v_.reserve(40); }
    void clear() { v_.clear(); }
    void pluck(int midi, float gain, float pan, int wait) {
        auto note = bank_.get(midi);
        if (!note) return;                                   // not made yet
        if (v_.size() >= 28) v_.erase(v_.begin());             // the oldest gives way
        PV v;
        v.note = note; v.rate = note->rate / sr_; v.g = gain; v.wait = wait < 0 ? 0 : wait;
        v.lg = std::min(1.0f, 1.0f - pan); v.rg = std::min(1.0f, 1.0f + pan);
        v_.push_back(v);
    }
    void render(float* L, float* R, int n) {                 // adds into L and R
        for (auto& v : v_) {
            const auto& a = v.note->attack;
            const int na = v.note->attackFrames();
            for (int i = 0; i < n; ++i) {
                if (v.wait > 0) { --v.wait; continue; }
                const int p = (int) v.pos;
                if (p + 1 >= na) { v.done = true; break; }
                const float fr = (float) (v.pos - p);
                const float s = a[(size_t) p * 2] + (a[(size_t) (p + 1) * 2] - a[(size_t) p * 2]) * fr;
                L[i] += s * v.g * v.lg;
                R[i] += s * v.g * v.rg;
                v.pos += v.rate;
            }
        }
        v_.erase(std::remove_if(v_.begin(), v_.end(), [](const PV& v) { return v.done; }), v_.end());
    }

private:
    struct PV {
        std::shared_ptr<Note> note;
        double pos = 0, rate = 1;
        float g = 1, lg = 1, rg = 1;
        int wait = 0;
        bool done = false;
    };
    PluckBank& bank_;
    std::vector<PV> v_;
    double sr_ = 44100;
};

}  // namespace brick
