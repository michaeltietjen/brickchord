// The Glide page: Brickglide's chord voices (ambient.py amb_play, amb_follow, amb_voicelead,
// amb_glide_all, amb_bloom; engine.py c_amb and _amb_render). Five voices and a sub hold a
// chord and glide, each along its own path, into the next one. Played from a keyboard or the
// pads; pitch bend bends the whole chord, the mod wheel stretches the glides and swells it.
#pragma once
#include <array>
#include <atomic>
#include <cstdint>
#include <cstdio>
#include <string>
#include <vector>
#include "Curves.h"
#include "Engine.h"
#include "Theory.h"

namespace brick {

inline const char* const kGlideChords[] = {"Triad", "Seventh", "Ninth", "Eleventh", "Sus2", "Sus4", "Quartal",
                                           "Lydian", "Minor 11", "Major 9", "Fifths", "Cluster", "Open"};
constexpr int kNumGlideChords = 13;
inline const char* const kGlidePaths[] = {"Smooth", "Linear", "Ease", "Swell", "Bounce", "Late", "Snap",
                                          "Wobble", "Semitones", "Scale steps", "Custom (curves)"};
constexpr int kNumGlidePaths = 11;
constexpr int kPathCustom = 10;
// expression routing: what drives each voice's pressure and timbre
inline const char* const kPressureSources[] = {"Off", "Level (fades)", "Glide curve", "LFO", "Mod wheel", "Velocity"};
constexpr int kNumPressureSources = 6;
inline const char* const kTimbreSources[] = {"Mod wheel", "Glide curve", "LFO", "Voice height", "Level (fades)", "Off"};
constexpr int kNumTimbreSources = 6;
inline const char* const kGlideTimings[] = {"Together", "By distance", "Bass lags", "Bass leads", "Loose"};
constexpr int kNumGlideTimings = 5;
inline const char* const kGlideMoves[] = {"No move", "Bloom", "Cascade up", "Cascade down", "Spiral", "Swoop",
                                          "Scatter", "Converge", "Fall"};
constexpr int kNumGlideMoves = 9;
// which voice takes which note of the next chord: the nearest, or trading places so they cross on the way
inline const char* const kGlideCrossings[] = {"No crossing", "Auto cross", "Swap middle", "Outside in", "Mirror",
                                              "Rotate up", "Rotate down", "Mirror all"};
constexpr int kNumGlideCrossings = 8;
inline const float kGlideTimes[] = {0.25f, 0.4f, 0.6f, 1.0f, 1.5f, 2.0f, 4.0f, 6.0f, 8.0f, 12.0f, 20.0f, 30.0f, 60.0f};
constexpr int kNumGlideTimes = 13;
inline const float kGlideFades[] = {0.2f, 0.5f, 1.0f, 2.0f, 4.0f, 8.0f, 15.0f};
constexpr int kNumGlideFades = 7;
// glide and fade times: seconds, then bars of the host's tempo (so a glide lands on the downbeat)
inline const float kBarLengths[] = {0.25f, 0.5f, 1.0f, 2.0f, 4.0f, 8.0f};
inline const char* const kBarNames[] = {"1/4 bar", "1/2 bar", "1 bar", "2 bars", "4 bars", "8 bars"};
constexpr int kNumBarLengths = 6;
inline std::vector<std::string> timeNames(const float* secs, int n, const char* prefix) {
    std::vector<std::string> out;
    for (int i = 0; i < n; ++i) {
        char b[48];
        std::snprintf(b, sizeof b, "%s %g s", prefix, (double) secs[i]);
        out.push_back(b);
    }
    for (auto* b : kBarNames) out.push_back(std::string(prefix) + " " + b);
    return out;
}
inline float timeSeconds(const float* secs, int n, int index, double bpm) {
    if (index < n) return secs[index < 0 ? 0 : index];
    const int k = index - n < kNumBarLengths ? index - n : kNumBarLengths - 1;
    return (float) (kBarLengths[k] * 4.0 * 60.0 / (bpm > 20 ? bpm : 120.0));
}
inline const int kGlideBends[] = {1, 2, 3, 5, 7, 12, 24};   // semitones at full pitch bend
constexpr int kNumGlideBends = 7;
// the drone's chords: what sounds over the root
inline const char* const kDroneChords[] = {"Root and fifth", "Open", "Triad", "Seventh", "Ninth", "Sus2", "Sus4", "Quartal", "Fifths"};
constexpr int kNumDroneChords = 9;
constexpr int kGlideVoices = 6;                             // five chord voices and the sub

struct GlideSettings {
    int chord = 0, path = 2, timing = 0, move = 0, cross = 0;
    float time = 1.5f, fade = 1.0f;
    bool sub = true;
    float tone = 1.0f;                           // 0..1: the low-pass on the voices (1: open)
    int prSrc = 0, tbSrc = 0;                    // kPressureSources, kTimbreSources
    float prDepth = 1, tbDepth = 1, lfoRate = 0.5f;
};

class GlideEngine {
public:
    explicit GlideEngine(NoteCache& cache);
    void prepare(double sr) { sr_ = sr; }
    void setKey(int key, Scale s) { key_ = key; scale_ = s; }
    void set(const GlideSettings& s) { st_ = s; }
    // chords (all on the audio thread); each returns the chord's name, empty if it stopped
    std::string playDegree(int deg, const Mods& m, float glideX, bool toggle);
    std::string follow(std::vector<int> notes, float glideX);
    void stop();
    void silence();                                      // everything off at once (a page change)
    void setSilent(bool s) { silent_ = s; }              // the MIDI builds: voices move, no sound is fetched
    void bloom();
    void setOctave(int o) { oct_ = o < -2 ? -2 : (o > 2 ? 2 : o); }   // the next chord lands this many octaves away
    void setBend(float semis) { bend_ = semis * 100.0f; }
    void setSwell(float x) { swell_ = x; }
    void setVelocity(float v) { vel_ = v < 0.05f ? 0.05f : (v > 1 ? 1 : v); }   // the next chord's: scales its level
    float velocity() const { return vel_; }
    float swell() const { return swell_; }
    void render(float* L, float* R, int n);              // adds into L and R
    // what each voice is doing, for the screen and for MIDI out (MPE)
    std::array<std::atomic<float>, kGlideVoices> cents{}, level{};
    std::array<std::atomic<bool>, kGlideVoices> on{};
    std::array<std::atomic<float>, kGlideVoices> target{};   // where each voice is headed (cents)
    std::array<std::atomic<float>, kGlideVoices> pressure{}; // 0..1: each voice's pressure, as routed
    std::array<std::atomic<float>, kGlideVoices> timbre{};   // 0..1: each voice's timbre (0.5 centre), as routed
    std::array<std::atomic<float>, kGlideVoices> progress{}; // 0..1: how far through its glide (1: arrived)
    std::atomic<int> chordSerial{0};                         // goes up with every chord played
    GlideCurves curves;                                      // the MPE editor's curves
    bool anyOn() const;

private:
    struct V {
        bool on = false;
        float level = 0.6f, pan = 0, vib = 4, rate = 0.2f, drift = 8;
        double cur = 0, tgt = 0;                         // cents (MIDI note x 100)
        std::vector<double> path;                        // a glide: the cents it passes through
        int64_t p0 = 0;
        double delay = 0, dur = 0;
        int shape = 0;
        float lvl = 0, lvlT = 0;
        float prog = 1, prOut = 1, tbOut = 0.5f, pgPrev = 1;
        double ph = 0, dr = 0, drT = 0;
        int drN = 0;
        std::shared_ptr<Note> note;                      // the sound, rendered at sampleMidi
        int sampleMidi = -1;
        double r0 = 1, pos = 0;
        std::shared_ptr<Note> old;                       // the sound it's crossfading from, after a long glide
        int oldMidi = -1, xf = 0, xfLen = 1;
        double oldR0 = 1, oldPos = 0;
        float z1[2] = {}, z2[2] = {};                    // the low-pass, per side
    };
    void push(int i, double tgtCents, double glide, int shape, double delay, const std::vector<double>& via, bool jump);
    std::vector<int> voicelead(const std::vector<int>& pcs, int rootPc) const;   // the five voices' new notes
    void glideAll(const std::vector<int>& notes, float glideX);
    void cross(std::vector<int>& notes);                 // deal the chord's notes out so the voices cross
    void subFollow(const std::vector<int>& notes, double secs, bool jump);
    void layOut(const std::vector<int>& notes);
    std::string apply(const std::vector<int>& pcs, int rootPc, float glideX);
    std::vector<double> scaleVia(double from, double to) const;
    static double shapeAt(double p, int shape);
    static double pathAt(const std::vector<double>& path, double el, double dur, int shape);
    float rnd() { rng_ = rng_ * 1664525u + 1013904223u; return (rng_ >> 8) / 16777216.0f; }

    NoteCache& cache_;
    GlideSettings st_;
    V v_[kGlideVoices];
    double sr_ = 44100;
    int64_t t_ = 0;
    int key_ = 9;
    Scale scale_ = Scale::Minor;
    float bend_ = 0, swell_ = 0, vel_ = 0.85f;
    double lfoPh_ = 0;
    float levelOf(int i) const { return v_[i].level * (0.45f + 0.55f * vel_ / 0.85f); }
    int curDeg_ = -1, oct_ = 0;
    bool silent_ = false;
    uint32_t rng_ = 98765;
    int crossTurn_ = 0;
};

}  // namespace brick
