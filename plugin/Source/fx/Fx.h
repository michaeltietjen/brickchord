// Two things the Drone page borrows from Summoner: the Cloud (the last second of sound cut into
// overlapping grains) and the sympathetic strings (a set of strings tuned to the drone that ring
// when the strum plays into them). Both are built on open-source sound engines by Emilie Gillet
// (MIT licence, see third_party/eurorack). The names and settings are ours.
#pragma once
#include <memory>

namespace brick {

class Cloud {
public:
    Cloud();
    ~Cloud();
    void prepare(double sampleRate);
    // size, pitch (octaves, -1..1), density, texture, spread, feedback, reverb: all 0..1 but pitch
    void set(float position, float size, float pitchOct, float density, float texture, float spread, float feedback, float reverb);
    void process(const float* inL, const float* inR, float* outL, float* outR, int n, float gain);   // adds the wet sound
private:
    struct Impl;
    std::unique_ptr<Impl> d;
};

class SympStrings {
public:
    SympStrings();
    ~SympStrings();
    void prepare(double sampleRate);
    void setNote(float midi) { note_ = midi; }               // what the strings are tuned around
    void process(const float* inL, const float* inR, float* outL, float* outR, int n, float gain);   // adds their ringing
private:
    struct Impl;
    std::unique_ptr<Impl> d;
    float note_ = 48, comp_ = 0;
};

}  // namespace brick
