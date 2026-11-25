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
    l.add(std::make_unique<AudioParameterBool>(ParameterID{"bass", 1}, "Synth bass", true));
    l.add(std::make_unique<AudioParameterFloat>(ParameterID{"basslevel", 1}, "Bass level", 0.f, 1.f, 0.4f));
    l.add(std::make_unique<AudioParameterFloat>(ParameterID{"space", 1}, "Space", 0.f, 1.f, 0.3f));
    l.add(std::make_unique<AudioParameterFloat>(ParameterID{"volume", 1}, "Volume", 0.f, 1.f, 0.8f));
    return l;
}

BricklabStudioProcessor::BricklabStudioProcessor()
    : AudioProcessor(BusesProperties().withOutput("Output", juce::AudioChannelSet::stereo(), true)),
      params(*this, nullptr, "BricklabStudio", layout()) {
    applySoundAndKey();
    startTimerHz(20);
}

BricklabStudioProcessor::~BricklabStudioProcessor() { stopTimer(); }

bool BricklabStudioProcessor::isBusesLayoutSupported(const BusesLayout& l) const {
    return l.getMainOutputChannelSet() == juce::AudioChannelSet::stereo();
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
    player.setBass(params.getRawParameterValue("bass")->load() > 0.5f);
    player.setBassLevel(0.75f * params.getRawParameterValue("basslevel")->load());   // engine.py _bass: 0.75 x level
    if (snd == lastSound && key == lastKey && sc == lastScale) return;
    if (snd != lastSound) {
        cache.setSound(snd);
        player.setRelease(kPatches[snd].r);
    }
    player.setKey(key, (Scale) sc);
    lastSound = snd; lastKey = key; lastScale = sc;
    auto w = player.wanted();
    wantedCount = (int) std::count_if(w.begin(), w.end(), [](int m) { return m < 1000; });
    cache.want(w);
}

void BricklabStudioProcessor::padDown(int degree) {
    auto c = player.playDegree(degree, mods);
    const juce::SpinLock::ScopedLockType l(nameLock);
    lastName = c.name;
    lastRoman = romanFor(degree, c.iv);
}

void BricklabStudioProcessor::padUp() { player.release(); }

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

void BricklabStudioProcessor::playHeld() {
    std::vector<int> keys(held.begin(), held.end());
    if (keys.size() >= 2) {                                 // keys together: that exact chord (main.py midi_tick)
        auto c = player.playExact(keys);
        const juce::SpinLock::ScopedLockType l(nameLock);
        lastName = c.name; lastRoman = "MIDI";
    } else if (keys.size() == 1) {
        padDown(degreeOf(keys[0], player.key(), player.scale()));
    } else
        player.release();
}

void BricklabStudioProcessor::processBlock(juce::AudioBuffer<float>& buffer, juce::MidiBuffer& midi) {
    juce::ScopedNoDenormals noDenormals;
    const int n = buffer.getNumSamples();
    buffer.clear();
    int at = 0;
    float* L = buffer.getWritePointer(0);
    float* R = buffer.getWritePointer(1);
    auto renderTo = [&](int upto) {
        while (at < upto) {
            int step = upto - at;
            if (pending >= 0) step = std::min(step, std::max(1, pending));
            player.render(L + at, R + at, step);
            at += step;
            if (pending >= 0) {
                pending -= step;
                if (pending <= 0) { pending = -1; playHeld(); }
            }
        }
    };
    for (const auto meta : midi) {
        const auto m = meta.getMessage();
        renderTo(std::min(n, meta.samplePosition));
        if (m.isNoteOn()) held.insert(m.getNoteNumber());
        else if (m.isNoteOff()) held.erase(m.getNoteNumber());
        else if (m.isAllNotesOff() || m.isAllSoundOff()) held.clear();
        else continue;
        pending = (int) (0.035 * sr);
    }
    renderTo(n);

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
