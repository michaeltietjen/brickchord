#pragma once
#include <juce_audio_processors/juce_audio_processors.h>
#include "PluginProcessor.h"

// One pad: press to play its chord, let go to release (like the handheld's buttons).
class Pad : public juce::Component {
public:
    std::function<void()> onDown, onUp;
    juce::String top, sub;
    bool lit = false;
    void paint(juce::Graphics&) override;
    void mouseDown(const juce::MouseEvent&) override { lit = true; repaint(); if (onDown) onDown(); }
    void mouseUp(const juce::MouseEvent&) override { lit = false; repaint(); if (onUp) onUp(); }
};

// drag what was played into the DAW as a MIDI clip
struct DragMidi : juce::Component {
    std::function<juce::File()> make;
    std::function<bool()> ready;
    bool dragging = false;
    void paint(juce::Graphics& g) override;
    void mouseDrag(const juce::MouseEvent&) override;
    void mouseUp(const juce::MouseEvent&) override { dragging = false; }
};

// the page, drawn at its own size and scaled to the window
struct Canvas : juce::Component {
    std::function<void(juce::Graphics&)> painter;
    void paint(juce::Graphics& g) override { if (painter) painter(g); }
};

class BricklabStudioEditor : public juce::AudioProcessorEditor, private juce::Timer {
public:
    explicit BricklabStudioEditor(BricklabStudioProcessor&);
    ~BricklabStudioEditor() override;
    void paint(juce::Graphics&) override;
    void resized() override;
    bool keyPressed(const juce::KeyPress&) override;
    bool keyStateChanged(bool isKeyDown) override;

private:
    void timerCallback() override;
    void showTab(int t);
    void layout();
    void paintContent(juce::Graphics&);
    void layoutRows();
    void padPress(int d, bool down);
    BricklabStudioProcessor& proc;
    Canvas canvas;                                 // declared first, so it outlives what sits on it
    int tab = 0;
    juce::OwnedArray<juce::TextButton> tabs;
    juce::OwnedArray<Pad> pads;
    juce::OwnedArray<juce::TextButton> modButtons;
    juce::OwnedArray<juce::AudioProcessorValueTreeState::ButtonAttachment> modAttach;
    juce::TextButton latch{"latch"};
    juce::ComboBox sound, key, scale, mode, arpOct, bassMode, leadSound, droneSound, octave, droneSlide;
    juce::Slider leadGlide, droneY, droneX, glideTone;
    juce::TextButton third{"3rd"}, bloomBtn{"bloom"}, stopBtn{"stop"}, glideSub{"sub"}, glideMore{"more"};
    juce::ComboBox glideSound, glideChord, glidePath, glideTiming, glideMove, glideTime, glideFade, glideBend, glideMpe;
    juce::Label glideChordL, glideToneL;
    juce::ComboBox presetBox;
    DragMidi dragMidi;
    std::array<std::array<float, 150>, 6> trail{};     // the Glide voices' last 10 seconds (cents; 0 = silent)
    std::array<float, 6> trailLvl{};
    int trailAt = 0;
    juce::Label octL, glideL, slideL, pulseL, bloomL;
    int litDrone = -2;
    juce::Slider space, volume, bassLvl;
    juce::Label spaceL, volumeL, soon, outNote, modeL, arpL, bassL;
    std::unique_ptr<juce::AudioProcessorValueTreeState::ComboBoxAttachment> aSound, aKey, aScale, aMode, aArpOct, aBassMode, aLeadSound, aDroneSound, aOctave, aDroneSlide,
        aGlideSound, aGlideChord, aGlidePath, aGlideTiming, aGlideMove, aGlideTime, aGlideFade, aGlideBend, aGlideMpe;
    std::unique_ptr<juce::AudioProcessorValueTreeState::ButtonAttachment> aLatch, aThird, aGlideSub;
    std::unique_ptr<juce::AudioProcessorValueTreeState::SliderAttachment> aSpace, aVolume, aBassLvl, aLeadGlide, aDroneY, aDroneX, aGlideTone;
    int keyDown = -1;
    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR(BricklabStudioEditor)
};
