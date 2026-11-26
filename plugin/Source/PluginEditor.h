#pragma once
#include <juce_audio_processors/juce_audio_processors.h>
#include "PluginProcessor.h"
#include "CurveEditor.h"

// One pad: press to play its chord, let go to release (like the handheld's buttons).
class Pad : public juce::Component {
public:
    std::function<void()> onDown, onUp;
    juce::String top, sub;
    bool lit = false;
    juce::Colour tint;                                 // its chord's colour on the field (clear = the accent)
    void paint(juce::Graphics&) override;
    void mouseDown(const juce::MouseEvent&) override { lit = true; repaint(); if (onDown) onDown(); }
    void mouseUp(const juce::MouseEvent&) override { lit = false; repaint(); if (onUp) onUp(); }
    // a pad is a button to VoiceOver and Switch Control too: pressing it plays a short tap
    std::unique_ptr<juce::AccessibilityHandler> createAccessibilityHandler() override {
        setTitle(top);
        return std::make_unique<juce::AccessibilityHandler>(*this, juce::AccessibilityRole::button,
            juce::AccessibilityActions().addAction(juce::AccessibilityActionType::press, [this] {
                lit = true; repaint(); if (onDown) onDown();
                juce::Component::SafePointer<Pad> me(this);
                juce::Timer::callAfterDelay(450, [me] { if (me != nullptr) { me->lit = false; me->repaint(); if (me->onUp) me->onUp(); } });
            }));
    }
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

// the look: dark glass, one accent
struct BrickLook : juce::LookAndFeel_V4 {
    BrickLook();
    void drawButtonBackground(juce::Graphics&, juce::Button&, const juce::Colour&, bool, bool) override;
    juce::Font getTextButtonFont(juce::TextButton&, int) override;
    juce::Font getComboBoxFont(juce::ComboBox&) override;
    juce::Font getPopupMenuFont() override;
    void drawComboBox(juce::Graphics&, int, int, bool, int, int, int, int, juce::ComboBox&) override;
    void drawLinearSlider(juce::Graphics&, int, int, int, int, float, float, float, juce::Slider::SliderStyle, juce::Slider&) override;
    void drawRotarySlider(juce::Graphics&, int, int, int, int, float, float, float, juce::Slider&) override;
};

// the page, drawn at its own size and scaled to the window
struct Canvas : juce::Component {
    std::function<void(juce::Graphics&)> painter;
    void paint(juce::Graphics& g) override { if (painter) painter(g); }
    std::function<void(juce::Point<float>, bool down)> pointer;   // the field under the controls, pressed or dragged
    void mouseDown(const juce::MouseEvent& e) override { if (pointer) pointer(e.position, true); }
    void mouseDrag(const juce::MouseEvent& e) override { if (pointer) pointer(e.position, true); }
    void mouseUp(const juce::MouseEvent& e) override { if (pointer) pointer(e.position, false); }
};

class BricklabStudioEditor : public juce::AudioProcessorEditor, private juce::Timer {
public:
    explicit BricklabStudioEditor(BricklabStudioProcessor&);
    ~BricklabStudioEditor() override;
    void paint(juce::Graphics&) override;
    void resized() override;
    bool keyPressed(const juce::KeyPress&) override;
    bool keyStateChanged(bool isKeyDown) override;
    void focusLost(FocusChangeType) override { releaseKey(); }
    void releaseKey();

private:
    void timerCallback() override;
    void showTab(int t);
    void layout();
    void paintContent(juce::Graphics&);
    void layoutRows();
    void padPress(int d, bool down);
    BricklabStudioProcessor& proc;
    BrickLook look;
    Canvas canvas;                                 // declared first, so it outlives what sits on it
    int tab = 0;
    juce::OwnedArray<juce::TextButton> tabs;
    juce::OwnedArray<Pad> pads;
    juce::OwnedArray<juce::TextButton> modButtons;
    juce::OwnedArray<juce::AudioProcessorValueTreeState::ButtonAttachment> modAttach;
    juce::TextButton latch{"latch"};
    juce::ComboBox sound, key, scale, mode, arpOct, bassMode, leadSound, droneSound, octave, droneSlide;
    juce::Slider leadGlide, droneY, droneX, glideTone, droneDrift, droneAir, pluckLevel, pluckEcho, pluckRing, droneCloud;
    juce::ComboBox glideSubBox, droneChord, pluckSound, pluckArp, pluckRate, cloudStyle, chordColour;
    std::unique_ptr<juce::AudioProcessorValueTreeState::ComboBoxAttachment> aDroneChord, aPluckSound, aPluckArp, aPluckRate, aCloudStyle, aChordColour;
    std::unique_ptr<juce::AudioProcessorValueTreeState::SliderAttachment> aDroneDrift, aDroneAir, aPluckLevel, aPluckEcho, aPluckRing, aDroneCloud;
    struct Spark { int midi; float age; };
    std::vector<Spark> sparks;                         // plucked notes, travelling away down their strings
    std::array<float, 128> stringGlow{};
    int pluckSeen = 0, hoverString = -1;
    // the Terrain view: the sound's spectrum, a ridge for each moment, rolling away as it ages
    static constexpr int kBands = 76, kRows = 56;
    juce::dsp::FFT fft{12};
    std::array<float, 8192> fftBuf{};
    std::array<std::array<float, kBands>, kRows> terrain{};
    std::array<float, kBands> bandNow{};
    static constexpr int kSpec = 172;                  // the Spectrum view: half a semitone to a band
    std::array<std::array<float, kSpec>, kRows> spec{};
    std::array<float, kSpec> specNow{};
    std::array<juce::Colour, kRows> terrainCol{};      // the chord's colour when each ridge was made
    juce::Colour colNow{0xffb9a6ff};
    int terrainAt = 0, terrainCount = 0;
    bool terrainPhase = false;
    juce::TextButton viewBtn{"field"};
    // the Field's depth: a camera that drifts, a bloom at each change of chord, dust in the air
    int shotTick = 0;
    float camX = 0, camY = 0, bloom = 0;
    juce::String bloomName;
    struct Dust { float x, z, h, ph; };
    std::vector<Dust> dust;
    juce::TextButton third{"3rd"}, bloomBtn{"bloom"}, stopBtn{"stop"}, glideSub{"sub"}, glideMore{"more"}, glideStrike{"strike each chord"};
    juce::ComboBox glideSound, glideChord, glidePath, glideTiming, glideMove, glideCross, glideReach, glideTime, glideFade, glideBend, glideMpe;
    juce::Label glideChordL, glideToneL;
    juce::ComboBox presetBox, prSrc, tbSrc;
    juce::TextButton curvesBtn{"curves"};
    juce::Slider prDepth, tbDepth, lfoRate;
    juce::Label prL, tbL, lfoL;
    std::unique_ptr<CurveEditor> curveEd;
    std::unique_ptr<juce::AudioProcessorValueTreeState::ComboBoxAttachment> aPrSrc, aTbSrc;
    std::unique_ptr<juce::AudioProcessorValueTreeState::SliderAttachment> aPrDepth, aTbDepth, aLfoRate;
    DragMidi dragMidi;
    static constexpr int kHist = 240;                  // 8 seconds at 30 a second
    std::array<std::array<float, kHist>, 6> trail{};   // the Glide voices' paths (cents; 0 = silent)
    std::array<std::array<float, kHist>, 6> trailLv{}; // and their levels
    std::array<std::array<uint64_t, 2>, kHist> noteHist{};   // Chord and Drone: which notes sounded
    std::array<int8_t, kHist> chordHist{};             // and which chord (by pad) they belonged to
    std::array<float, 6> trailLvl{};
    int trailAt = 0;
    float fieldLo = 3300, fieldHi = 7200;
    static constexpr float fieldHor = 118, fieldK = 60, kLift = 2.6f;   // kLift: how far a ribbon rides above the floor   // the floor's horizon and depth scale
    juce::Label octL, glideL, slideL, pulseL, bloomL;
    int litDrone = -2;
    juce::Slider space, volume, bassLvl;
    juce::Label spaceL, volumeL, soon, outNote, modeL, arpL, bassL;
    std::unique_ptr<juce::AudioProcessorValueTreeState::ComboBoxAttachment> aSound, aKey, aScale, aMode, aArpOct, aBassMode, aLeadSound, aDroneSound, aOctave, aDroneSlide,
        aGlideSound, aGlideChord, aGlidePath, aGlideTiming, aGlideMove, aGlideCross, aGlideReach, aGlideTime, aGlideFade, aGlideBend, aGlideMpe;
    std::unique_ptr<juce::AudioProcessorValueTreeState::ButtonAttachment> aLatch, aThird, aGlideSub, aGlideStrike;
    std::unique_ptr<juce::AudioProcessorValueTreeState::SliderAttachment> aSpace, aVolume, aBassLvl, aLeadGlide, aDroneY, aDroneX, aGlideTone;
    int keyDown = -1;
    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR(BricklabStudioEditor)
};
