// Bricklab Studio: the plugin. Chord is the first of the four modes to play;
// Lab, Glide and Chop follow (see the tabs in PluginEditor).
#pragma once
#include <juce_audio_processors/juce_audio_processors.h>
#include <juce_dsp/juce_dsp.h>
#include <set>
#include "core/Engine.h"
#include "core/Patterns.h"

class BricklabStudioProcessor : public juce::AudioProcessor, private juce::Timer {
public:
    BricklabStudioProcessor();
    ~BricklabStudioProcessor() override;

    void prepareToPlay(double sampleRate, int samplesPerBlock) override;
    void releaseResources() override {}
    bool isBusesLayoutSupported(const BusesLayout& layouts) const override;
    void processBlock(juce::AudioBuffer<float>&, juce::MidiBuffer&) override;

    juce::AudioProcessorEditor* createEditor() override;
    bool hasEditor() const override { return true; }
    const juce::String getName() const override { return "Bricklab Studio"; }
    bool acceptsMidi() const override { return true; }
    bool producesMidi() const override { return true; }      // MIDI out: play other instruments with these chords
    bool isMidiEffect() const override { return kMidiFx; }
#if BRICK_MIDI_FX
    static constexpr bool kMidiFx = true;      // the Logic MIDI FX build: no sound of its own, only MIDI out
#else
    static constexpr bool kMidiFx = false;
#endif
    double getTailLengthSeconds() const override { return 3.0; }
    int getNumPrograms() override { return 1; }
    int getCurrentProgram() override { return 0; }
    void setCurrentProgram(int) override {}
    const juce::String getProgramName(int) override { return {}; }
    void changeProgramName(int, const juce::String&) override {}
    void getStateInformation(juce::MemoryBlock& destData) override;
    void setStateInformation(const void* data, int sizeInBytes) override;

    // the Chord page and MIDI both play through these
    void padDown(int degree, int pos = 0);
    void padUp(int pos = 0);
    brick::Mods mods;                         // 7th, sus4, 9th, flip: set by the page's buttons
    juce::String chordName() const;
    juce::String chordRoman() const;
    std::vector<juce::String> padNames() const;
    int soundsReady() const { return cache.ready(); }
    int soundsWanted() const { return wantedCount.load(); }

    juce::AudioProcessorValueTreeState params;
    static juce::StringArray soundNames();

private:
    void timerCallback() override;            // follows sound, key and scale changes (message thread)
    void applySoundAndKey();
    void playHeld(int pos);                   // MIDI: what the held keys ask for
    void queueOut(bool on, int pos);          // a chord just started (or was let go): for Patterns

    struct ChordEvent { int pos; std::vector<int> notes; };   // notes empty = let go
    juce::SpinLock outLock;
    std::vector<ChordEvent> outQueue;         // filled by the page and by playHeld, read in processBlock
    brick::Patterns patterns;                 // play mode and bass mode: chords into note events
    std::vector<brick::NoteEvent> events;
    std::set<std::pair<int, int>> sounding;   // MIDI notes sent on and not off yet
    int64_t clock = 0, nextStep = 0, stepIndex = 0;
    bool wasLatched = false;
public:
    std::atomic<int> padsDown{0};             // pads held on the page (latch needs to know)
private:   // the free-running 16th clock (when the host isn't playing)

    brick::NoteCache cache;
    brick::Player player{cache};
    juce::dsp::Reverb reverb;
    std::set<int> held;                       // MIDI keys down
    int pending = -1;                         // samples until held keys are read (a chord's notes arrive one by one)
    int lastSound = -1, lastKey = -1, lastScale = -1;
    std::atomic<int> wantedCount{0};
    mutable juce::SpinLock nameLock;
    juce::String lastName, lastRoman;
    double sr = 44100;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR(BricklabStudioProcessor)
};
