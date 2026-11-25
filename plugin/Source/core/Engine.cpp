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
            if (todo_.empty() || (todo_.front() >= 1000)) {
                int b = !todo_.empty() ? todo_.front() - 1000 : nextBass;
                if (!todo_.empty()) todo_.pop_front();
                if (b > 63 || bass_[(size_t) std::min(b, 127)]) { if (b == nextBass) ++nextBass; continue; }
                l.unlock();
                auto bn = renderBass(b);
                std::lock_guard<std::mutex> l2(mx_);
                bass_[(size_t) b] = bn;
                if (b == nextBass) ++nextBass;
                continue;
            }
            m = todo_.front();
            todo_.pop_front();
            snd = sound_.load();
            gen = gen_.load();
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

void Player::start(const std::vector<int>& notes) {
    std::lock_guard<std::mutex> l(vmx_);
    const int xf = (int) (0.025 * sr_);
    for (auto& v : voices_)                             // the last chord lets go (engine c_chord: release "held")
        if (v.relAt < 0) { v.relAt = 0; v.relLen = v.bass ? (int) (0.02 * sr_) : std::max(xf, (int) (relSecs_ * sr_)); }
    for (size_t i = 1; i < notes.size(); ++i) {         // the patch's bass note gives way to the synth bass
        Voice v;
        double ratio = 1;
        v.note = cache_.get(notes[i], ratio);
        if (!v.note) continue;
        v.rate = ratio * kSR / sr_;
        v.gain = 0.95f;
        v.midi = notes[i];
        voices_.push_back(v);
    }
    if (bassOn_) {                                       // an octave under the patch's bass note
        int root = notes[0] - 12;
        while (root < 28) root += 12;
        Voice b;
        b.note = cache_.bass(root);
        if (b.note) { b.rate = kSR / sr_; b.bass = true; b.gain = 1.0f; b.midi = root; voices_.push_back(b); }
    }
    if (voices_.size() > 48) {                           // keep the count bounded: oldest tails go first
        for (size_t i = 0; i + 48 < voices_.size(); ++i)
            if (voices_[i].relAt >= 0) { voices_[i].relLen = std::min(voices_[i].relLen, (int) (0.012 * sr_)); }
    }
}

void Player::release() {
    std::lock_guard<std::mutex> l(vmx_);
    for (auto& v : voices_)
        if (v.relAt < 0) { v.relAt = 0; v.relLen = v.bass ? (int) (0.08 * sr_) : (int) (relSecs_ * sr_); }
}

std::vector<int> Player::wanted() const {              // live.py wanted(): the chords' notes first
    std::vector<int> first, prev;
    for (int d = 0; d < 7; ++d) {
        Chord c = buildChord(key_, scale_, d, Mods{});
        auto notes = voice(c.root, c.iv, prev);
        int root = notes[0] - 12;
        while (root < 28) root += 12;
        first.insert(first.begin(), 1000 + root);         // the bass under it, first of all
        for (size_t i = 1; i < notes.size(); ++i)
            if (std::find(first.begin(), first.end(), notes[i]) == first.end()) first.push_back(notes[i]);
        if (std::find(first.begin(), first.end(), notes[1] + 12) == first.end()) first.push_back(notes[1] + 12);
    }
    for (int m = 48; m < 92; ++m)
        if (std::find(first.begin(), first.end(), m) == first.end()) first.push_back(m);
    return first;
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
}

}  // namespace brick
