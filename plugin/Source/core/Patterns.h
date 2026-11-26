// The handheld's play modes (main.PLAY_MODES) and bass modes (synth.BASS_MODES), as note
// events: what engine.py's c_chord, _on_step, _strum, _arp_step, _repeat, _harp_run and
// _bass_step play, minus the sound. The plugin turns these events into its own voices,
// MIDI out, or both. Channel 1 is the chord, channel 2 the synth bass.
#pragma once
#include <cstdint>
#include <vector>

namespace brick {

// the handheld has 15; the plugin keeps the eight that a DAW's own arpeggiator doesn't already do better
inline const char* const kPlayModes[] = {
    "Chord", "Slop", "Strum Folk", "Strum Skank", "Harp Up", "Arp 1/8 Up", "Arp 1/16 Up-Down", "Repeat 1/8"};
constexpr int kNumPlayModes = 8;
inline const char* const kBassModes[] = {"Synth", "Pulse", "Octaves", "Walk", "Sub + Patch", "Patch", "Off"};
constexpr int kNumBassModes = 7;

struct NoteEvent {
    int64_t at;          // sample time
    bool on;
    int ch, note;        // ch 1: chord, ch 2: synth bass
    float gain = 1, pan = 0;
    float rel = -1;      // note off: release seconds for the built-in sound (-1: the sound's own)
    uint32_t id = 0;     // pairs an off with its on
};

class Patterns {
public:
    void setMode(int m) { mode_ = m; }
    void setBassMode(int b) { bassMode_ = b; }
    void setArpOctaves(int n) { arpOct_ = n < 1 ? 1 : (n > 4 ? 4 : n); }
    void setTempo(double bpm, double sr) { bpm_ = bpm > 20 ? bpm : 120; sr_ = sr; }
    void chord(const std::vector<int>& notes, int64_t at, float vel = 0.85f);   // voiced notes; notes[0] is the patch's bass note
    void clear(int64_t at);                                    // all chord buttons let go
    void step(int64_t s, int64_t at);                          // a 16th of the clock, at sample time at
    void take(int64_t upto, std::vector<NoteEvent>& out);      // the events before upto, in order

private:
    enum Tag { Held, Harp, Strum, Arp, Bass, NTags };
    struct Live { int ch, note; uint32_t id; };
    const char* mode() const { return kPlayModes[mode_]; }
    void note(int64_t at, int ch, int m, float gain, float pan, Tag tag, int64_t gate = -1, float rel = -1);
    void release(Tag tag, int64_t at, float rel = -1);
    void strum(char c, int64_t at);
    void arpStep(int64_t at);
    void repeat(int64_t at, int k);
    void bassStart(int64_t at, bool changed);
    void bassStep(int64_t at);
    std::vector<int> arpNotes() const;

    int mode_ = 0, bassMode_ = 0, arpOct_ = 1;
    float vel_ = 0.85f;                                 // how hard the chord was played: scales every note
    double bpm_ = 120, sr_ = 44100;
    std::vector<int> notes_, pat_, arp_;                // notes_ empty: no chord held
    int64_t chordT_ = INT64_MIN / 2, bassT0_ = INT64_MIN / 2;
    int patI_ = 0, patDir_ = 1, bassI_ = 0;
    std::vector<Live> live_[NTags];
    std::vector<NoteEvent> q_;
    uint32_t nextId_ = 1, active_[3][128] = {};
    uint32_t rng_ = 12345;
    float rnd() { rng_ = rng_ * 1664525u + 1013904223u; return (rng_ >> 8) / 16777216.0f; }
};

}  // namespace brick
