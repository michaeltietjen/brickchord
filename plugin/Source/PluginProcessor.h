// Bricklab Studio: the plugin. Chord is the first of the four modes to play;
// Lab, Glide and Chop follow (see the tabs in PluginEditor).
#pragma once
#include <juce_audio_processors/juce_audio_processors.h>
#include <juce_dsp/juce_dsp.h>
#include <set>
#include "core/Engine.h"

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
    void queueOut(bool on, int pos);          // MIDI out: the chord just started (or let go)

    struct OutEvent { int pos; std::vector<std::pair<int, int>> on; };   // (channel, note); empty = let go
    juce::SpinLock outLock;
    std::vector<OutEvent> outQueue;           // filled by the page and by playHeld, sent from processBlock
    std::vector<std::pair<int, int>> sounding; // notes we sent on and have not sent off yet (audio thread)

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
