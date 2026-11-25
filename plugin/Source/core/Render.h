// Bricklab Studio: renders one note of a sound the way the handheld does
// (brickchord/synth.py render_note): band-limited wavetables shaped per control
// block by the filter, envelopes frozen after the attack so the rest loops
// seamlessly. A note is an attack segment and, for sustaining sounds, a loop.
#pragma once
#include <memory>
#include <vector>
#include "Patch.h"

namespace brick {

// the rate notes render at: the host's (44.1 or 48 kHz), so they play back untouched. The handheld
// runs at 22050; rendering at the host rate keeps the top octave clean instead of resampled.
// Changed only by the NoteCache thread between renders (NoteCache::setRate).
inline int kSR = 44100;

struct Note {                                 // interleaved stereo float, L R L R
    std::vector<float> attack, loop;          // loop empty: the sound doesn't sustain
    int attackFrames() const { return (int) attack.size() / 2; }
    int loopFrames() const { return (int) loop.size() / 2; }
};

std::shared_ptr<Note> renderNote(int midi, const Patch& p, unsigned seed = 1);

}  // namespace brick
