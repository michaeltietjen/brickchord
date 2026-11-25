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
    void layoutRows();
    void padPress(int d, bool down);
    BricklabStudioProcessor& proc;
    int tab = 0;
    juce::OwnedArray<juce::TextButton> tabs;
    juce::OwnedArray<Pad> pads;
    juce::OwnedArray<juce::TextButton> modButtons;
    juce::TextButton latch{"latch"};
    juce::ComboBox sound, key, scale, mode, arpOct, bassMode, leadSound, droneSound, octave, droneSlide;
    juce::Slider leadGlide, droneY, droneX;
    juce::TextButton third{"3rd"};
    juce::Label octL, glideL, slideL, pulseL, bloomL;
    int litDrone = -2;
    juce::Slider space, volume, bassLvl;
    juce::Label spaceL, volumeL, soon, outNote, modeL, arpL, bassL;
    std::unique_ptr<juce::AudioProcessorValueTreeState::ComboBoxAttachment> aSound, aKey, aScale, aMode, aArpOct, aBassMode, aLeadSound, aDroneSound, aOctave, aDroneSlide;
    std::unique_ptr<juce::AudioProcessorValueTreeState::ButtonAttachment> aLatch, aThird;
    std::unique_ptr<juce::AudioProcessorValueTreeState::SliderAttachment> aSpace, aVolume, aBassLvl, aLeadGlide, aDroneY, aDroneX;
    int keyDown = -1;
    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR(BricklabStudioEditor)
};
