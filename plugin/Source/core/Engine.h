// Bricklab Studio: the playing engine. Notes are rendered off the audio thread
// (Render.cpp, the handheld's renderer) and played back from the cache: attack,
// then the seamless loop while held, then the handheld's release curve. Playback
// reads each note at its own speed, so the plugin runs at any host sample rate and
// a note that isn't rendered yet sounds as the nearest one that is, pitched.
#pragma once
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
    int sound() const { return sound_.load(); }
    void want(const std::vector<int>& midis);       // render these next (most wanted first)
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
    std::atomic<int> sound_{0}, ready_{0}, gen_{0};
    std::atomic<bool> quit_{false};
    std::thread th_;
};

struct Voice {
    std::shared_ptr<Note> note;
    double pos = 0, rate = 1;        // position in the note's frames (attack then loop), frames per output sample
    float gain = 1, lg = 1, rg = 1;
    int relAt = -1, relLen = 0, age = 0;   // relAt: output samples from now until release starts (-1 held)
    bool bass = false, done = false;
    int midi = 0;
};

class Player {
public:
    explicit Player(NoteCache& cache) : cache_(cache) {}
    void prepare(double sampleRate) { sr_ = sampleRate; }
    // the chord buttons: the chord on a degree of the key, voiced as the handheld does
    Chord playDegree(int degree, const Mods& m);
    Chord playExact(const std::vector<int>& notes);    // keys held together: that chord
    void release();
    void setKey(int key, Scale s) { key_ = key; scale_ = s; prev_.clear(); }
    int key() const { return key_; }
    Scale scale() const { return scale_; }
    void setRelease(float secs) { relSecs_ = secs; }
    void setBass(bool on) { bassOn_ = on; }
    void setBassLevel(float g) { bassGain_ = g; }
    bool bassOn() const { return bassOn_; }
    std::vector<int> lastNotes() const { std::lock_guard<std::mutex> l(vmx_); return last_; }   // the last chord as voiced
    std::vector<int> wanted() const;                     // every note a chord button can ask for, likely first
    void render(float* L, float* R, int n);              // adds into L and R

private:
    void start(const std::vector<int>& notes);
    NoteCache& cache_;
    std::vector<Voice> voices_;
    std::vector<int> prev_, last_;
    int key_ = 9;
    Scale scale_ = Scale::Minor;
    double sr_ = 44100;
    float relSecs_ = 0.4f;
    bool bassOn_ = true;
    float bassGain_ = 0.3f;
    mutable std::mutex vmx_;                                      // the UI thread starts chords too
};

int degreeOf(int note, int key, Scale scale);           // which degree of the key a MIDI note is nearest

}  // namespace brick
