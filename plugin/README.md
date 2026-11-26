# Bricklab Studio (plugin)

The Brick suite as an AU / VST3 instrument for Logic and other DAWs: Chord, Lab,
Glide and Chop in one plugin. It uses the handheld's own sounds: `Source/core/Render.cpp`
is a C++ port of `brickchord/synth.py`'s note renderer, and `Source/core/PatchData.h`
is generated from the same patch list by `tools/export_patches.py`.

Status: Chord plays (pads, the computer keyboard, or MIDI: one key plays that degree's
chord, keys held together play that exact chord). Lab, Glide and Chop come next.

## Build (macOS)

    git clone --depth 1 --branch 8.0.10 https://github.com/juce-framework/JUCE.git ../../JUCE
    cmake -B build -G Xcode -DJUCE_DIR=../../JUCE
    cmake --build build --config Release

(If xcode-select points at the Command Line Tools, prefix both with
`DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer`.) The AU and VST3 are copied
to ~/Library/Audio/Plug-Ins after the build; it runs on macOS 12 and up.
`auval -v aumu Brkl Mtie` validates the AU, and `tests/authost.swift` loads it like a DAW,
plays MIDI into it offline and prints the level:

    swiftc -O tests/authost.swift -o authost && ./authost

## Tests (any C++17 compiler, no JUCE)

    g++ -O2 -std=c++17 -o render_check tests/render_check.cpp Source/core/Render.cpp
    g++ -O2 -std=c++17 -pthread -o engine_check tests/engine_check.cpp Source/core/Engine.cpp Source/core/Render.cpp

`tests/render_check` prints each sound's length and level at C4, to compare with
`synth.render_note` in Python.

## License

The plugin is built on JUCE (https://juce.com). To release it as open source, JUCE's
terms mean this plugin folder would be AGPLv3 (the rest of the repository stays MIT).
That choice is made before the first release.

## Two plugins: the sound, or the notes

- **Bricklab Studio** (AU, VST3, Standalone) is the instrument: its own sounds.
- **Bricklab Studio MIDI** has no sound of its own: it plays whatever instrument you give it its
  chords (channel 1, the bass on channel 2), leads and drones (the drone's pulse goes out as
  expression, CC 11).
  - Logic: the AU, in the MIDI FX slot above any instrument.
  - Ableton Live, Bitwig, Reaper, FL Studio: the VST3, on a track of its own; set your synth
    track's MIDI input to it.

## Pages: one layer per instance

Each instance plays one page, saved with your project. Layer them on separate tracks.

- **Glide** (the default): five voices and a sub hold a chord and glide into the next one, each
  on its own path. Pads play the scale's chords (the same one again lets go); a keyboard plays
  one note as that degree's chord, or any chord you hold, and how hard you play sets its level.
  Let go and the chord holds. Glide and fade times in seconds or bars of your tempo; path (Smooth,
  Ease, Bounce, Scale steps...); moves (Bloom, Cascade, Spiral, Swoop...); chord type; sub; Tone, a
  low-pass the mod wheel opens. Pitch bend bends the whole chord; the mod wheel stretches the glides
  (up to 4x) and swells them. "more" holds the timing, bend range and MIDI out settings. The screen
  draws each voice's path and where it's headed. After a wide glide a voice changes to a sound
  rendered nearer its note, crossfading, so it doesn't end stretched.
- **Chord**: the chord pads; 7th, sus4, 9th, flip (saved and automatable); eight play modes;
  bass modes; latch; octave. Key velocity sets the level.
- **Drone**: tap a pad or key to drone on it (root, fifth, octaves; 3rd adds the third), the
  same again to stop. Slide glides to the next drone. Pulse | Swell and Thin | Bloom shape it;
  the mod wheel pulses it and pitch bend thins or blooms it.

Nine scales: Major, Minor, Dorian, Mixolydian, Lydian, Phrygian, Locrian, Harmonic and Melodic minor.
Twelve presets (Presets menu, or your DAW's preset list) keep your key and scale. **drag MIDI**
drags the last eight bars you played into your DAW as a clip. The window resizes.

## MIDI out (Bricklab Studio MIDI)

Glide goes out as MPE: each voice on its own channel (2 to 7) with a 48-semitone bend range, its
glide as pitch bend, its fades and swells as pressure, the mod wheel's swell as timbre (CC 74).
Turn MPE on in your synth (Pigments: Settings, MPE). Or set Out to notes for any synth: the chords
as plain notes, the fades as expression (CC 11). Chord sends chords on channel 1 and the bass on
channel 2; Drone sends its pulse as expression.
