#include "PluginProcessor.h"
#include "PluginEditor.h"
#include "core/PatchData.h"

using namespace brick;

juce::StringArray BricklabStudioProcessor::soundNames() {
    juce::StringArray s;
    for (int i = 0; i < kNumPatches; ++i) s.add(kPatches[i].name);
    return s;
}

static juce::AudioProcessorValueTreeState::ParameterLayout layout() {
    using namespace juce;
    AudioProcessorValueTreeState::ParameterLayout l;
    l.add(std::make_unique<AudioParameterChoice>(ParameterID{"sound", 1}, "Sound", BricklabStudioProcessor::soundNames(), 0));
    l.add(std::make_unique<AudioParameterChoice>(ParameterID{"key", 1}, "Key",
        StringArray{"C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"}, 9));
    l.add(std::make_unique<AudioParameterChoice>(ParameterID{"scale", 1}, "Scale", StringArray{"Major", "Minor", "Dorian", "Mixolydian"}, 1));
    StringArray modes, basses;
    for (auto* m : kPlayModes) modes.add(m);
    for (auto* b : kBassModes) basses.add(b);
    l.add(std::make_unique<AudioParameterChoice>(ParameterID{"mode", 1}, "Play mode", modes, 0));
    l.add(std::make_unique<AudioParameterChoice>(ParameterID{"bassmode", 1}, "Bass", basses, 0));
    l.add(std::make_unique<AudioParameterInt>(ParameterID{"arpoct", 1}, "Arp octaves", 1, 4, 1));
    l.add(std::make_unique<AudioParameterFloat>(ParameterID{"basslevel", 1}, "Bass level", 0.f, 1.f, 0.4f));
    l.add(std::make_unique<AudioParameterBool>(ParameterID{"internal", 1}, "Built-in sound", true));
    l.add(std::make_unique<AudioParameterBool>(ParameterID{"midiout", 1}, "MIDI out", BricklabStudioProcessor::kMidiFx));
    l.add(std::make_unique<AudioParameterFloat>(ParameterID{"space", 1}, "Space", 0.f, 1.f, 0.3f));
    l.add(std::make_unique<AudioParameterFloat>(ParameterID{"volume", 1}, "Volume", 0.f, 1.f, 0.8f));
    return l;
}

BricklabStudioProcessor::BricklabStudioProcessor()
    : AudioProcessor(kMidiFx ? BusesProperties() : BusesProperties().withOutput("Output", juce::AudioChannelSet::stereo(), true)),
      params(*this, nullptr, "BricklabStudio", layout()) {
    applySoundAndKey();
    startTimerHz(20);
}

BricklabStudioProcessor::~BricklabStudioProcessor() { stopTimer(); }

bool BricklabStudioProcessor::isBusesLayoutSupported(const BusesLayout& l) const {
    return kMidiFx || l.getMainOutputChannelSet() == juce::AudioChannelSet::stereo();
}

void BricklabStudioProcessor::prepareToPlay(double sampleRate, int samplesPerBlock) {
    sr = sampleRate;
    player.prepare(sampleRate);
    reverb.prepare({sampleRate, (juce::uint32) samplesPerBlock, 2});
}

void BricklabStudioProcessor::timerCallback() { applySoundAndKey(); }

void BricklabStudioProcessor::applySoundAndKey() {
    int snd = (int) params.getRawParameterValue("sound")->load();
    int key = (int) params.getRawParameterValue("key")->load();
    int sc = (int) params.getRawParameterValue("scale")->load();
    player.setBassLevel(0.75f * params.getRawParameterValue("basslevel")->load());   // engine.py _bass: 0.75 x level
    if (snd == lastSound && key == lastKey && sc == lastScale) return;
    if (snd != lastSound) {
        cache.setSound(snd);
        player.setRelease(kPatches[snd].r);
    }
    player.setKey(key, (Scale) sc);
    lastSound = snd; lastKey = key; lastScale = sc;
    if (kMidiFx) return;                                  // nothing to render: it only sends notes
    auto w = player.wanted();
    wantedCount = (int) std::count_if(w.begin(), w.end(), [](int m) { return m < 1000; });
    cache.want(w);
}

void BricklabStudioProcessor::padDown(int degree, int pos) {
    auto c = player.playDegree(degree, mods);
    queueOut(true, pos);
    const juce::SpinLock::ScopedLockType l(nameLock);
    lastName = c.name;
    lastRoman = romanFor(degree, c.iv);
}

void BricklabStudioProcessor::padUp(int pos) { player.release(); queueOut(false, pos); }

void BricklabStudioProcessor::queueOut(bool on, int pos) {
    ChordEvent e{pos, on ? player.lastNotes() : std::vector<int>{}};
    if (on && e.notes.size() < 2) return;
    const juce::SpinLock::ScopedLockType l(outLock);
    outQueue.push_back(std::move(e));
}

juce::String BricklabStudioProcessor::chordName() const { const juce::SpinLock::ScopedLockType l(nameLock); return lastName; }
juce::String BricklabStudioProcessor::chordRoman() const { const juce::SpinLock::ScopedLockType l(nameLock); return lastRoman; }

std::vector<juce::String> BricklabStudioProcessor::padNames() const {
    std::vector<juce::String> out;
    for (int d = 0; d < 7; ++d) {
        auto c = buildChord(player.key(), player.scale(), d, Mods{});
        out.push_back(juce::String(c.name) + "\n" + romanFor(d, c.iv));
    }
    return out;
}

void BricklabStudioProcessor::playHeld(int pos) {
    std::vector<int> keys(held.begin(), held.end());
    if (keys.size() >= 2) {                                 // keys together: that exact chord (main.py midi_tick)
        auto c = player.playExact(keys);
        queueOut(true, pos);
        const juce::SpinLock::ScopedLockType l(nameLock);
        lastName = c.name; lastRoman = "MIDI";
    } else if (keys.size() == 1) {
        padDown(degreeOf(keys[0], player.key(), player.scale()), pos);
    } else
        padUp(pos);
}

void BricklabStudioProcessor::processBlock(juce::AudioBuffer<float>& buffer, juce::MidiBuffer& midi) {
    juce::ScopedNoDenormals noDenormals;
    const int n = buffer.getNumSamples();
    buffer.clear();

    // 1. the keys played in: which chords start (or stop) where in this block
    {
        int at = 0;
        auto advance = [&](int upto) {
            while (pending >= 0 && at + pending <= upto) {
                at += std::max(1, pending);
                pending = -1;
                playHeld(std::min(at, n - 1));
            }
            if (pending >= 0) pending -= upto - at;
            at = upto;
        };
        for (const auto meta : midi) {
            const auto m = meta.getMessage();
            advance(std::min(n, meta.samplePosition));
            if (m.isNoteOn()) held.insert(m.getNoteNumber());
            else if (m.isNoteOff()) held.erase(m.getNoteNumber());
            else if (m.isAllNotesOff() || m.isAllSoundOff()) held.clear();
            else continue;
            pending = (int) (0.035 * sr);                    // a chord's notes arrive one by one
        }
        advance(n);
    }
    midi.clear();                                            // what goes out is the chords they make

    // 2. play mode and bass mode turn those chords into notes, on the host's 16ths when it plays
    double bpm = 120, ppq = -1;
    bool playing = false;
    if (auto* ph = getPlayHead())
        if (auto pos = ph->getPosition()) {
            if (auto b = pos->getBpm()) bpm = *b;
            if (auto p = pos->getPpqPosition()) ppq = *p;
            playing = pos->getIsPlaying();
        }
    patterns.setTempo(bpm, sr);
    patterns.setMode((int) params.getRawParameterValue("mode")->load());
    patterns.setBassMode((int) params.getRawParameterValue("bassmode")->load());
    patterns.setArpOctaves((int) params.getRawParameterValue("arpoct")->load());
    std::vector<ChordEvent> chords;
    {
        const juce::SpinLock::ScopedLockType l(outLock);
        chords.swap(outQueue);
    }
    const double stepLen = 60.0 / bpm / 4 * sr;
    std::vector<std::pair<int64_t, int64_t>> steps;          // (sample time, 16th index)
    if (playing && ppq >= 0) {
        double q = ppq * 4, first = std::ceil(q - 1e-9);
        for (double s = first; (s - q) * stepLen < n; s += 1)
            steps.push_back({clock + (int64_t) ((s - q) * stepLen), (int64_t) s});
        nextStep = clock + (int64_t) ((first - q) * stepLen);
        while (nextStep < clock + n) nextStep += (int64_t) stepLen;
    } else {
        if (nextStep < clock || nextStep > clock + 4 * (int64_t) stepLen) nextStep = clock;
        for (; nextStep < clock + n; nextStep += std::max<int64_t>(1, (int64_t) stepLen)) steps.push_back({nextStep, stepIndex++});
    }
    size_t si = 0;
    for (auto& c : chords) {
        const int64_t t = clock + juce::jlimit(0, std::max(0, n - 1), c.pos);
        for (; si < steps.size() && steps[si].first < t; ++si) patterns.step(steps[si].second, steps[si].first);
        if (c.notes.empty()) patterns.clear(t); else patterns.chord(c.notes, t);
    }
    for (; si < steps.size(); ++si) patterns.step(steps[si].second, steps[si].first);
    events.clear();
    patterns.take(clock + n, events);

    // 3. the notes: into the built-in sound and out as MIDI
    const bool audio = buffer.getNumChannels() >= 2;
    const bool internal = audio && params.getRawParameterValue("internal")->load() > 0.5f;
    const bool out = params.getRawParameterValue("midiout")->load() > 0.5f;
    float* L = audio ? buffer.getWritePointer(0) : nullptr;
    float* R = audio ? buffer.getWritePointer(1) : nullptr;
    int at = 0;
    for (auto& e : events) {
        const int p = (int) juce::jlimit<int64_t>(0, n - 1, e.at - clock);
        if (audio && p > at) { player.render(L + at, R + at, p - at); at = p; }
        if (e.on) {
            if (internal) player.noteOn(e.ch, e.note, e.gain, e.pan);
            if (out) {
                midi.addEvent(juce::MidiMessage::noteOn(e.ch, e.note, (juce::uint8) juce::jlimit(1, 127, (int) std::lround(e.gain * 120))), p);
                sounding.insert({e.ch, e.note});
            }
        } else {
            player.noteOff(e.ch, e.note, e.rel);
            if (sounding.erase({e.ch, e.note})) midi.addEvent(juce::MidiMessage::noteOff(e.ch, e.note), p);
        }
    }
    if (audio && at < n) player.render(L + at, R + at, n - at);
    if (!out && !sounding.empty()) {                         // switched off with notes held: let them go
        for (auto [ch, note] : sounding) midi.addEvent(juce::MidiMessage::noteOff(ch, note), n - 1);
        sounding.clear();
    }
    clock += n;
    if (!audio) return;
    if (!internal) { buffer.clear(); return; }

    juce::dsp::Reverb::Parameters rp;
    const float space = params.getRawParameterValue("space")->load();
    rp.roomSize = 0.82f; rp.damping = 0.45f; rp.width = 1.0f;
    rp.wetLevel = 0.45f * space; rp.dryLevel = 1.0f;
    reverb.setParameters(rp);
    juce::dsp::AudioBlock<float> block(buffer);
    reverb.process(juce::dsp::ProcessContextReplacing<float>(block));
    const float vol = params.getRawParameterValue("volume")->load();
    for (int c = 0; c < 2; ++c) {
        auto* d = buffer.getWritePointer(c);
        for (int i = 0; i < n; ++i) d[i] = std::tanh(d[i] * vol * 1.2f) / 1.2f;     // never clips
    }
}

void BricklabStudioProcessor::getStateInformation(juce::MemoryBlock& destData) {
    if (auto xml = params.copyState().createXml()) copyXmlToBinary(*xml, destData);
}

void BricklabStudioProcessor::setStateInformation(const void* data, int sizeInBytes) {
    if (auto xml = getXmlFromBinary(data, sizeInBytes))
        if (xml->hasTagName(params.state.getType())) params.replaceState(juce::ValueTree::fromXml(*xml));
}

juce::AudioProcessorEditor* BricklabStudioProcessor::createEditor() { return new BricklabStudioEditor(*this); }

juce::AudioProcessor* JUCE_CALLTYPE createPluginFilter() { return new BricklabStudioProcessor(); }
