// The Glide page: Brickglide's chord voices (ambient.py amb_play, amb_follow, amb_voicelead,
// amb_glide_all, amb_bloom; engine.py c_amb and _amb_render). Five voices and a sub hold a
// chord and glide, each along its own path, into the next one. Played from a keyboard or the
// pads; pitch bend bends the whole chord, the mod wheel stretches the glides and swells it.
#pragma once
#include <array>
#include <atomic>
#include <cstdint>
#include <string>
#include <vector>
#include "Engine.h"
#include "Theory.h"

namespace brick {

inline const char* const kGlideChords[] = {"Triad", "Seventh", "Ninth", "Eleventh", "Sus2", "Sus4", "Quartal",
                                           "Lydian", "Minor 11", "Major 9", "Fifths", "Cluster", "Open"};
constexpr int kNumGlideChords = 13;
inline const char* const kGlidePaths[] = {"Smooth", "Linear", "Ease", "Swell", "Bounce", "Late", "Snap",
                                          "Wobble", "Semitones", "Scale steps"};
constexpr int kNumGlidePaths = 10;
inline const char* const kGlideTimings[] = {"Together", "By distance", "Bass lags", "Bass leads", "Loose"};
constexpr int kNumGlideTimings = 5;
inline const char* const kGlideMoves[] = {"No move", "Bloom", "Cascade up", "Cascade down", "Spiral", "Swoop",
                                          "Scatter", "Converge", "Fall"};
constexpr int kNumGlideMoves = 9;
inline const float kGlideTimes[] = {0.25f, 0.4f, 0.6f, 1.0f, 1.5f, 2.0f, 4.0f, 6.0f, 8.0f, 12.0f, 20.0f, 30.0f, 60.0f};
constexpr int kNumGlideTimes = 13;
inline const float kGlideFades[] = {0.2f, 0.5f, 1.0f, 2.0f, 4.0f, 8.0f, 15.0f};
constexpr int kNumGlideFades = 7;
inline const int kGlideBends[] = {1, 2, 3, 5, 7, 12, 24};   // semitones at full pitch bend
constexpr int kNumGlideBends = 7;
constexpr int kGlideVoices = 6;                             // five chord voices and the sub

struct GlideSettings {
    int chord = 0, path = 2, timing = 0, move = 0;
    float time = 1.5f, fade = 1.0f;
    bool sub = true;
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
    void bloom();
    void setBend(float semis) { bend_ = semis * 100.0f; }
    void setSwell(float x) { swell_ = x; }
    void render(float* L, float* R, int n);              // adds into L and R
    // what each voice is doing, for the screen and for MIDI out (MPE)
    std::array<std::atomic<float>, kGlideVoices> cents{}, level{};
    std::array<std::atomic<bool>, kGlideVoices> on{};
    std::array<std::atomic<float>, kGlideVoices> target{};   // where each voice is headed (cents)
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
        double ph = 0, dr = 0, drT = 0;
        int drN = 0;
        std::shared_ptr<Note> note;                      // the sound, rendered at sampleMidi
        int sampleMidi = -1;
        double r0 = 1, pos = 0;
    };
    void push(int i, double tgtCents, double glide, int shape, double delay, const std::vector<double>& via, bool jump);
    std::vector<int> voicelead(const std::vector<int>& pcs, int rootPc) const;   // the five voices' new notes
    void glideAll(const std::vector<int>& notes, float glideX);
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
    float bend_ = 0, swell_ = 0;
    int curDeg_ = -1;
    uint32_t rng_ = 98765;
};

}  // namespace brick
