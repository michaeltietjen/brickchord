# A tiny VST3 host for testing the built plugins:
#   cmake -B build -G Xcode -DJUCE_DIR=../../../JUCE && cmake --build build --config Release
cmake_minimum_required(VERSION 3.22)
set(CMAKE_OSX_DEPLOYMENT_TARGET "12.0" CACHE STRING "")
project(vst3host VERSION 0.1.0)
set(CMAKE_CXX_STANDARD 17)
add_subdirectory(${JUCE_DIR} JUCE)
juce_add_console_app(vst3host PRODUCT_NAME "vst3host")
target_sources(vst3host PRIVATE main.cpp)
target_compile_definitions(vst3host PRIVATE JUCE_PLUGINHOST_VST3=1 JUCE_MODAL_LOOPS_PERMITTED=1 JUCE_WEB_BROWSER=0 JUCE_USE_CURL=0)
target_link_libraries(vst3host PRIVATE juce::juce_audio_processors juce::juce_gui_basics
    PUBLIC juce::juce_recommended_config_flags juce::juce_recommended_warning_flags)
