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
    COMPANY_NAME "Michael Tietjen"
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

target_sources(BricklabStudio PRIVATE
    Source/PluginProcessor.cpp
    Source/PluginEditor.cpp
    Source/core/Render.cpp
    Source/core/Engine.cpp)

target_compile_definitions(BricklabStudio PUBLIC
    JUCE_WEB_BROWSER=0
    JUCE_USE_CURL=0
    JUCE_VST3_CAN_REPLACE_VST2=0)

target_link_libraries(BricklabStudio
    PRIVATE juce::juce_audio_utils juce::juce_dsp
    PUBLIC juce::juce_recommended_config_flags juce::juce_recommended_lto_flags juce::juce_recommended_warning_flags)
