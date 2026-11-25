#include "PluginProcessor.h"
#include "PluginEditor.h"
#include "core/PatchData.h"

using namespace brick;

juce::StringArray BricklabStudioProcessor::soundNames() {
    juce::StringArray s;
    for (int i = 0; i < kNumPatches; ++i) s.add(kPatches[i].name);
    return s;
}

std::vector<int> BricklabStudioProcessor::soundsOf(int group) {
    std::vector<int> v;
    for (int i = 0; i < kNumPatches; ++i) if (kPatches[i].group == group) v.push_back(i);
    return v;
}

std::vector<int> BricklabStudioProcessor::glideSounds() {     // ambient.amb_bank: drones and pads first
    auto v = soundsOf(2);
    for (int i : soundsOf(0)) v.push_back(i);
    return v;
}

static juce::StringArray namesOf(int group) {
    juce::StringArray s;
    for (int i : BricklabStudioProcessor::soundsOf(group)) s.add(kPatches[i].name);
    return s;
}

static juce::AudioProcessorValueTreeState::ParameterLayout layout() {
    using namespace juce;
    AudioProcessorValueTreeState::ParameterLayout l;
    l.add(std::make_unique<AudioParameterChoice>(ParameterID{"page", 1}, "Page", StringArray{"Chord", "Lead", "Drone", "Glide"}, 0));
    l.add(std::make_unique<AudioParameterChoice>(ParameterID{"sound", 1}, "Sound", BricklabStudioProcessor::soundNames(), 0));
    l.add(std::make_unique<AudioParameterChoice>(ParameterID{"leadsound", 1}, "Lead sound", namesOf(1), 0));
    l.add(std::make_unique<AudioParameterChoice>(ParameterID{"dronesound", 1}, "Drone sound", namesOf(2), 0));
    l.add(std::make_unique<AudioParameterInt>(ParameterID{"octave", 1}, "Octave", -2, 2, 0));
    l.add(std::make_unique<AudioParameterFloat>(ParameterID{"leadglide", 1}, "Lead glide", 0.f, 1.f, 0.25f));
    l.add(std::make_unique<AudioParameterChoice>(ParameterID{"droneslide", 1}, "Drone slide", StringArray{"Off (restrike)", "0.5 s", "1 s", "2 s", "4 s"}, 2));
    l.add(std::make_unique<AudioParameterBool>(ParameterID{"dronethird", 1}, "Drone 3rd", false));
    l.add(std::make_unique<AudioParameterFloat>(ParameterID{"droney", 1}, "Pulse / Swell", -1.f, 1.f, 0.f));
    l.add(std::make_unique<AudioParameterFloat>(ParameterID{"dronex", 1}, "Thin / Bloom", -1.f, 1.f, 0.f));
    {                                                        // the Glide page
        StringArray gs, ch, pa, ti, mo, tm, fa, be;
        for (int i : BricklabStudioProcessor::glideSounds()) gs.add(kPatches[i].name);
        for (auto* c : kGlideChords) ch.add(c);
        for (auto* c : kGlidePaths) pa.add(c);
        for (auto* c : kGlideTimings) ti.add(c);
        for (auto* c : kGlideMoves) mo.add(c);
        for (float t : kGlideTimes) tm.add("Glide " + String(t) + " s");
        for (float t : kGlideFades) fa.add("Fade " + String(t) + " s");
        for (int b : kGlideBends) be.add("Bend " + String(b) + " st");
        l.add(std::make_unique<AudioParameterChoice>(ParameterID{"glidesound", 1}, "Glide sound", gs, 0));
        l.add(std::make_unique<AudioParameterChoice>(ParameterID{"glidechord", 1}, "Glide chord", ch, 0));
        l.add(std::make_unique<AudioParameterChoice>(ParameterID{"glidepath", 1}, "Glide path", pa, 2));
        l.add(std::make_unique<AudioParameterChoice>(ParameterID{"glidetiming", 1}, "Glide timing", ti, 0));
        l.add(std::make_unique<AudioParameterChoice>(ParameterID{"glidemove", 1}, "Glide move", mo, 0));
        l.add(std::make_unique<AudioParameterChoice>(ParameterID{"glidetime", 1}, "Glide time", tm, 4));
        l.add(std::make_unique<AudioParameterChoice>(ParameterID{"glidefade", 1}, "Glide fade", fa, 2));
        l.add(std::make_unique<AudioParameterChoice>(ParameterID{"glidebend", 1}, "Glide bend range", be, 4));
        l.add(std::make_unique<AudioParameterBool>(ParameterID{"glidesub", 1}, "Glide sub", true));
        l.add(std::make_unique<AudioParameterChoice>(ParameterID{"glidempe", 1}, "Glide MIDI out", StringArray{"MPE", "Notes"}, 0));
    }
    l.add(std::make_unique<AudioParameterChoice>(ParameterID{"key", 1}, "Key",
        StringArray{"C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"}, 9));
    l.add(std::make_unique<AudioParameterChoice>(ParameterID{"scale", 1}, "Scale", StringArray{"Major", "Minor", "Dorian", "Mixolydian"}, 1));
    StringArray modes, basses;
    for (auto* m : kPlayModes) modes.add(m);
    for (auto* b : kBassModes) basses.add(b);
    l.add(std::make_unique<AudioParameterChoice>(ParameterID{"mode", 1}, "Play mode", modes, 0));
    l.add(std::make_unique<AudioParameterChoice>(ParameterID{"bassmode", 1}, "Bass", basses, 0));
    l.add(std::make_unique<AudioParameterInt>(ParameterID{"arpoct", 1}, "Arp octaves", 1, 4, 1));
    l.add(std::make_unique<AudioParameterBool>(ParameterID{"latch", 1}, "Latch", false));
    l.add(std::make_unique<AudioParameterFloat>(ParameterID{"basslevel", 1}, "Bass level", 0.f, 1.f, 0.4f));
    l.add(std::make_unique<AudioParameterFloat>(ParameterID{"space", 1}, "Space", 0.f, 1.f, 0.3f));
    l.add(std::make_unique<AudioParameterFloat>(ParameterID{"volume", 1}, "Volume", 0.f, 1.f, 0.8f));
    return l;
}

BricklabStudioProcessor::BricklabStudioProcessor()
    : AudioProcessor(kMidiFx && !kSilentBus ? BusesProperties() : BusesProperties().withOutput("Output", juce::AudioChannelSet::stereo(), true)),
      params(*this, nullptr, "BricklabStudio", layout()) {
    applySoundAndKey();
    startTimerHz(20);
}

BricklabStudioProcessor::~BricklabStudioProcessor() { stopTimer(); }

bool BricklabStudioProcessor::isBusesLayoutSupported(const BusesLayout& l) const {
    return (kMidiFx && !kSilentBus) || l.getMainOutputChannelSet() == juce::AudioChannelSet::stereo();
}

void BricklabStudioProcessor::prepareToPlay(double sampleRate, int samplesPerBlock) {
    sr = sampleRate;
    player.prepare(sampleRate);
    glide.prepare(sampleRate);
    if (!kMidiFx) { cache.setRate((int) std::lround(sampleRate)); rateChanged = true; }   // notes render at the host's rate
    reverb.prepare({sampleRate, (juce::uint32) samplesPerBlock, 2});
}

void BricklabStudioProcessor::timerCallback() { applySoundAndKey(); }

void BricklabStudioProcessor::applySoundAndKey() {
    const int pg = page();
    int snd = (int) params.getRawParameterValue("sound")->load();
    if (pg == GlidePage) {
        static const auto list = glideSounds();
        snd = list[(size_t) juce::jlimit(0, (int) list.size() - 1, (int) params.getRawParameterValue("glidesound")->load())];
    }
    if (pg == LeadPage || pg == DronePage) {
        static const auto leads = soundsOf(1), drones = soundsOf(2);
        const auto& list = pg == LeadPage ? leads : drones;
        int i = (int) params.getRawParameterValue(pg == LeadPage ? "leadsound" : "dronesound")->load();
        snd = list[(size_t) juce::jlimit(0, (int) list.size() - 1, i)];
    }
    int key = (int) params.getRawParameterValue("key")->load();
    int sc = (int) params.getRawParameterValue("scale")->load();
    player.setBassLevel(0.75f * params.getRawParameterValue("basslevel")->load());   // engine.py _bass: 0.75 x level
    const int oct = (int) params.getRawParameterValue("octave")->load();
    player.setOctave(pg == ChordPage ? oct : 0);
    const bool fresh = rateChanged.exchange(false);
    if (!fresh && snd == lastSound && key == lastKey && sc == lastScale && oct == lastOct) return;
    lastOct = oct;
    if (snd != lastSound) {
        cache.setSound(snd);
        player.setRelease(kPatches[snd].r);
    }
    player.setKey(key, (Scale) sc);
    lastSound = snd; lastKey = key; lastScale = sc;
    if (kMidiFx) return;                                  // nothing to render: it only sends notes
    std::vector<int> w;
    if (pg == LeadPage || pg == DronePage || pg == GlidePage) {   // the lead's range from the middle out; the drone's and glide's low
        const int mid = pg == LeadPage ? 64 : (pg == DronePage ? 50 : 52);
        for (int d = 0; d <= (pg == GlidePage ? 32 : 28); ++d) { if (mid + d < 128) w.push_back(mid + d); if (d && mid - d >= 0) w.push_back(mid - d); }
    } else
        w = player.wanted();
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

void BricklabStudioProcessor::padUp(int pos) {
    player.release();
    if (params.getRawParameterValue("latch")->load() < 0.5f) queueOut(false, pos);   // latched: keeps playing
}

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
    const int pg = page();
    if (pg == LeadPage || pg == DronePage) {                // a note of the scale; on the Drone page, its drone
        const auto& sc = scaleSteps(player.scale());
        for (int d = 0; d < 7; ++d)
            out.push_back(juce::MidiMessage::getMidiNoteName(player.key() + sc[(size_t) d], true, false, 3)
                          + "\n" + (pg == LeadPage ? "note" : "drone"));
        return out;
    }
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

void BricklabStudioProcessor::runChord(juce::AudioBuffer<float>& buffer, juce::MidiBuffer& midi, int n, bool audio, bool internal, bool out) {
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
    const bool latch = params.getRawParameterValue("latch")->load() > 0.5f;
    if (wasLatched && !latch && held.empty() && padsDown.load() == 0) queueOut(false, 0);   // latch off: let go
    wasLatched = latch;

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
}

// ---------------------------------------------------------------- the Lead and Drone pages
void BricklabStudioProcessor::uiPad(int degree, bool down) {
    const juce::SpinLock::ScopedLockType l(uiLock);
    uiQueue.push_back({degree, down});
}

void BricklabStudioProcessor::setName(const juce::String& name, const juce::String& sub) {
    const juce::SpinLock::ScopedLockType l(nameLock);
    lastName = name; lastRoman = sub;
}

void BricklabStudioProcessor::sendOff(juce::MidiBuffer& midi, int pos) {
    if (leadOut >= 0) { midi.addEvent(juce::MidiMessage::noteOff(1, leadOut), pos); leadOut = -1; }
    for (int m : droneOut) midi.addEvent(juce::MidiMessage::noteOff(1, m), pos);
    droneOut.clear();
}

void BricklabStudioProcessor::leadPlay(int m, int pos, juce::MidiBuffer& midi, bool internal, bool out) {
    const float glide = params.getRawParameterValue("leadglide")->load() * 0.4f;   // main.glide_time: up to 400 ms
    if (internal) player.leadOn(m, glide);
    if (out) {
        const int old = leadOut;
        if (old >= 0 && glide <= 0.005f) midi.addEvent(juce::MidiMessage::noteOff(1, old), pos);
        midi.addEvent(juce::MidiMessage::noteOn(1, m, (juce::uint8) 110), pos);
        if (old >= 0 && old != m && glide > 0.005f) midi.addEvent(juce::MidiMessage::noteOff(1, old), pos);   // legato: synths glide
        leadOut = m;
    }
    setName(juce::MidiMessage::getMidiNoteName(m, true, true, 3), "Lead");
}

void BricklabStudioProcessor::leadPress(int id, int m, int pos, juce::MidiBuffer& midi, bool internal, bool out) {   // modes.lead_press
    leadStack.erase(std::remove_if(leadStack.begin(), leadStack.end(), [id](auto& e) { return e.first == id; }), leadStack.end());
    leadStack.push_back({id, m});
    leadPlay(m, pos, midi, internal, out);
}

void BricklabStudioProcessor::leadRelease(int id, int pos, juce::MidiBuffer& midi, bool internal, bool out) {   // modes.lead_release
    const bool top = !leadStack.empty() && leadStack.back().first == id;
    leadStack.erase(std::remove_if(leadStack.begin(), leadStack.end(), [id](auto& e) { return e.first == id; }), leadStack.end());
    if (!top) return;
    if (!leadStack.empty()) { leadPlay(leadStack.back().second, pos, midi, internal, out); return; }   // back to the note still held
    player.leadOff();
    if (leadOut >= 0) { midi.addEvent(juce::MidiMessage::noteOff(1, leadOut), pos); leadOut = -1; }
}

void BricklabStudioProcessor::droneToggle(int pc, int deg, int pos, juce::MidiBuffer& midi, bool internal, bool out) {   // modes.drone_toggle
    for (int m : droneOut) midi.addEvent(juce::MidiMessage::noteOff(1, m), pos);
    droneOut.clear();
    if (pc == dronePc) {                                     // the same one again: off
        player.drone({}, 0);
        dronePc = -1; droneDegLit = -1;
        setName({}, {});
        return;
    }
    const int oct = (int) params.getRawParameterValue("octave")->load();
    const int root = 36 + pc + 12 * std::max(0, oct);
    std::vector<int> notes{root, root + 7, root + 12, root + 19};
    if (params.getRawParameterValue("dronethird")->load() > 0.5f) {
        const auto& sc = scaleSteps(player.scale());
        notes.push_back(root + 12 + ((sc[(size_t) ((deg + 2) % 7)] - sc[(size_t) deg]) % 12 + 12) % 12);
    }
    static const float slides[] = {0.f, 0.5f, 1.f, 2.f, 4.f};
    const float slide = slides[juce::jlimit(0, 4, (int) params.getRawParameterValue("droneslide")->load())];
    if (internal) player.drone(notes, slide);
    if (out) {
        for (int m : notes) midi.addEvent(juce::MidiMessage::noteOn(1, m, (juce::uint8) 90), pos);
        droneOut = notes;
    }
    dronePc = pc; droneDegLit = deg;
    setName(juce::MidiMessage::getMidiNoteName(root, true, false, 3), "Drone");
}

void BricklabStudioProcessor::runMono(juce::AudioBuffer<float>& buffer, juce::MidiBuffer& midi, int n, bool audio, bool internal, bool out, int pg) {
    struct Act { int pos, type, a; };                        // 0 key on, 1 key off, 2 pad down, 3 pad up, 4 bend, 5 mod wheel
    std::vector<Act> acts;
    {
        const juce::SpinLock::ScopedLockType l(uiLock);
        for (auto [d, down] : uiQueue) acts.push_back({0, down ? 2 : 3, d});
        uiQueue.clear();
    }
    for (const auto meta : midi) {
        const auto m = meta.getMessage();
        const int p = juce::jlimit(0, std::max(0, n - 1), meta.samplePosition);
        if (m.isNoteOn()) acts.push_back({p, 0, m.getNoteNumber()});
        else if (m.isNoteOff()) acts.push_back({p, 1, m.getNoteNumber()});
        else if (m.isPitchWheel()) acts.push_back({p, 4, m.getPitchWheelValue()});
        else if (m.isController() && m.getControllerNumber() == 1) acts.push_back({p, 5, m.getControllerValue()});
        else if (m.isAllNotesOff() || m.isAllSoundOff())
            for (auto e : std::vector<std::pair<int, int>>(leadStack)) acts.push_back({p, e.first >= 100 ? 3 : 1, e.first >= 100 ? e.first - 100 : e.first});
    }
    std::stable_sort(acts.begin(), acts.end(), [](const Act& x, const Act& y) { return x.pos < y.pos; });
    midi.clear();
    if (!out && (leadOut >= 0 || !droneOut.empty())) sendOff(midi, 0);   // MIDI out switched off with notes on

    double bpm = 120;
    if (auto* ph = getPlayHead())
        if (auto pos = ph->getPosition())
            if (auto b = pos->getBpm()) bpm = *b;
    player.setTempo(bpm);
    // the drone's motion: the knobs, or the wheels while they're moved (mod wheel pulses, pitch bend thins or blooms)
    auto droneMotion = [&] {
        const float x = std::abs(bendSemis) > 0.04f ? bendSemis / 2.0f : params.getRawParameterValue("dronex")->load();
        const float y = vibDepth > 0.02f ? -vibDepth : params.getRawParameterValue("droney")->load();
        player.droneMod(x, y);
    };
    droneMotion();

    const int oct = (int) params.getRawParameterValue("octave")->load();
    const int key = player.key();
    const auto& sc = scaleSteps(player.scale());
    float* L = audio ? buffer.getWritePointer(0) : nullptr;
    float* R = audio ? buffer.getWritePointer(1) : nullptr;
    int at = 0;
    for (auto& e : acts) {
        if (audio && e.pos > at) { player.render(L + at, R + at, e.pos - at); at = e.pos; }
        if (e.type == 4) {                                   // pitch bend: 2 semitones, as most synths
            bendSemis = (float) (e.a - 8192) / 8192.0f * 2.0f;
            if (pg == LeadPage) player.leadMod(bendSemis, vibDepth); else droneMotion();
            if (out && pg == LeadPage) midi.addEvent(juce::MidiMessage::pitchWheel(1, e.a), e.pos);
            continue;
        }
        if (e.type == 5) {                                   // the mod wheel: vibrato
            vibDepth = (float) e.a / 127.0f;
            if (pg == LeadPage) player.leadMod(bendSemis, vibDepth); else droneMotion();
            if (out && pg == LeadPage) midi.addEvent(juce::MidiMessage::controllerEvent(1, 1, e.a), e.pos);
            continue;
        }
        if (pg == LeadPage) {
            if (e.type == 0) leadPress(e.a, juce::jlimit(0, 127, e.a + 12 * oct), e.pos, midi, internal, out);
            else if (e.type == 1) leadRelease(e.a, e.pos, midi, internal, out);
            else if (e.type == 2) {                          // modes.lead_midi: a pad is a note of the scale
                int m = 60 + key + sc[(size_t) e.a] + 12 * oct;
                if (key >= 7) m -= 12;
                leadPress(100 + e.a, m, e.pos, midi, internal, out);
            } else leadRelease(100 + e.a, e.pos, midi, internal, out);
        } else {                                             // Drone: a key or pad picks the root, the same again stops
            if (e.type == 0) droneToggle(e.a % 12, degreeOf(e.a, key, player.scale()), e.pos, midi, internal, out);
            else if (e.type == 2) droneToggle((key + sc[(size_t) e.a]) % 12, e.a, e.pos, midi, internal, out);
        }
    }
    if (audio && at < n) player.render(L + at, R + at, n - at);

    // MIDI out pulses the drone too: the same gate as expression (CC 11), so any synth breathes with it
    if (out && pg == DronePage && !droneOut.empty()) {
        float y = vibDepth > 0.02f ? -vibDepth : params.getRawParameterValue("droney")->load();
        y = std::abs(y) < 0.25f ? 0.0f : (std::abs(y) - 0.25f) / 0.75f * (y > 0 ? 1.0f : -1.0f);
        for (int i = 0; i < n; i += 128) {
            const int v = y < 0 ? (int) std::lround(127 * dronePulse(y, (double) (clock + i) / sr, bpm)) : 127;
            if (v != lastExpr) { midi.addEvent(juce::MidiMessage::controllerEvent(1, 11, v), i); lastExpr = v; }
        }
    }
}

// ---------------------------------------------------------------- the Glide page
void BricklabStudioProcessor::glideOut(juce::MidiBuffer& midi, int pos, bool allOff) {
    if (allOff) {
        for (int i = 0; i < kGlideVoices; ++i)
            if (mpeNote[(size_t) i] > 0) { midi.addEvent(juce::MidiMessage::noteOff(i + 2, mpeNote[(size_t) i] - 1), pos); mpeNote[(size_t) i] = 0; }
        for (int m : glideNotesOut) midi.addEvent(juce::MidiMessage::noteOff(1, m), pos);
        glideNotesOut.clear();
        return;
    }
    if ((int) params.getRawParameterValue("glidempe")->load() == 1) {   // Notes: the chord as plain notes, no glide
        std::vector<int> want;
        for (int i = 0; i < kGlideVoices; ++i)
            if (glide.on[(size_t) i]) want.push_back((int) std::lround(glide.target[(size_t) i] / 100.0f));
        std::sort(want.begin(), want.end());
        want.erase(std::unique(want.begin(), want.end()), want.end());
        if (want != glideNotesOut) {
            for (int m : glideNotesOut) midi.addEvent(juce::MidiMessage::noteOff(1, m), pos);
            for (int m : want) midi.addEvent(juce::MidiMessage::noteOn(1, m, (juce::uint8) 96), pos);
            glideNotesOut = want;
        }
        return;
    }
    if (!mpeReady) {                                         // MPE: the zone (ch 2..7) and a 48-semitone bend range
        midi.addEvent(juce::MidiMessage::controllerEvent(1, 101, 0), pos);
        midi.addEvent(juce::MidiMessage::controllerEvent(1, 100, 6), pos);
        midi.addEvent(juce::MidiMessage::controllerEvent(1, 6, kGlideVoices), pos);
        for (int ch = 2; ch < 2 + kGlideVoices; ++ch) {
            midi.addEvent(juce::MidiMessage::controllerEvent(ch, 101, 0), pos);
            midi.addEvent(juce::MidiMessage::controllerEvent(ch, 100, 0), pos);
            midi.addEvent(juce::MidiMessage::controllerEvent(ch, 6, 48), pos);
            midi.addEvent(juce::MidiMessage::controllerEvent(ch, 38, 0), pos);
        }
        mpeReady = true;
    }
    for (int i = 0; i < kGlideVoices; ++i) {                 // each voice its own channel; its glide is its pitch bend
        const int ch = i + 2;
        int& note = mpeNote[(size_t) i];                     // note + 1 (0: none)
        const bool on = glide.on[(size_t) i];
        const double c = glide.cents[(size_t) i];
        if (!on) {
            if (note > 0) { midi.addEvent(juce::MidiMessage::noteOff(ch, note - 1), pos); note = 0; }
            continue;
        }
        if (note > 0 && std::abs(c - (note - 1) * 100.0) > 4700) { midi.addEvent(juce::MidiMessage::noteOff(ch, note - 1), pos); note = 0; }
        const int bendFor = note > 0 ? note - 1 : juce::jlimit(0, 127, (int) std::lround(c / 100.0));
        const int pb = juce::jlimit(0, 16383, 8192 + (int) std::lround((c - bendFor * 100.0) / 4800.0 * 8191.0));
        if (note == 0) {
            midi.addEvent(juce::MidiMessage::pitchWheel(ch, pb), pos);
            midi.addEvent(juce::MidiMessage::noteOn(ch, bendFor, (juce::uint8) 96), pos);
            note = bendFor + 1;
            mpeBend[(size_t) i] = pb;
        } else if (std::abs(pb - mpeBend[(size_t) i]) >= 2) {
            midi.addEvent(juce::MidiMessage::pitchWheel(ch, pb), pos);
            mpeBend[(size_t) i] = pb;
        }
    }
}

void BricklabStudioProcessor::runGlide(juce::AudioBuffer<float>& buffer, juce::MidiBuffer& midi, int n, bool audio, bool out) {
    GlideSettings st;
    st.chord = (int) params.getRawParameterValue("glidechord")->load();
    st.path = (int) params.getRawParameterValue("glidepath")->load();
    st.timing = (int) params.getRawParameterValue("glidetiming")->load();
    st.move = (int) params.getRawParameterValue("glidemove")->load();
    st.time = kGlideTimes[juce::jlimit(0, kNumGlideTimes - 1, (int) params.getRawParameterValue("glidetime")->load())];
    st.fade = kGlideFades[juce::jlimit(0, kNumGlideFades - 1, (int) params.getRawParameterValue("glidefade")->load())];
    st.sub = params.getRawParameterValue("glidesub")->load() > 0.5f;
    glide.set(st);
    glide.setKey(player.key(), player.scale());
    const int range = kGlideBends[juce::jlimit(0, kNumGlideBends - 1, (int) params.getRawParameterValue("glidebend")->load())];

    struct Act { int pos, type, a; };                         // 0 keys read, 2 pad, 4 bend, 5 mod wheel, 6 stop, 7 bloom
    std::vector<Act> acts;
    {
        const juce::SpinLock::ScopedLockType l(uiLock);
        for (auto [d, down] : uiQueue)
            if (down) acts.push_back({0, d == 100 ? 6 : (d == 101 ? 7 : 2), d});
        uiQueue.clear();
    }
    {                                                         // the keys: a chord's notes arrive one by one
        int at = 0;
        auto advance = [&](int upto) {
            while (pending >= 0 && at + pending <= upto) {
                at += std::max(1, pending);
                pending = -1;
                acts.push_back({std::min(at, n - 1), 0, 0});
            }
            if (pending >= 0) pending -= upto - at;
            at = upto;
        };
        for (const auto meta : midi) {
            const auto m = meta.getMessage();
            const int p = juce::jlimit(0, std::max(0, n - 1), meta.samplePosition);
            advance(p);
            if (m.isNoteOn()) { held.insert(m.getNoteNumber()); pending = (int) (0.035 * sr); }
            else if (m.isNoteOff()) held.erase(m.getNoteNumber());       // let go: the chord holds
            else if (m.isPitchWheel()) acts.push_back({p, 4, m.getPitchWheelValue()});
            else if (m.isController() && m.getControllerNumber() == 1) acts.push_back({p, 5, m.getControllerValue()});
            else if (m.isAllNotesOff() || m.isAllSoundOff()) held.clear();
        }
        advance(n);
    }
    std::stable_sort(acts.begin(), acts.end(), [](const Act& x, const Act& y) { return x.pos < y.pos; });
    midi.clear();

    float* L = audio ? buffer.getWritePointer(0) : nullptr;
    float* R = audio ? buffer.getWritePointer(1) : nullptr;
    std::vector<float> scratch;
    if (!audio) scratch.assign((size_t) n * 2, 0.0f);          // the MIDI builds still move the voices
    float* l = audio ? L : scratch.data();
    float* r = audio ? R : scratch.data() + n;
    const bool sound = audio && !kMidiFx;
    int at = 0;
    for (auto& e : acts) {
        if (e.pos > at) { glide.render(l + at, r + at, e.pos - at); if (out) glideOut(midi, at, false); at = e.pos; }
        const float gx = 1.0f + 3.0f * glideSwell;              // the mod wheel stretches the glides up to 4x
        if (e.type == 0) {
            std::vector<int> keys(held.begin(), held.end());
            if (keys.size() >= 2) setName(glide.follow(keys, gx), "Keys");
            else if (keys.size() == 1) setName(glide.playDegree(degreeOf(keys[0], player.key(), player.scale()), Mods{}, gx, false), "Glide");
        } else if (e.type == 2) {
            auto name = glide.playDegree(e.a, Mods{}, gx, true);
            setName(name, name.empty() ? "" : "Glide");
        } else if (e.type == 4) glide.setBend((float) (e.a - 8192) / 8192.0f * (float) range);
        else if (e.type == 5) { glideSwell = (float) e.a / 127.0f; glide.setSwell(glideSwell); }
        else if (e.type == 6) { glide.stop(); setName({}, {}); }
        else if (e.type == 7) glide.bloom();
    }
    if (at < n) glide.render(l + at, r + at, n - at);
    if (out) glideOut(midi, std::max(0, n - 1), false);
    if (!sound && audio) buffer.clear();
}

void BricklabStudioProcessor::processBlock(juce::AudioBuffer<float>& buffer, juce::MidiBuffer& midi) {
    juce::ScopedNoDenormals noDenormals;
    const int n = buffer.getNumSamples();
    buffer.clear();
    const bool audio = buffer.getNumChannels() >= 2;
    // the instrument is the sound; the MIDI FX is the notes for the instrument after it
    const bool internal = audio && !kMidiFx;
    const bool out = kMidiFx;
    const int pg = page();
    juce::MidiBuffer flush;
    if (pg != lastPage) {                                    // a new page: the old one lets go
        if (lastPage >= 0) {
            sendOff(flush, 0);
            for (auto [ch, note] : sounding) flush.addEvent(juce::MidiMessage::noteOff(ch, note), 0);
            sounding.clear();
            patterns.clear(clock);
            std::vector<NoteEvent> gone;
            patterns.take(INT64_MAX, gone);
            player.allOff();
            glide.stop();
            glideOut(flush, 0, true);
            leadStack.clear();
            dronePc = -1; droneDegLit = -1;
            setName({}, {});
        }
        lastPage = pg;
    }
    if (pg == GlidePage) runGlide(buffer, midi, n, audio, out);
    else if (pg == ChordPage) runChord(buffer, midi, n, audio, internal, out);
    else runMono(buffer, midi, n, audio, internal, out, pg);
    if (!flush.isEmpty()) midi.addEvents(flush, 0, -1, 0);
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
