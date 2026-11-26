// Bricklab Studio: the playing engine. Notes are rendered off the audio thread
// (Render.cpp, the handheld's renderer) and played back from the cache: attack,
// then the seamless loop while held, then the handheld's release curve. Playback
// reads each note at its own speed, so the plugin runs at any host sample rate and
// a note that isn't rendered yet sounds as the nearest one that is, pitched.
#pragma once
#include <algorithm>
#include <cmath>
#include <array>
#include <atomic>
#include <condition_variable>
#include <deque>
#include <memory>
#include <mutex>
#include <thread>
#include <vector>
#include "Render.h"
#include "Theory.h"

namespace brick {

class NoteCache {
public:
    NoteCache();
    ~NoteCache();
    void setSound(int index);                       // which sound renders; clears the queue
    void setRate(int sampleRate);                   // render at this rate (the host's, up to 48 kHz); clears everything
    int sound() const { return sound_.load(); }
    void want(const std::vector<int>& midis);       // render these next (most wanted first)
    // recorded notes in place of a rendered sound (midi, note): every other note plays the nearest, pitched
    void setRecorded(int id, const std::vector<std::pair<int, std::shared_ptr<Note>>>& rec);
    std::shared_ptr<Note> get(int midi, double& ratio) const;   // nearest ready note and the pitch ratio to it
    int ready() const { return ready_.load(); }
    // the synth bass under the chords (synth.render_bass): mono, no loop, 28..63
    std::shared_ptr<Note> bass(int midi) const;

private:
    void run();
    mutable std::mutex mx_;
    std::condition_variable cv_;
    std::deque<int> todo_;
    std::array<std::shared_ptr<Note>, 128> notes_{};
    std::array<std::shared_ptr<Note>, 128> bass_{};
    std::atomic<int> sound_{0}, ready_{0}, gen_{0}, rate_{44100};
    std::atomic<bool> quit_{false};
    bool recorded_ = false;
    std::thread th_;
};

struct Voice {
    std::shared_ptr<Note> note;
    double pos = 0, rate = 1;        // position in the note's frames (attack then loop), frames per output sample
    float gain = 1, lg = 1, rg = 1;
    int relAt = -1, relLen = 0, age = 0;   // relAt: output samples from now until release starts (-1 held)
    bool bass = false, done = false;
    int ch = 1;
    int midi = 0;
};

// a voice whose pitch moves: the lead (glide, bend, vibrato) and the sliding drone
struct GVoice {
    std::shared_ptr<Note> note;
    double pos = 0, baseRate = 1, ratio = 1;   // ratio: the glide, 2^((target - base) / 12) when it has arrived
    int base = 60, target = 60, midi = 60;
    float glide = 0, env = 1, gain = 0.95f;
    int fadeIn = 0, relN = 1;
    bool rel = false, drone = false, done = false;
    bool air = false;                          // a breathing overtone over the drone
    float airPer = 10, airPh = 0, shown = 0;   // its cycle (seconds, phase); the level last played, for the screen
};

class Player {
public:
    explicit Player(NoteCache& cache) : cache_(cache) {}
    void prepare(double sampleRate) { sr_ = sampleRate; }
    // the chord buttons: the chord on a degree of the key, voiced as the handheld does
    Chord playDegree(int degree, const Mods& m);
    void setColour(int c) { colour_ = c; }               // 0: the scale's chords; else a colour shape on each pad's root
    Chord playExact(const std::vector<int>& notes);    // keys held together: that chord
    void release();
    void setKey(int key, Scale s) { key_ = key; scale_ = s; prev_.clear(); }
    int key() const { return key_; }
    Scale scale() const { return scale_; }
    void setRelease(float secs) { relSecs_ = secs; }
    void setBassLevel(float g) { bassGain_ = g; }
    void setOctave(int o) { octave_ = o; }           // the chords up or down whole octaves
    // the notes themselves come from Patterns (play mode and bass mode): ch 1 the sound, ch 2 the synth bass
    void noteOn(int ch, int midi, float gain, float pan);
    void noteOff(int ch, int midi, float relSecs);       // relSecs < 0: the sound's own release
    void allOff();
    // the Lead page (engine.c_lead_on / c_lead_off / c_lead_mod) and the Drone page (engine.c_drone)
    void leadOn(int midi, float glideSecs);
    void leadOff();
    void leadMod(float bendSemis, float vib) { bend_ = bendSemis; vib_ = vib; }
    void drone(const std::vector<int>& notes, float slideSecs);   // empty: the drone fades
    void droneMod(float x, float y) { dx_ = x; dy_ = y; }          // x: thin (-) / bloom (+), y: pulse (-) / swell (+)
    void droneAir(float a) { air_ = a; }                           // 0..1: overtones that breathe in and out, high above
    void droneDrift(float d) { drift_ = d; }                       // 0..1: how often two voices slowly trade places
    // the drone's voices as they sound, for the screen
    static constexpr int kShown = 10;
    std::array<std::atomic<float>, kShown> dCents{}, dLevel{};
    std::atomic<int> dCount{0};
    void setTempo(double bpm) { bpm_ = bpm > 20 ? bpm : 120; }
    std::vector<int> lastNotes() const { std::lock_guard<std::mutex> l(vmx_); return last_; }   // the last chord as voiced
    std::vector<int> wanted() const;                     // every note a chord button can ask for, likely first
    void render(float* L, float* R, int n);              // adds into L and R

private:
    void start(const std::vector<int>& notes);
    NoteCache& cache_;
    std::vector<Voice> voices_;
    std::vector<GVoice> gv_;
    std::vector<int> droneNotes_;
    float bend_ = 0, vib_ = 0, dx_ = 0, dy_ = 0, air_ = 0, drift_ = 0;
    int colour_ = 0;
    double driftLeft_ = 0;
    uint32_t rng_ = 4242;
    float rnd() { rng_ = rng_ * 1664525u + 1013904223u; return (float) (rng_ >> 8) / 16777216.0f; }
    double vibPh_ = 0, bpm_ = 120;
    int64_t T_ = 0;
    void renderG(float* L, float* R, int n);
    std::vector<int> prev_, last_;
    int key_ = 9;
    Scale scale_ = Scale::Minor;
    double sr_ = 44100;
    float relSecs_ = 0.4f;
    float bassGain_ = 0.3f;
    int octave_ = 0;
    mutable std::mutex vmx_;                                      // the UI thread starts chords too
};

int degreeOf(int note, int key, Scale scale);

// the drone's pulse (engine._drone_env, stick down): a smooth tempo-synced gate. y: -1..0 after the
// dead zone; t in seconds. 1 = full level.
inline double dronePulse(float y, double t, double bpm) {
    const double beat = 60.0 / bpm;
    const int div = y > -0.4f ? 2 : (y > -0.75f ? 4 : 8);         // 1/8, 1/16, 1/32
    const double len = beat / div, ph = std::fmod(t, len) / len;
    const double depth = std::min(1.0, -y * 1.1), duty = 0.6 - 0.3 * depth, edge = 0.12;
    const double on = std::clamp(ph / edge, 0.0, 1.0) * std::clamp((duty - ph) / edge, 0.0, 1.0);
    return (1 - depth) + depth * (0.5 - 0.5 * std::cos(3.14159265358979 * on));
}           // which degree of the key a MIDI note is nearest

}  // namespace brick
