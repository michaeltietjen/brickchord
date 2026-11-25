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
