// Bricklab Studio: a sound as the handheld defines it (brickchord/synth.py).
#pragma once
#include <vector>

namespace brick {

enum class Wave { Saw, Square, Pulse, Tri, Sine, Vox };
enum class Engine { VA, FM, Pluck, Noise };

struct Osc {            // synth.py osc: (wave, cents, level, pan, octave)
    Wave wave;
    float cents, level, pan;
    int octave;
};

struct FMParams { float ratio, idx, idxS, idxT, det; };
struct PluckParams { float bright, t60, body; };
struct NoiseParams { float width, tilt, floor; };

struct Patch {
    const char* name;
    int group;                      // 0 chord, 1 lead, 2 drone
    Engine engine;
    std::vector<Osc> oscs;
    float cutoff, res, fenv, fa, fd, fs, a, d, s, r, pwm, gain;
    bool ladder;
    float drive, noise;             // noise: the VA engine's noise level (0 = none)
    bool noiseDark;
    FMParams fm;
    PluckParams pluck;
    NoiseParams noiseCfg;           // the Noise engine's settings
};

}  // namespace brick
