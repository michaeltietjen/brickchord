# Bricklab Studio: the Brick suite (Chord, Lab, Glide, Chop) as an AU / VST3 instrument.
# Build (macOS):
#   git clone --depth 1 --branch 8.0.10 https://github.com/juce-framework/JUCE.git ../../JUCE
#   cmake -B build -G Xcode -DJUCE_DIR=../../JUCE
#   cmake --build build --config Release
cmake_minimum_required(VERSION 3.22)
# set before project(): macOS 12 and up, Apple silicon and Intel
set(CMAKE_OSX_DEPLOYMENT_TARGET "12.0" CACHE STRING "")
set(CMAKE_OSX_ARCHITECTURES "arm64;x86_64" CACHE STRING "")
project(BricklabStudio VERSION 0.1.0)

set(CMAKE_CXX_STANDARD 17)

if(NOT JUCE_DIR)
    set(JUCE_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../../JUCE")
endif()
add_subdirectory(${JUCE_DIR} JUCE)

juce_add_plugin(BricklabStudio
    COMPANY_NAME "Bricklab Studios"
    BUNDLE_ID "io.github.michaeltietjen.bricklabstudio"
    PLUGIN_MANUFACTURER_CODE Mtie
    PLUGIN_CODE Brkl
    FORMATS AU VST3 Standalone
    PRODUCT_NAME "Bricklab Studio"
    DESCRIPTION "The Brick suite: chords, songs, glides and chops"
    IS_SYNTH TRUE
    NEEDS_MIDI_INPUT TRUE
    NEEDS_MIDI_OUTPUT FALSE
    IS_MIDI_EFFECT FALSE
    EDITOR_WANTS_KEYBOARD_FOCUS TRUE
    AU_MAIN_TYPE kAudioUnitType_MusicDevice
    VST3_CATEGORIES Instrument Synth
    COPY_PLUGIN_AFTER_BUILD TRUE)

# the same code, built twice: the instrument (AU, VST3, Standalone; MIDI out included)
# and, for Logic, a MIDI FX that only sends its chords to the instrument after it
juce_add_plugin(BricklabStudioMIDI
    COMPANY_NAME "Bricklab Studios"
    BUNDLE_ID "io.github.michaeltietjen.bricklabstudiomidi"
    PLUGIN_MANUFACTURER_CODE Mtie
    PLUGIN_CODE BrkM
    FORMATS AU
    PRODUCT_NAME "Bricklab Studio MIDI"
    DESCRIPTION "Bricklab Studio's chords, sent to any instrument"
    IS_SYNTH FALSE
    NEEDS_MIDI_INPUT TRUE
    NEEDS_MIDI_OUTPUT TRUE
    IS_MIDI_EFFECT TRUE
    EDITOR_WANTS_KEYBOARD_FOCUS TRUE
    AU_MAIN_TYPE kAudioUnitType_MIDIProcessor
    COPY_PLUGIN_AFTER_BUILD TRUE)

# and for the VST3 hosts: the MIDI build as an instrument with a silent output, whose MIDI
# other tracks take (VST3 has no MIDI FX slot in most of them)
juce_add_plugin(BricklabStudioMIDIVST
    COMPANY_NAME "Bricklab Studios"
    BUNDLE_ID "io.github.michaeltietjen.bricklabstudiomidivst"
    PLUGIN_MANUFACTURER_CODE Mtie
    PLUGIN_CODE BrkV
    FORMATS VST3
    PRODUCT_NAME "Bricklab Studio MIDI"
    DESCRIPTION "Bricklab Studio's chords, leads and drones, sent to any instrument"
    IS_SYNTH TRUE
    NEEDS_MIDI_INPUT TRUE
    NEEDS_MIDI_OUTPUT TRUE
    IS_MIDI_EFFECT FALSE
    EDITOR_WANTS_KEYBOARD_FOCUS TRUE
    VST3_CATEGORIES Instrument Generator
    COPY_PLUGIN_AFTER_BUILD TRUE)

# The Cloud and the sympathetic strings (Source/fx), built on open-source engines (MIT: third_party/eurorack).
set(EURO ${CMAKE_CURRENT_SOURCE_DIR}/third_party/eurorack)
add_library(BrickFx STATIC
    ${EURO}/stmlib/utils/random.cc ${EURO}/stmlib/dsp/units.cc ${EURO}/stmlib/dsp/atan.cc
    ${EURO}/rings/resources.cc ${EURO}/rings/dsp/fm_voice.cc ${EURO}/rings/dsp/part.cc ${EURO}/rings/dsp/resonator.cc
    ${EURO}/rings/dsp/string.cc ${EURO}/rings/dsp/string_synth_part.cc
    ${EURO}/clouds/resources.cc ${EURO}/clouds/dsp/correlator.cc ${EURO}/clouds/dsp/granular_processor.cc ${EURO}/clouds/dsp/mu_law.cc
    ${EURO}/clouds/dsp/pvoc/frame_transformation.cc ${EURO}/clouds/dsp/pvoc/phase_vocoder.cc ${EURO}/clouds/dsp/pvoc/stft.cc
    Source/fx/Fx.cpp)
target_include_directories(BrickFx PRIVATE ${EURO})
target_compile_definitions(BrickFx PRIVATE TEST=1)
target_compile_options(BrickFx PRIVATE -w -O2)
set_target_properties(BrickFx PROPERTIES POSITION_INDEPENDENT_CODE ON)

foreach(t BricklabStudio BricklabStudioMIDI BricklabStudioMIDIVST)
    target_sources(${t} PRIVATE
        Source/PluginProcessor.cpp
        Source/PluginEditor.cpp
        Source/core/Render.cpp
        Source/core/Engine.cpp
        Source/core/Patterns.cpp
        Source/core/Glide.cpp)
    target_compile_definitions(${t} PUBLIC
        JUCE_WEB_BROWSER=0
        JUCE_USE_CURL=0
        JUCE_VST3_CAN_REPLACE_VST2=0)
    target_link_libraries(${t}
        PRIVATE juce::juce_audio_utils juce::juce_dsp BrickFx
        PUBLIC juce::juce_recommended_config_flags juce::juce_recommended_lto_flags juce::juce_recommended_warning_flags)
endforeach()
target_compile_definitions(BricklabStudioMIDI PRIVATE BRICK_MIDI_FX=1)
target_compile_definitions(BricklabStudioMIDIVST PRIVATE BRICK_MIDI_FX=1 BRICK_SILENT_BUS=1)

# The recorded strum instruments (plugin/sounds: CC0 recordings from VSCO 2 Community Edition and VCSL) go into
# the instrument's Resources/Sounds, in the build and in the copies the build installs.
foreach(fmt AU VST3 Standalone)
  add_custom_command(TARGET BricklabStudio_${fmt} POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E copy_directory "${CMAKE_CURRENT_SOURCE_DIR}/sounds" "$<TARGET_BUNDLE_DIR:BricklabStudio_${fmt}>/Contents/Resources/Sounds")
endforeach()
if(APPLE)
  add_custom_command(TARGET BricklabStudio_AU POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E copy_directory "${CMAKE_CURRENT_SOURCE_DIR}/sounds" "$ENV{HOME}/Library/Audio/Plug-Ins/Components/Bricklab Studio.component/Contents/Resources/Sounds")
  add_custom_command(TARGET BricklabStudio_VST3 POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E copy_directory "${CMAKE_CURRENT_SOURCE_DIR}/sounds" "$ENV{HOME}/Library/Audio/Plug-Ins/VST3/Bricklab Studio.vst3/Contents/Resources/Sounds")
endif()
