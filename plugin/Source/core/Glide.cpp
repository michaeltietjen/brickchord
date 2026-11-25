#include "Glide.h"
#include <algorithm>
#include <cmath>
#include <set>
#include "Render.h"

namespace brick {

static const int kDefaultNotes[kGlideVoices] = {36, 43, 48, 55, 60, 36};    // root, fifth, octave, fifth, two octaves
static const float kPans[kGlideVoices] = {0.0f, -0.4f, 0.4f, -0.2f, 0.2f, 0.0f};
constexpr int kNCH = 5;                                                     // the chord voices; 5 is the sub

GlideEngine::GlideEngine(NoteCache& cache) : cache_(cache) {     // ambient.amb_init's voices
    for (int i = 0; i < kGlideVoices; ++i) {
        V& v = v_[i];
        v.level = i == 0 ? 0.7f : 0.6f;
        v.pan = kPans[i];
        v.rate = 0.15f + 0.05f * (float) i;
        v.cur = v.tgt = (kDefaultNotes[i] + key_) * 100.0;
    }
    v_[5].vib = 0; v_[5].drift = 0;                                 // the sub sits still
}

bool GlideEngine::anyOn() const {
    for (auto& v : v_) if (v.on) return true;
    return false;
}

double GlideEngine::shapeAt(double p, int shape) {           // engine.amb_shape
    p = std::clamp(p, 0.0, 1.0);
    const double pi = 3.14159265358979;
    switch (shape) {
        case 1: case 8: return p;
        case 2: return p * p * (3 - 2 * p);
        case 3: { double e = p * p * (3 - 2 * p); return e + 0.45 * std::sin(pi * p) * p; }
        case 4: return 1.0 - std::pow(1.0 - p, 4) * std::cos(3.0 * pi * p);
        case 5: { double q = std::max(0.0, (p - 0.65) / 0.35); return q * q * (3 - 2 * q); }
        case 6: { double q = std::min(1.0, p / 0.25); return q * q * (3 - 2 * q); }
        case 7: { double e = p * p * (3 - 2 * p); return e + 0.09 * std::sin(6 * pi * p) * std::sin(pi * p); }
        default: return (1 - std::exp(-5 * p)) / (1 - std::exp(-5.0));
    }
}

double GlideEngine::pathAt(const std::vector<double>& path, double el, double dur, int shape) {   // engine.amb_path_at
    if (el <= 0) return path.front();
    if (dur <= 0.02 || el >= dur) return path.back();
    const size_t n = path.size() - 1;
    if (n == 1) {
        double v = path[0] + (path[1] - path[0]) * shapeAt(el / dur, shape);
        if (shape == 8) v = path[0] + std::round((v - path[0]) / 100.0) * 100.0;   // Semitones: a staircase
        return v;
    }
    const double q = el / dur * (double) n;
    const size_t i = std::min(n - 1, (size_t) q);
    return path[i] + (path[i + 1] - path[i]) * shapeAt(q - (double) i, 2);
}

std::vector<double> GlideEngine::scaleVia(double from, double to) const {   // ambient.amb_steps_via
    const auto& sc = scaleSteps(scale_);
    const double lo = std::min(from, to) / 100.0, hi = std::max(from, to) / 100.0;
    std::vector<double> out;
    for (int m = (int) std::ceil(lo); m <= (int) hi; ++m) {
        const int pc = ((m - key_) % 12 + 12) % 12;
        if (std::find(sc.begin(), sc.end(), pc) != sc.end() && m > lo + 0.3 && m < hi - 0.3) out.push_back(m * 100.0);
    }
    if (from > to) std::reverse(out.begin(), out.end());
    if (out.size() > 10) out.resize(10);
    return out;
}

void GlideEngine::push(int i, double tgt, double glide, int shape, double delay, const std::vector<double>& via, bool jump) {
    V& v = v_[i];
    v.tgt = tgt;
    if (jump || v.lvl <= 0.001f) {                           // from silence: there at once
        v.cur = tgt;
        v.path.clear();
    } else if (std::abs(tgt - v.cur) > 0.5 || !via.empty()) {
        v.path.clear();
        v.path.push_back(v.cur);
        v.path.insert(v.path.end(), via.begin(), via.end());
        v.path.push_back(tgt);
        v.p0 = t_; v.delay = delay; v.dur = glide; v.shape = shape;
    }
    // the sound is rendered at one note and pitched from there; far away, or silent, it's fetched again
    const int m = (int) std::lround(tgt / 100.0);
    if (!v.note || v.lvl <= 0.001f || std::abs(m - v.sampleMidi) > 24) {
        v.sampleMidi = m;
        v.note = cache_.get(m, v.r0);
        v.pos = 0;
    }
}

std::vector<int> GlideEngine::voicelead(const std::vector<int>& pcsIn, int rootPc) const {   // ambient.amb_voicelead
    std::set<int> pcs(pcsIn.begin(), pcsIn.end());
    std::vector<int> cand;
    for (int n = 24; n < 97; ++n) if (pcs.count(n % 12)) cand.push_back(n);
    std::vector<std::pair<double, int>> cur;
    for (int i = 0; i < kNCH; ++i) cur.push_back({(v_[i].lvl > 0.001f || v_[i].on ? v_[i].cur : (kDefaultNotes[i] + key_) * 100.0) / 100.0, i});
    std::sort(cur.begin(), cur.end());
    std::vector<int> best(kNCH, 0);
    std::set<int> used;
    int prev = 0;
    size_t start = 0;
    {                                                          // the lowest voice takes the root, C2..B2, as a bass would
        const double c0 = cur[0].first;
        int b = 36;
        double bd = 1e9;
        for (int n = 36; n < 48; ++n) if (n % 12 == rootPc && std::abs(n - c0) < bd) { bd = std::abs(n - c0); b = n; }
        best[(size_t) cur[0].second] = b; used.insert(rootPc); prev = b; start = 1;
    }
    for (size_t k = start; k < cur.size(); ++k) {
        std::vector<int> opts;
        for (int n : cand) if (n > prev) opts.push_back(n);
        if (opts.empty()) opts.push_back(cand.back());
        const double c = cur[k].first;
        int pick = opts[0];
        double pd = 1e9;
        for (int n : opts) {
            double d = std::abs(n - c) + ((used.count(n % 12) && used.size() < pcs.size()) ? 2.5 : 0.0);
            if (d < pd) { pd = d; pick = n; }
        }
        best[(size_t) cur[k].second] = pick;
        used.insert(pick % 12);
        prev = pick;
    }
    return best;
}

void GlideEngine::subFollow(const std::vector<int>& notes, double secs, bool jump) {   // ambient.amb_sub_follow
    V& s = v_[5];
    if (!st_.sub) {
        if (s.on) { s.on = false; s.lvlT = 0; }
        return;
    }
    const int bass = *std::min_element(notes.begin(), notes.end());
    const bool was = s.on;
    s.on = true; s.lvlT = s.level;
    push(5, (bass - 12) * 100.0, secs, 2, 0, {}, jump || !was);
}

void GlideEngine::layOut(const std::vector<int>& notes) {   // from silence: the voices lay the chord out and fade in
    for (int i = 0; i < kNCH; ++i) {
        V& v = v_[i];
        v.on = true; v.lvlT = v.level;
        push(i, notes[(size_t) i] * 100.0, 0, 0, 0, {}, true);
    }
    subFollow(notes, 0.5, true);
}

void GlideEngine::glideAll(const std::vector<int>& notes, float glideX) {   // ambient.amb_glide_all
    const int path = st_.path % kNumGlidePaths;
    int shape = path == 9 ? 2 : path;
    double secs = st_.time * glideX;
    std::vector<double> delays(kNCH, 0.0);
    std::vector<std::vector<double>> vias(kNCH);
    std::vector<int> rank(kNCH);
    for (int i = 0; i < kNCH; ++i) rank[(size_t) i] = i;
    std::sort(rank.begin(), rank.end(), [&](int a, int b) { return notes[(size_t) a] < notes[(size_t) b]; });
    const int mv = st_.move;                                    // 0: no move
    if (mv > 0) {
        const std::string name = kGlideMoves[mv];
        secs = std::max(secs, 2.5) * ((name == "Bloom" || name == "Spiral" || name == "Swoop" || name == "Scatter") ? 2.0 : 1.0);
        const int lo = *std::min_element(notes.begin(), notes.end()), hi = *std::max_element(notes.begin(), notes.end());
        for (int k = 0; k < kNCH; ++k) {
            const int i = rank[(size_t) k];
            const double c = notes[(size_t) i] * 100.0;
            if (name == "Bloom") vias[(size_t) i] = {lo * 100.0};
            else if (name == "Cascade up") delays[(size_t) i] = k * secs * 0.6 / kNCH;
            else if (name == "Cascade down") delays[(size_t) i] = (kNCH - 1 - k) * secs * 0.6 / kNCH;
            else if (name == "Spiral") vias[(size_t) i] = {c + (k % 2 ? 1200.0 : -1200.0)};
            else if (name == "Swoop") vias[(size_t) i] = {c - 1200.0};
            else if (name == "Scatter") {
                const auto& sc = scaleSteps(scale_);
                std::vector<int> opts;
                for (int m = notes[(size_t) i] - 7; m <= notes[(size_t) i] + 7; ++m)
                    if (m != notes[(size_t) i] && std::find(sc.begin(), sc.end(), ((m - key_) % 12 + 12) % 12) != sc.end()) opts.push_back(m);
                if (!opts.empty()) vias[(size_t) i] = {opts[(size_t) std::min((int) opts.size() - 1, (int) (rnd() * opts.size()))] * 100.0};
            } else if (name == "Converge") vias[(size_t) i] = {(lo + hi) * 50.0};
            else if (name == "Fall") vias[(size_t) i] = {c + 1200.0};
        }
        if (path == 9 || path == 8) shape = 2;                   // through a Move's turning points, an ease reads best
    }
    for (int k = 0; k < kNCH; ++k) {
        const int i = rank[(size_t) k];
        const double to = notes[(size_t) i] * 100.0, from = v_[i].cur;
        const double kk = (double) k / (kNCH - 1);              // 0 the bass .. 1 the top
        double g = secs;
        switch (st_.timing) {
            case 1: g = secs * std::clamp(std::abs(to - from) / 500.0, 0.35, 2.5); break;   // by distance
            case 2: g = secs * (1.8 - 0.9 * kk); break;                                      // bass lags
            case 3: g = secs * (0.6 + 0.9 * kk); break;                                      // bass leads
            case 4: g = secs * (0.6 + rnd()); break;                                         // loose
            default: break;
        }
        auto via = vias[(size_t) i];
        if (via.empty() && path == 9) via = scaleVia(from, to);
        v_[i].on = true; v_[i].lvlT = v_[i].level;
        push(i, to, g, shape, delays[(size_t) i], via, false);
    }
    subFollow(notes, secs, false);
}

std::string GlideEngine::apply(const std::vector<int>& pcs, int rootPc, float glideX) {
    auto notes = voicelead(pcs, rootPc);
    bool fresh = true;
    for (int i = 0; i < kNCH; ++i) if (v_[i].on) fresh = false;
    if (fresh) {
        layOut(notes);
        if (st_.move > 0) bloom();
    } else
        glideAll(notes, glideX);
    return {};
}

std::string GlideEngine::playDegree(int deg, const Mods& held, float glideX, bool toggle) {   // ambient.amb_chord_tones, amb_play
    deg = ((deg % 7) + 7) % 7;
    if (toggle && deg == curDeg_ && anyOn()) { stop(); return {}; }   // the same chord again: let it go
    const std::string name = kGlideChords[st_.chord % kNumGlideChords];
    Mods m = held;
    const bool anyHeld = m.seventh || m.sus || m.ninth || m.flip;
    if (!anyHeld) { if (name == "Seventh") m.seventh = true; else if (name == "Ninth") m.ninth = true; else if (name == "Sus4") m.sus = true; }
    Chord c = buildChord(key_, scale_, deg, m);
    std::vector<int> pcs;
    std::string label = c.name;
    if (anyHeld || name == "Triad" || name == "Seventh" || name == "Ninth" || name == "Sus4") {
        for (int i : c.iv) pcs.push_back((c.root + i) % 12);
    } else {                                                   // the colour chords: by degrees or by semitones
        static const std::vector<std::vector<int>> steps = {{}, {}, {}, {0, 2, 4, 6, 8, 10}, {0, 2, 7, 14}, {},
            {0, 5, 10, 15, 20}, {0, 4, 6, 11, 14, 18}, {0, 3, 7, 10, 14, 17}, {0, 4, 7, 11, 14}, {0, 7, 14, 21},
            {0, 2, 3, 5, 7}, {0, 7, 16, 19, 26}};
        const auto& s = steps[(size_t) (st_.chord % kNumGlideChords)];
        const auto& sc = scaleSteps(scale_);
        for (int x : s) pcs.push_back(name == "Eleventh" ? (key_ + sc[(size_t) ((deg + x) % 7)]) % 12 : (c.root + x) % 12);
        label += " " + name;
    }
    apply(pcs, c.root, glideX);
    curDeg_ = deg;
    return romanFor(deg, c.iv) + "  " + label;
}

std::string GlideEngine::follow(std::vector<int> notes, float glideX) {   // ambient.amb_follow: a chord from the keyboard
    std::sort(notes.begin(), notes.end());
    const int rootPc = notes[0] % 12;
    std::vector<int> pcs, iv;
    for (int n : notes) { if (std::find(pcs.begin(), pcs.end(), n % 12) == pcs.end()) pcs.push_back(n % 12); }
    for (int p : pcs) iv.push_back((p - rootPc + 12) % 12);
    std::sort(iv.begin(), iv.end());
    apply(pcs, rootPc, glideX);
    curDeg_ = -1;
    return chordName(rootPc, iv, false, false, key_, scale_);
}

void GlideEngine::stop() {                                    // ambient.amb_stop: everything fades out
    for (auto& v : v_) { v.on = false; v.lvlT = 0; }
    curDeg_ = -1;
}

void GlideEngine::bloom() {                                   // ambient.amb_bloom: one note fanning out to the chord
    std::vector<int> on;
    for (int i = 0; i < kNCH; ++i) if (v_[i].on) on.push_back(i);
    if (on.size() < 2) return;
    const double secs = std::max(3.0, (double) st_.time * 3);
    double low = 1e9;
    for (int i : on) low = std::min(low, v_[i].tgt);
    for (int i : on) {
        V& v = v_[i];
        v.path = {v.cur, low, v.tgt};
        v.p0 = t_; v.delay = 0; v.dur = secs * 1.5; v.shape = 2;
    }
}

void GlideEngine::render(float* L, float* R, int n) {         // engine._amb_render, in blocks of 32
    const double sr = sr_;
    const float bend = bend_, sw = std::max(0.0f, swell_);
    for (int b0 = 0; b0 < n; b0 += 32) {
        const int N = std::min(32, n - b0);
        const double dt = N / sr;
        for (int i = 0; i < kGlideVoices; ++i) {
            V& v = v_[i];
            if (v.lvl <= 0 && v.lvlT <= 0) { v.path.clear(); continue; }
            if (!v.note) {                                       // the sound wasn't ready (or there is none: MIDI out only)
                v.sampleMidi = (int) std::lround(v.tgt / 100.0);
                v.note = cache_.get(v.sampleMidi, v.r0);
            }
            const double c0 = v.cur;
            if (!v.path.empty()) {
                const double el = (double) (t_ + N - v.p0) / sr - v.delay;
                v.cur = pathAt(v.path, el, v.dur, v.shape);
                if (el >= v.dur) v.path.clear();
            } else
                v.cur = v.tgt;
            if (v.drift > 0) {                                    // a slow random drift
                if (--v.drN <= 0) { v.drT = (rnd() * 2 - 1) * v.drift; v.drN = (int) ((2.0 + 4.0 * rnd()) / dt); }
                v.dr += (v.drT - v.dr) * std::min(1.0, dt / 1.5);
            }
            const double ph0 = v.ph;
            v.ph = std::fmod(v.ph + 2 * 3.14159265358979 * v.rate * dt, 2 * 3.14159265358979);
            const double vib = v.vib * (1 + 3 * sw);
            const double cents0 = c0 + v.dr + vib * std::sin(ph0) + bend;
            const double cents1 = v.cur + v.dr + vib * std::sin(v.ph) + bend;
            const double base = v.sampleMidi * 100.0;
            const double k = v.r0 * kSR / sr;
            const double r0 = k * std::pow(2.0, (cents0 - base) / 1200.0), r1 = k * std::pow(2.0, (cents1 - base) / 1200.0);
            const float l0 = v.lvl;
            const float step = (float) (dt / std::max(0.05f, st_.fade));
            v.lvl = v.lvlT > v.lvl ? std::min(v.lvlT, v.lvl + step) : std::max(v.lvlT, v.lvl - step);
            const float g0 = l0 * 1.3f * (1 + 0.6f * sw), g1 = v.lvl * 1.3f * (1 + 0.6f * sw);
            const float lg = std::min(1.0f, 1.0f - kPans[i]), rg = std::min(1.0f, 1.0f + kPans[i]);
            if (!v.note) continue;                               // the voice still moves; it just makes no sound
            const Note& nt = *v.note;
            const int na = nt.attackFrames(), nl = nt.loopFrames();
            for (int s = 0; s < N; ++s) {
                const double f = (double) s / N;
                int kk = (int) v.pos;
                if (kk >= na && nl == 0) break;                     // a struck sound that has finished
                auto get = [&](int idx, float& a, float& c) {
                    if (idx < na) { a = nt.attack[(size_t) idx * 2]; c = nt.attack[(size_t) idx * 2 + 1]; }
                    else if (nl) { idx = (idx - na) % nl; a = nt.loop[(size_t) idx * 2]; c = nt.loop[(size_t) idx * 2 + 1]; }
                    else a = c = 0;
                };
                float a0, c0_, a1, c1;
                get(kk, a0, c0_);
                get(kk + 1, a1, c1);
                const float fr = (float) (v.pos - kk);
                const float g = g0 + (g1 - g0) * (float) f;
                L[b0 + s] += (a0 + (a1 - a0) * fr) * g * lg;
                R[b0 + s] += (c0_ + (c1 - c0_) * fr) * g * rg;
                v.pos += r0 + (r1 - r0) * f;
            }
            if (nl > 0 && v.pos > na + nl) v.pos = na + std::fmod(v.pos - na, (double) nl);
        }
        t_ += N;
    }
    for (int i = 0; i < kGlideVoices; ++i) {
        cents[(size_t) i] = (float) (v_[i].cur + bend_);
        level[(size_t) i] = v_[i].lvl;
        on[(size_t) i] = v_[i].on;
        target[(size_t) i] = (float) v_[i].tgt;
    }
}

}  // namespace brick
