#include "Engine.h"
#include <algorithm>
#include <chrono>
#include <cmath>
#include "PatchData.h"

namespace brick {

// ---------------------------------------------------------------- the note cache
static std::shared_ptr<Note> renderBass(int midi) {     // synth.render_bass
    const double f = 440.0 * std::pow(2.0, (midi - 69) / 12.0);
    const int n = (int) (2.4 * kSR);
    const int nh = (int) std::min(14.0, std::floor(kSR * 0.42 / f));
    auto note = std::make_shared<Note>();
    note->attack.resize((size_t) n * 2);
    for (int i = 0; i < n; ++i) {
        double t = (double) i / kSR, ph = 2 * 3.14159265358979 * f * t, x = 0;
        for (int h = 1; h <= nh; ++h) x += std::sin(ph * h) * (0.55 / h) * std::exp(-t * (4.0 + 5.5 * h));
        x += std::sin(ph) * 0.75 + std::sin(ph * 2) * 0.10 * std::exp(-t * 2.0);
        double env = std::min(1.0, t / 0.003) * (0.62 + 0.38 * std::exp(-t * 7.0)) * std::exp(-t * 0.25);
        float v = (float) (std::tanh(x * env * 1.6) * 0.62);
        note->attack[(size_t) i * 2] = note->attack[(size_t) i * 2 + 1] = v;
    }
    note->rate = kSR;
    return note;
}

NoteCache::NoteCache() { th_ = std::thread([this] { run(); }); }

NoteCache::~NoteCache() {
    quit_ = true;
    cv_.notify_all();
    if (th_.joinable()) th_.join();
}

void NoteCache::setSound(int index) {
    std::lock_guard<std::mutex> l(mx_);
    if (index == sound_.load() && ready_.load() > 0) return;
    sound_ = std::clamp(index, 0, kNumPatches - 1);
    ++gen_;
    for (auto& n : notes_) n.reset();
    ready_ = 0;
    todo_.clear();
}

void NoteCache::setRate(int sampleRate) {
    std::lock_guard<std::mutex> l(mx_);
    sampleRate = std::clamp(sampleRate, 22050, 48000);
    if (sampleRate == rate_.load()) return;
    rate_ = sampleRate;                                    // the thread switches before its next render
    ++gen_;
    for (auto& n : notes_) n.reset();
    for (auto& n : bass_) n.reset();
    ready_ = 0;
    todo_.clear();
    cv_.notify_all();
}

void NoteCache::want(const std::vector<int>& midis) {
    {
        std::lock_guard<std::mutex> l(mx_);
        std::deque<int> q;
        for (int m : midis)                                // 1000 + m asks for the synth bass note m
            if ((m >= 1000 && m < 1128 && !bass_[(size_t) (m - 1000)]) || (m >= 0 && m < 128 && !notes_[(size_t) m])) q.push_back(m);
        for (int m : todo_) if (std::find(q.begin(), q.end(), m) == q.end()) q.push_back(m);
        todo_ = q;
    }
    cv_.notify_all();
}

std::shared_ptr<Note> NoteCache::get(int midi, double& ratio) const {
    std::lock_guard<std::mutex> l(mx_);
    if (midi >= 0 && midi < 128 && notes_[(size_t) midi]) { ratio = 1; return notes_[(size_t) midi]; }
    for (int d = 1; d < 128; ++d)                      // a stand-in: the nearest note, pitched
        for (int s : {midi - d, midi + d})
            if (s >= 0 && s < 128 && notes_[(size_t) s]) { ratio = std::pow(2.0, (midi - s) / 12.0); return notes_[(size_t) s]; }
    return nullptr;
}

std::shared_ptr<Note> NoteCache::bass(int midi) const {
    std::lock_guard<std::mutex> l(mx_);
    return (midi >= 0 && midi < 128) ? bass_[(size_t) midi] : nullptr;
}

void NoteCache::run() {
    int nextBass = 28;                                   // the synth bass fills in between the sound's notes
    while (!quit_) {
        int m = -1, snd = 0, gen = 0;
        {
            std::unique_lock<std::mutex> l(mx_);
            cv_.wait_for(l, std::chrono::milliseconds(50), [this, nextBass] { return quit_ || !todo_.empty() || nextBass <= 63; });
            if (quit_) return;
            if (kSR != rate_.load()) { kSR = rate_.load(); nextBass = 28; }   // a new rate: between renders only
            gen = gen_.load();
            if (todo_.empty() || (todo_.front() >= 1000)) {
                int b = !todo_.empty() ? todo_.front() - 1000 : nextBass;
                if (!todo_.empty()) todo_.pop_front();
                if (b > 63 || bass_[(size_t) std::min(b, 127)]) { if (b == nextBass) ++nextBass; continue; }
                l.unlock();
                auto bn = renderBass(b);
                std::lock_guard<std::mutex> l2(mx_);
                if (gen == gen_.load()) bass_[(size_t) b] = bn;
                if (b == nextBass) ++nextBass;
                continue;
            }
            m = todo_.front();
            todo_.pop_front();
            snd = sound_.load();
        }
        auto note = renderNote(m, kPatches[snd], (unsigned) snd + 1);
        std::lock_guard<std::mutex> l(mx_);
        if (gen == gen_.load() && !notes_[(size_t) m]) { notes_[(size_t) m] = note; ++ready_; }
    }
}

// ---------------------------------------------------------------- playing
int degreeOf(int note, int key, Scale scale) {
    const auto& sc = scaleSteps(scale);
    int pc = ((note - key) % 12 + 12) % 12, best = 0, bd = 99;
    for (int i = 0; i < 7; ++i) {
        int d = std::min(((pc - sc[(size_t) i]) % 12 + 12) % 12, ((sc[(size_t) i] - pc) % 12 + 12) % 12);
        if (d < bd) { bd = d; best = i; }
    }
    return best;
}

Chord Player::playDegree(int degree, const Mods& m) {
    Chord c = buildChord(key_, scale_, ((degree % 7) + 7) % 7, m);
    std::vector<int> notes;
    {
        std::lock_guard<std::mutex> l(vmx_);
        notes = voice(c.root, c.iv, prev_);
    }
    start(notes);
    return c;
}

Chord Player::playExact(const std::vector<int>& keys) {
    std::vector<int> ns(keys);
    std::sort(ns.begin(), ns.end());
    Chord c;
    c.root = ns[0] % 12;
    for (int n : ns) {
        int i = ((n - c.root) % 12 + 12) % 12;
        if (std::find(c.iv.begin(), c.iv.end(), i) == c.iv.end()) c.iv.push_back(i);
    }
    std::sort(c.iv.begin(), c.iv.end());
    c.name = chordName(c.root, c.iv, false, false, key_, scale_);
    std::vector<int> notes;
    {
        std::lock_guard<std::mutex> l(vmx_);
        notes = voice(c.root, c.iv, prev_);
    }
    start(notes);
    return c;
}

void Player::start(const std::vector<int>& notes) {   // the voicing only: Patterns plays it
    std::lock_guard<std::mutex> l(vmx_);
    last_ = notes;
    for (int& m : last_) m = std::clamp(m + 12 * octave_, 0, 127);
}

void Player::release() {}

void Player::noteOn(int ch, int midi, float gain, float pan) {
    if (midi < 0 || midi > 127) return;
    Voice v;
    double ratio = 1;
    if (ch == 2) {
        v.note = cache_.bass(midi);
        if (!v.note) { cache_.want({1000 + midi}); return; }
        v.bass = true;
        gain *= bassGain_;
    } else {
        v.note = cache_.get(midi, ratio);
        if (!v.note) return;
    }
    v.rate = ratio * v.note->rate / sr_;
    v.gain = gain;
    v.lg = 1.0f - std::max(0.0f, pan);
    v.rg = 1.0f + std::min(0.0f, pan);
    v.midi = midi;
    v.ch = ch;
    std::lock_guard<std::mutex> l(vmx_);
    voices_.push_back(v);
    if (voices_.size() > 64)                             // keep the count bounded: oldest go first
        for (size_t i = 0; i + 64 < voices_.size(); ++i)
        {
            auto& o = voices_[i];
            const int fast = (int) (0.012 * sr_);
            if (o.relAt < 0) { o.relAt = 0; o.relLen = fast; }
            else o.relLen = std::min(o.relLen, o.age + fast);
        }
}

void Player::noteOff(int ch, int midi, float relSecs) {
    std::lock_guard<std::mutex> l(vmx_);
    for (auto& v : voices_)
        if (v.ch == ch && v.midi == midi && v.relAt < 0) {
            float r = relSecs < 0 ? relSecs_ : std::min(relSecs_, relSecs);
            if (v.bass && relSecs < 0) r = 0.08f;
            v.relAt = 0;
            v.relLen = std::max(1, (int) (r * sr_));
        }
}

void Player::allOff() {
    std::lock_guard<std::mutex> l(vmx_);
    for (auto& v : voices_)
        if (v.relAt < 0) { v.relAt = 0; v.relLen = (int) (0.05 * sr_); }
    for (auto& v : gv_)
        if (!v.rel) { v.rel = true; v.relN = (int) (0.05 * sr_); }
}

std::vector<int> Player::wanted() const {              // live.py wanted(): the chords' notes first
    std::vector<int> first, prev;
    for (int d = 0; d < 7; ++d) {
        Chord c = buildChord(key_, scale_, d, Mods{});
        auto notes = voice(c.root, c.iv, prev);
        for (int& m : notes) m = std::clamp(m + 12 * octave_, 0, 127);
        int root = notes[0] - 12;
        while (root < 28) root += 12;
        first.insert(first.begin(), 1000 + root);         // the bass under it, first of all
        first.push_back(1000 + root + 7);                 // and what Walk and Octaves reach for
        first.push_back(1000 + root + 12);
        for (size_t i = 1; i < notes.size(); ++i)
            if (std::find(first.begin(), first.end(), notes[i]) == first.end()) first.push_back(notes[i]);
        if (std::find(first.begin(), first.end(), notes[1] + 12) == first.end()) first.push_back(notes[1] + 12);
    }
    for (int m = 48 + 12 * octave_; m < 92 + 12 * octave_; ++m)
        if (m >= 0 && m < 128 && std::find(first.begin(), first.end(), m) == first.end()) first.push_back(m);
    return first;
}

// ---------------------------------------------------------------- lead and drone
void Player::leadOn(int midi, float glide) {               // engine.c_lead_on
    std::lock_guard<std::mutex> l(vmx_);
    GVoice* cur = nullptr;
    for (auto& v : gv_) if (!v.drone && !v.rel && !v.done) cur = &v;
    if (cur && glide > 0.005f) { cur->target = midi; cur->glide = glide; cur->midi = midi; return; }   // legato slide
    for (auto& v : gv_) if (!v.drone && !v.rel) { v.rel = true; v.relN = std::max(1, (int) (0.02 * sr_)); }
    double r0 = 1;
    auto note = cache_.get(midi, r0);
    if (!note) return;
    GVoice v;
    v.note = note;
    v.baseRate = r0 * note->rate / sr_;
    v.base = v.target = v.midi = midi;
    v.glide = glide;
    gv_.push_back(v);
}

void Player::leadOff() {                                    // engine.c_lead_off
    std::lock_guard<std::mutex> l(vmx_);
    for (auto& v : gv_)
        if (!v.drone && !v.rel) { v.rel = true; v.relN = std::max(64, (int) (std::min(relSecs_, 0.6f) * sr_)); }
}

void Player::drone(const std::vector<int>& in, float slide) {   // engine.c_drone
    std::lock_guard<std::mutex> l(vmx_);
    std::vector<int> notes(in);
    std::sort(notes.begin(), notes.end());
    const int fade = (int) (0.8 * sr_);
    auto make = [&](int m, int fadeIn) {
        double r0 = 1;
        auto note = cache_.get(m, r0);
        if (!note) return;
        GVoice v;
        v.note = note; v.drone = true; v.gain = 0.7f * 0.95f;
        v.baseRate = r0 * note->rate / sr_;
        v.base = v.target = v.midi = m;
        v.fadeIn = fadeIn; v.env = fadeIn > 0 ? 0.0f : 1.0f;
        gv_.push_back(v);
    };
    if (slide > 0 && !notes.empty()) {                      // voices that stay slide, extras fade, new ones fade in
        std::vector<GVoice*> live;
        for (auto& v : gv_) if (v.drone && !v.rel) live.push_back(&v);
        const size_t had = live.size();
        for (size_t i = had; i > notes.size(); --i) { live[i - 1]->rel = true; live[i - 1]->relN = fade; }
        for (size_t i = 0; i < notes.size() && i < had; ++i) {
            live[i]->target = live[i]->midi = notes[i];
            live[i]->glide = slide * (1.0f + 0.25f * (float) i);   // upper voices arrive a little later
        }
        for (size_t i = had; i < notes.size(); ++i) make(notes[i], (int) (0.6 * sr_));
    } else {
        for (auto& v : gv_) if (v.drone && !v.rel) { v.rel = true; v.relN = fade; }
        for (int m : notes) make(m, 0);
    }
    droneNotes_ = notes;
}

static inline bool frameAt(const Note& nt, double pos, float& l, float& r) {
    const int na = nt.attackFrames(), nl = nt.loopFrames();
    auto get = [&](int idx, float& a, float& b) {
        if (idx < na) { a = nt.attack[(size_t) idx * 2]; b = nt.attack[(size_t) idx * 2 + 1]; return true; }
        if (nl == 0) { a = b = 0; return false; }
        idx = (idx - na) % nl;
        a = nt.loop[(size_t) idx * 2]; b = nt.loop[(size_t) idx * 2 + 1];
        return true;
    };
    const int k = (int) pos;
    const float fr = (float) (pos - k);
    float l0, r0, l1, r1;
    if (!get(k, l0, r0)) return false;
    get(k + 1, l1, r1);
    l = l0 + (l1 - l0) * fr;
    r = r0 + (r1 - r0) * fr;
    return true;
}

void Player::renderG(float* L, float* R, int n) {          // engine._lead_render and _drone_render
    if (gv_.empty()) { T_ += n; return; }
    const double sr = sr_;
    const double bendF = std::pow(2.0, bend_ / 12.0);
    const int nd = std::max<int>(1, (int) droneNotes_.size());
    const int lo = droneNotes_.empty() ? 0 : droneNotes_.front();
    // the drone's motion (engine._drone_env): dead zone, then pulse / swell, thin / bloom
    const float dz = 0.25f;
    auto shape = [&](float a) { return std::abs(a) < dz ? 0.0f : (std::abs(a) - dz) / (1 - dz) * (a > 0 ? 1.0f : -1.0f); };
    const float x = shape(dx_), y = shape(dy_);
    int di = 0;
    for (auto& v : gv_) {
        if (v.done) continue;
        const double rt = std::pow(2.0, (v.target - v.base) / 12.0);
        const double c = v.glide > 0.005f ? std::exp(-1.0 / (v.glide * 0.35 * sr)) : 0.0;
        float pan = 0;
        const int idx = v.drone ? di++ : 0;
        if (v.drone && nd > 1) pan = ((float) idx / (float) (nd - 1) - 0.5f) * 0.8f;
        const int above = v.drone ? v.midi - lo : 0;          // 0 at the root, higher = an upper voice
        float lg = std::min(1.0f, 1.0f - pan), rg = std::min(1.0f, 1.0f + pan);
        for (int i = 0; i < n; ++i) {
            v.ratio = rt + (v.ratio - rt) * c;
            double r = v.ratio;
            if (!v.drone) {
                if (vib_ > 0.01f) r *= std::pow(2.0, vib_ * 0.6 * std::sin(vibPh_ + 2 * 3.14159265358979 * 5.5 * i / sr) / 12.0);
                r *= bendF;
            }
            float sl, sr2;
            if (!frameAt(*v.note, v.pos, sl, sr2)) { v.done = true; break; }
            v.pos += r * v.baseRate;
            float g = v.gain;
            if (v.fadeIn > 0) { v.env = std::min(1.0f, v.env + 1.0f / (float) v.fadeIn); if (v.env >= 1) v.fadeIn = 0; g *= v.env; }
            if (v.rel) {
                v.env -= 1.0f / (float) std::max(1, v.relN);
                if (v.env <= 0) { v.done = true; break; }
                g *= v.env * v.env;
            }
            float gl = lg, gr = rg;
            if (v.drone && (x != 0 || y != 0)) {
                const double t = (double) (T_ + i) / sr;
                if (y < 0) g *= (float) dronePulse(y, t, bpm_);   // pulse: a smooth tempo-synced gate
                else if (y > 0) {                           // swell, with a slow rotating pan
                    g *= 1.0f + 0.6f * y;
                    const double rot = 2 * 3.14159265358979 * t * (0.15 + 0.6 * y) + idx * 1.3;
                    gl *= (float) (1.0 - 0.6 * y * (0.5 + 0.5 * std::sin(rot)));
                    gr *= (float) (1.0 - 0.6 * y * (0.5 - 0.5 * std::sin(rot)));
                }
                if (x < 0 && above > 0) g *= std::max(0.0f, 1.0f + x * 1.1f);           // thin to the root
                else if (x > 0 && above > 0) {                                           // the upper voices breathe
                    const double br = 0.5 + 0.5 * std::sin(2 * 3.14159265358979 * t * (0.25 + 0.5 * x) + idx * 0.9);
                    g *= 1.0f + x * (float) (0.3 + 0.9 * br);
                }
            }
            L[i] += sl * g * gl;
            R[i] += sr2 * g * gr;
        }
    }
    vibPh_ = std::fmod(vibPh_ + 2 * 3.14159265358979 * 5.5 * n / sr, 2 * 3.14159265358979);
    T_ += n;
    gv_.erase(std::remove_if(gv_.begin(), gv_.end(), [](const GVoice& v) { return v.done; }), gv_.end());
    int leads = 0;                                          // the lead keeps its last three (engine: leads[-3:])
    for (auto it = gv_.rbegin(); it != gv_.rend(); ++it) if (!it->drone && ++leads > 3) it->done = true;
}

void Player::render(float* L, float* R, int n) {
    std::lock_guard<std::mutex> l(vmx_);
    for (auto& v : voices_) {
        const auto& a = v.note->attack;
        const auto& lp = v.note->loop;
        const int na = v.note->attackFrames(), nl = v.note->loopFrames();
        for (int i = 0; i < n; ++i) {
            int k = (int) v.pos;
            float fr = (float) (v.pos - k), sl, sr;
            auto frame = [&](int idx, float& l2, float& r2) {
                if (idx < na) { l2 = a[(size_t) idx * 2]; r2 = a[(size_t) idx * 2 + 1]; return true; }
                if (nl == 0) { l2 = r2 = 0; return false; }
                idx = (idx - na) % nl;
                l2 = lp[(size_t) idx * 2]; r2 = lp[(size_t) idx * 2 + 1];
                return true;
            };
            float l0, r0, l1, r1;
            if (!frame(k, l0, r0)) { v.done = true; break; }
            frame(k + 1, l1, r1);
            sl = l0 + (l1 - l0) * fr;
            sr = r0 + (r1 - r0) * fr;
            float g = v.gain;
            if (v.relAt >= 0 && i >= v.relAt) {          // the handheld's release: (1 - x)^2
                float x = (float) (i - v.relAt + v.age) / std::max(1, v.relLen);
                if (x >= 1) { v.done = true; break; }
                g *= (1 - x) * (1 - x);
            }
            L[i] += sl * g * v.lg;
            R[i] += sr * g * v.rg;
            v.pos += v.rate;
        }
        if (v.relAt >= 0) {                               // count the release on across blocks
            int into = std::max(0, n - v.relAt);
            v.age += into;
            v.relAt = std::max(0, v.relAt - n);
        }
    }
    voices_.erase(std::remove_if(voices_.begin(), voices_.end(), [](const Voice& v) { return v.done; }), voices_.end());
    renderG(L, R, n);
}

}  // namespace brick
