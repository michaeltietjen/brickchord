#include "Patterns.h"
#include <algorithm>
#include <cstring>
#include <set>

namespace brick {

static const char* kStrumPat(const char* mode) {          // engine.STRUM_PATTERNS: 8th-note grid
    if (!std::strcmp(mode, "Strum Folk")) return "D.DU.UDU";
    if (!std::strcmp(mode, "Strum Pop")) return "D.D.UDUd";
    return ".D.D.D.D";                                     // Strum Skank
}
static bool starts(const char* s, const char* p) { return std::strncmp(s, p, std::strlen(p)) == 0; }
static bool has(const char* s, const char* p) { return std::strstr(s, p) != nullptr; }
static int repeatSteps(const char* mode) { return has(mode, "1/4") ? 4 : (has(mode, "1/8") ? 2 : 1); }

void Patterns::note(int64_t at, int ch, int m, float gain, float pan, Tag tag, int64_t gate, float rel) {
    if (m < 0 || m > 127) return;
    const uint32_t id = nextId_++;
    gain *= 0.35f + 0.65f * vel_ / 0.85f;                // velocity: the pads play at 0.85, unchanged
    q_.push_back({at, true, ch, m, gain, pan, -1, id});
    if (gate >= 0) q_.push_back({at + std::max<int64_t>(1, gate), false, ch, m, 0, 0, rel, id});
    auto& l = live_[tag];
    l.push_back({ch, m, id});
    if (l.size() > 96) l.erase(l.begin(), l.begin() + 32);     // gated notes end themselves
}

void Patterns::release(Tag tag, int64_t at, float rel) {
    for (auto& v : live_[tag]) q_.push_back({at, false, v.ch, v.note, 0, 0, rel, v.id});
    live_[tag].clear();
}

std::vector<int> Patterns::arpNotes() const {           // engine._arp_notes
    std::set<int> s(notes_.begin() + 1, notes_.end());
    std::vector<int> base(s.begin(), s.end()), out;
    for (int k = 0; k < arpOct_; ++k)
        for (int m : base) if (m + 12 * k <= 108) out.push_back(m + 12 * k);
    if (base[0] + 12 * arpOct_ <= 108) out.push_back(base[0] + 12 * arpOct_);
    return out.empty() ? base : out;
}

void Patterns::chord(const std::vector<int>& notes, int64_t t, float vel) {   // engine.c_chord
    if (notes.size() < 2) return;
    vel_ = std::clamp(vel, 0.05f, 1.0f);
    notes_ = notes;
    pat_.assign(notes.begin() + 1, notes.end());
    pat_.push_back(notes[1] + 12);
    arp_ = arpNotes();
    const char* m = mode();
    const bool patchBass = bassMode_ == 4 || bassMode_ == 5;
    bassStart(t, true);                                    // a press always restarts the bass
    if (!std::strcmp(m, "Chord") || !std::strcmp(m, "Slop")) {
        release(Held, t);
        const bool slop = !std::strcmp(m, "Slop");
        for (size_t i = 0; i < notes.size(); ++i) {
            if (i == 0 && !patchBass) continue;            // the synth bass (or nothing) replaces it
            int64_t when = t;
            float gain = 0.95f;
            if (slop) { when += (int64_t) (rnd() * 0.045 * sr_); gain = 0.72f + 0.28f * rnd(); }
            note(when, 1, notes[i], gain, 0, Held);
        }
        return;
    }
    release(Held, t, 0.025f);                              // pattern modes keep a bass voice
    if (patchBass) note(t, 1, notes[0], 0.7f, 0, Held);
    if (starts(m, "Harp")) {
        std::set<int> pcs;
        for (int n : notes) pcs.insert(n % 12);
        int lo = (notes[1] / 12) * 12 - 2;
        std::vector<int> run;
        for (int n = lo; n < lo + 36; ++n) if (pcs.count(n % 12)) run.push_back(n);
        if (!std::strcmp(m, "Harp Down")) std::reverse(run.begin(), run.end());
        for (size_t i = 0; i < run.size(); ++i) {
            float pan = (float) i / (float) std::max<size_t>(1, run.size() - 1) - 0.5f;
            note(t + (int64_t) (i * 0.034 * sr_), 1, run[i], 0.6f, pan, Harp, (int64_t) (1.4 * sr_));
        }
        return;
    }
    if (starts(m, "Strum")) strum('D', t);
    else if (starts(m, "Repeat")) repeat(t, repeatSteps(m));
    else { patI_ = 0; patDir_ = 1; arpStep(t); }
    chordT_ = t;
}

void Patterns::clear(int64_t t) {                          // engine.c_clear
    release(Held, t);
    release(Strum, t, 0.12f);
    release(Arp, t, 0.06f);
    release(Bass, t, 0.08f);
    notes_.clear();
}

void Patterns::strum(char c, int64_t at) {                 // engine._strum
    if (c == '.' || notes_.empty()) return;
    std::vector<int> ns(pat_);
    std::sort(ns.begin(), ns.end());
    const bool skank = !std::strcmp(mode(), "Strum Skank");
    release(Strum, at, skank ? 0.05f : 0.11f);
    std::vector<int> seq;
    double gap; float vol;
    if (c == 'D' || c == 'd') { seq = ns; gap = 0.013; vol = c == 'D' ? 0.95f : 0.6f; }
    else { seq.assign(ns.rbegin(), ns.rend()); if (seq.size() > 4) seq.resize(4); gap = 0.010; vol = 0.62f; }
    const int64_t gate = skank ? (int64_t) (0.11 * sr_) : (int64_t) (60.0 / bpm_ * 2 * sr_);
    for (size_t i = 0; i < seq.size(); ++i) {
        float pan = ((float) i / (float) std::max<size_t>(1, seq.size() - 1) - 0.5f) * 0.6f;
        note(at + (int64_t) (i * gap * sr_), 1, seq[i], vol * (1 - 0.04f * (float) i), pan, Strum, gate);
    }
}

void Patterns::arpStep(int64_t at) {                       // engine._arp_step
    if (notes_.empty()) return;
    const char* m = mode();
    const auto& ns = arp_.empty() ? pat_ : arp_;
    const int len = (int) ns.size();
    const double step = 60.0 / bpm_ / (has(m, "1/8") ? 2 : 4) * sr_;
    int n;
    if (has(m, "Random")) n = ns[(size_t) std::min(len - 1, (int) (rnd() * len))];
    else if (has(m, "Down") && !has(m, "Up")) { n = ns[(size_t) (len - 1 - (patI_ % len))]; ++patI_; }
    else if (has(m, "Up-Down")) {
        patI_ = std::max(0, std::min(patI_, len - 1));
        n = ns[(size_t) patI_];
        if (len > 1) {
            if (patI_ + patDir_ < 0 || patI_ + patDir_ >= len) patDir_ = -patDir_;
            patI_ += patDir_;
        }
    } else { n = ns[(size_t) (patI_ % len)]; ++patI_; }
    release(Arp, at, 0.03f);
    note(at, 1, n, 0.85f, 0, Arp, (int64_t) (step * 0.9), (float) (step * 0.8 / sr_));
}

void Patterns::repeat(int64_t at, int k) {                 // engine._repeat
    if (notes_.empty()) return;
    const double step = 60.0 / bpm_ / 4 * sr_ * k;
    release(Strum, at, 0.01f);
    const size_t n = notes_.size() - 1;
    for (size_t i = 1; i < notes_.size(); ++i) {
        float pan = ((float) (i - 1) / (float) std::max<size_t>(1, n - 1) - 0.5f) * 0.5f;
        note(at, 1, notes_[i], 0.85f, pan, Strum, (int64_t) (step * 0.55), 0.04f);
    }
}

void Patterns::bassStart(int64_t t, bool changed) {        // engine._bass_start
    int root = notes_[0] - 12;
    while (root < 28) root += 12;
    if (bassMode_ == 0 || bassMode_ == 4) {                 // Synth, Sub + Patch: held
        if (changed) {
            release(Bass, t, 0.02f);
            note(t, 2, root, bassMode_ == 4 ? 0.8f : 1.0f, 0, Bass);
        }
    } else if (bassMode_ >= 1 && bassMode_ <= 3) {          // Pulse, Octaves, Walk: on the clock
        if (changed) {
            release(Bass, t, 0.02f);
            bassI_ = 0;
            bassStep(t);
            bassT0_ = t;
        }
    } else
        release(Bass, t, 0.02f);                            // Patch, Off
}

static const int kWalk[4] = {0, 0, 7, 12};             // Walk: root, root, fifth, octave

void Patterns::bassStep(int64_t at) {                      // engine._bass_step
    if (notes_.empty()) return;
    int r = notes_[0] - 12;
    while (r < 28) r += 12;
    int m = bassMode_ == 1 ? r : (bassMode_ == 2 ? (bassI_ % 2 == 0 ? r : r + 12) : r + kWalk[bassI_ % 4]);
    const float g = bassI_ % 2 == 0 ? 1.0f : 0.8f;
    ++bassI_;
    const double step = 60.0 / bpm_ / 2 * sr_;
    release(Bass, at, 0.015f);
    note(at, 2, m, g, 0, Bass, (int64_t) (step * 0.8));
}

void Patterns::step(int64_t s, int64_t at) {               // engine._on_step
    if (notes_.empty()) return;
    const char* m = mode();
    if (bassMode_ >= 1 && bassMode_ <= 3 && s % 2 == 0 && at - bassT0_ > (int64_t) (0.09 * sr_)) bassStep(at);
    const bool fresh = at - chordT_ < (int64_t) (0.09 * sr_);   // just played on press
    if (fresh) return;
    if (starts(m, "Strum") && s % 2 == 0) strum(kStrumPat(m)[(s / 2) % 8], at);
    else if (starts(m, "Arp") && (has(m, "1/16") || s % 2 == 0)) arpStep(at);
    else if (starts(m, "Repeat")) { int k = repeatSteps(m); if (s % k == 0) repeat(at, k); }
}

void Patterns::take(int64_t upto, std::vector<NoteEvent>& out) {
    std::stable_sort(q_.begin(), q_.end(), [](const NoteEvent& a, const NoteEvent& b) {
        return a.at != b.at ? a.at < b.at : (!a.on && b.on);   // offs before ons at the same time
    });
    size_t k = 0;
    for (; k < q_.size() && q_[k].at < upto; ++k) {
        auto e = q_[k];
        uint32_t& act = active_[e.ch][e.note];
        if (e.on) {
            if (act) out.push_back({e.at, false, e.ch, e.note, 0, 0, 0.01f, act});   // the same note again: retrigger
            act = e.id;
            out.push_back(e);
        } else if (act == e.id) {                          // an off for a note a newer one took over is dropped
            act = 0;
            out.push_back(e);
        }
    }
    q_.erase(q_.begin(), q_.begin() + (long) k);
}

}  // namespace brick
