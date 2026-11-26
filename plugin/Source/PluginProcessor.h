// Bricklab Studio: the plugin. Chord is the first of the four modes to play;
// Lab, Glide and Chop follow (see the tabs in PluginEditor).
#pragma once
#include <juce_audio_processors/juce_audio_processors.h>
#include <juce_dsp/juce_dsp.h>
#include <cstdio>
#include <set>
#include "core/Engine.h"
#include "core/Patterns.h"
#include "core/Glide.h"
#include "core/Hall.h"

class BricklabStudioProcessor : public juce::AudioProcessor, private juce::Timer {
public:
    BricklabStudioProcessor();
    ~BricklabStudioProcessor() override;

    void prepareToPlay(double sampleRate, int samplesPerBlock) override;
    void releaseResources() override {}
    bool isBusesLayoutSupported(const BusesLayout& layouts) const override;
    void processBlock(juce::AudioBuffer<float>&, juce::MidiBuffer&) override;
    void processBlockBypassed(juce::AudioBuffer<float>&, juce::MidiBuffer&) override;   // bypassed: everything lets go

    juce::AudioProcessorEditor* createEditor() override;
    bool hasEditor() const override { return true; }
    const juce::String getName() const override { return "Bricklab Studio"; }
    bool acceptsMidi() const override { return true; }
    bool producesMidi() const override { return kMidiFx; }   // the MIDI FX: plays the instrument after it
    bool isMidiEffect() const override { return kMidiFx && !kSilentBus; }
#if BRICK_MIDI_FX
    static constexpr bool kMidiFx = true;      // the MIDI builds: no sound of their own, only the notes
#else
    static constexpr bool kMidiFx = false;
#endif
#if BRICK_SILENT_BUS
    static constexpr bool kSilentBus = true;   // the VST3 MIDI build: an instrument to the host (a silent output), so
#else                                          // Ableton, Bitwig, Reaper and FL can route its MIDI to other tracks
    static constexpr bool kSilentBus = false;
#endif
    double getTailLengthSeconds() const override { return 3.0; }
    int getNumPrograms() override;                 // the factory presets
    int getCurrentProgram() override { return currentProgram; }
    void setCurrentProgram(int) override;
    const juce::String getProgramName(int) override;
    void changeProgramName(int, const juce::String&) override {}
    void getStateInformation(juce::MemoryBlock& destData) override;
    void setStateInformation(const void* data, int sizeInBytes) override;

    // which page this instance plays: each instance is one layer, as many as you like in the DAW
    enum Page { ChordPage, LeadPage, DronePage, GlidePage };
    int page() const { return (int) params.getRawParameterValue("page")->load(); }
    void uiPad(int degree, bool down);        // the Lead and Drone pages' pads
    int droneDegree() const { return droneDegLit.load(); }
    static std::vector<int> soundsOf(int group);   // patch indexes of a group: 0 chord, 1 lead, 2 drone

    // the Chord page and MIDI both play through these
    void padDown(int degree, int pos = 0);
    void padUp(int pos = 0);
    brick::Mods heldMods() const;             // 7th, sus4, 9th, flip: the page's buttons, as parameters
    juce::String chordName() const;
    juce::String chordRoman() const;
    std::vector<juce::String> padNames() const;
    int soundsReady() const { return cache.ready(); }
    int soundsWanted() const { return wantedCount.load(); }

    juce::AudioProcessorValueTreeState params;
    // what this instance played, kept so it can be dragged into the DAW as a MIDI clip
    juce::File writePhrase();                 // the last 8 bars as a .mid file (or an empty File if nothing was played)
    bool hasPhrase() const { return captured.load() > 0; }
    static juce::StringArray soundNames();

private:
    void timerCallback() override;            // follows sound, key and scale changes (message thread)
    void applySoundAndKey();
    void playHeld(int pos);                   // MIDI: what the held keys ask for
    void runChord(juce::AudioBuffer<float>&, juce::MidiBuffer&, int n, bool audio, bool internal, bool out);
    void runMono(juce::AudioBuffer<float>&, juce::MidiBuffer&, int n, bool audio, bool internal, bool out, int pg);
    void runGlide(juce::AudioBuffer<float>&, juce::MidiBuffer&, int n, bool audio, bool out);
    void glideOut(juce::MidiBuffer&, int pos, bool allOff);   // MIDI out for Glide: MPE, or plain notes
    void leadPlay(int m, int pos, juce::MidiBuffer&, bool internal, bool out);
    void leadPress(int id, int m, int pos, juce::MidiBuffer&, bool internal, bool out);
    void leadRelease(int id, int pos, juce::MidiBuffer&, bool internal, bool out);
    void droneToggle(int pc, int deg, int pos, juce::MidiBuffer&, bool internal, bool out);
    void sendOff(juce::MidiBuffer&, int pos);  // every MIDI note this instance has on: off
    void setName(const juce::String& name, const juce::String& sub);

    struct Cap { int64_t t; bool on; int note, vel; };
    juce::SpinLock capLock;
    std::vector<Cap> cap;                     // note ons and offs, in samples of the clock
    std::set<int> capOpen;                    // notes captured on and not yet off
    std::vector<int> capGlide, capDrone;      // the Glide chord and the drone as captured
    std::vector<int> droneNotesNow;
    std::atomic<int> captured{0};
    double lastBpm = 120;
    int currentProgram = 0;
    void capture(bool on, int note, int vel, int pos);
    void captureSet(std::vector<int>& was, std::vector<int> now, int vel, int pos);

    juce::SpinLock uiLock;
    std::vector<std::pair<int, bool>> uiQueue;        // (degree, down) from the Lead and Drone pads
    std::vector<std::pair<int, int>> leadStack;       // (key or 100 + pad, note): the lead plays the newest
    int leadOut = -1;                                 // the lead note MIDI out has on
    std::vector<int> droneOut;                        // the drone notes MIDI out has on
    int dronePc = -1, lastPage = -1;
    std::atomic<int> droneDegLit{-1};
    float bendSemis = 0, vibDepth = 0;
public:
    brick::GlideEngine glide{cache};
    static std::vector<int> glideSounds();    // the Glide page's sounds: the drones, then the chord sounds
private:
    std::array<int, brick::kGlideVoices> mpeNote{}, mpeBend{}, mpePress{}, mpeTimbre{};
    int mpeExpr = -1, lastOutMode = 0, mpeSerial = 0;
    std::FILE* dbg = nullptr;                 // the diagnostic log (see prepareToPlay)
    int64_t dbgBeat = 0;
    int dbgOther = 0;
    int64_t mpeRefreshAt = 0;
    bool hostPlaying = false;
    juce::String instanceId = juce::Uuid().toString();
    std::vector<int> glideNotesOut;           // the Notes mode's chord on MIDI out
    bool mpeReady = false, wasPlaying = false;
    float glideSwell = 0;
    int lastExpr = 127;                               // the expression MIDI out last sent (the drone's pulse)
    void queueOut(bool on, int pos);          // a chord just started (or was let go): for Patterns

    struct ChordEvent { int pos; std::vector<int> notes; float vel = 0.85f; };   // notes empty = let go
    float keyVel = 0.85f;                     // the last key's velocity (0..1); the pads play at 0.85
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
    brick::Hall hall;                         // the reverb (Space)
    std::set<int> held;                       // MIDI keys down
    int pending = -1;                         // samples until held keys are read (a chord's notes arrive one by one)
    int lastSound = -1, lastKey = -1, lastScale = -1, lastOct = 0;
    std::atomic<int> wantedCount{0};
    std::atomic<bool> rateChanged{false};
    mutable juce::SpinLock nameLock;
    juce::String lastName, lastRoman;
    double sr = 44100;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR(BricklabStudioProcessor)
};
