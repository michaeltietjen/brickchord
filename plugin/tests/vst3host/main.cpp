// Loads a VST3 the way a DAW does (JUCE's VST3 hosting), plays it keys on the Chord, Lead and
// Drone pages and prints the MIDI it sends out and the level of its audio.
//   vst3host "~/Library/Audio/Plug-Ins/VST3/Bricklab Studio MIDI.vst3"
#include <juce_audio_processors/juce_audio_processors.h>
#include <cmath>
#include <iostream>

int main(int argc, char** argv) {
    juce::ScopedJuceInitialiser_GUI gui;
    if (argc < 2) { std::cout << "usage: vst3host plugin.vst3\n"; return 1; }
    juce::AudioPluginFormatManager fm;
    fm.addFormat(new juce::VST3PluginFormat());
    juce::OwnedArray<juce::PluginDescription> found;
    juce::VST3PluginFormat vst3;
    vst3.findAllTypesForFile(found, argv[1]);
    if (found.isEmpty()) { std::cout << "no plugin in " << argv[1] << "\n"; return 1; }
    juce::String err;
    auto p = fm.createPluginInstance(*found[0], 44100, 512, err);
    if (!p) { std::cout << "load failed: " << err << "\n"; return 1; }
    std::cout << "loaded: " << p->getName() << " by " << found[0]->manufacturerName
              << (p->producesMidi() ? ", sends MIDI" : ", no MIDI out") << ", " << p->getTotalNumOutputChannels() << " out\n";
    p->enableAllBuses();
    p->prepareToPlay(44100, 512);
    juce::AudioBuffer<float> buf(std::max(2, p->getTotalNumOutputChannels()), 512);
    auto setPage = [&](int page) {                                // Page: Chord, Lead, Drone, Glide
        for (auto* q : p->getParameters())
            if (q->getName(64) == "Page") q->setValueNotifyingHost((float) page / 3.0f);
    };
    juce::MidiBuffer pend;
    int lastBend[17] = {};
    auto run = [&](double secs, const char* label) {
        juce::String s;
        double sum = 0; long n = 0; int bends = 0, press = 0;
        for (int b = 0; b < (int) (secs * 44100 / 512); ++b) {
            juce::MidiBuffer m;
            m.swapWith(pend);
            buf.clear();
            p->processBlock(buf, m);
            for (const auto meta : m) {
                auto msg = meta.getMessage();
                if (msg.isNoteOn()) s << "on ch" << msg.getChannel() << " " << msg.getNoteNumber() << ", ";
                else if (msg.isNoteOff()) s << "off ch" << msg.getChannel() << " " << msg.getNoteNumber() << ", ";
                else if (msg.isPitchWheel()) { ++bends; lastBend[msg.getChannel()] = msg.getPitchWheelValue(); }
                else if (msg.isChannelPressure()) ++press;
            }
            for (int i = 0; i < 512; ++i) { float v = buf.getSample(0, i); sum += v * v; ++n; }
            juce::MessageManager::getInstance()->runDispatchLoopUntil(5);
        }
        std::cout << juce::String(label).paddedRight(' ', 18) << " rms " << juce::String(std::sqrt(sum / (double) std::max(1L, n)), 4) << "  " << s << (bends ? juce::String(bends) + " pitch bends " : juce::String()) << (press ? juce::String(press) + " pressure" : juce::String()) << "\n";
        if (bends) { std::cout << "      bends now (st):"; for (int c = 2; c <= 7; ++c) std::cout << " " << juce::String((lastBend[c] - 8192) / 8191.0 * 48.0, 1); std::cout << "\n"; }
    };
    auto key = [&](bool on, int k) { pend.addEvent(on ? juce::MidiMessage::noteOn(1, k, (juce::uint8) 100) : juce::MidiMessage::noteOff(1, k), 0); };
    if (argc > 2 && juce::String(argv[2]) == "drone") {                   // vst3host plugin.vst3 drone: the strum and arp
        auto set = [&](const char* name, float v01) { for (auto* q : p->getParameters()) if (q->getName(64) == name) q->setValueNotifyingHost(v01); };
        setPage(2);
        juce::MessageManager::getInstance()->runDispatchLoopUntil(9000);
        set("Pluck level", 0.0f);
        key(true, 62); key(false, 62); run(1.5, "D drone, no strum");
        set("Pluck level", 1.0f);
        for (int v = 0; v <= 127; v += 8) { pend.addEvent(juce::MidiMessage::controllerEvent(1, 1, v), 0); run(0.06, "  mod wheel"); }
        run(1.0, "after the strum");
        pend.addEvent(juce::MidiMessage::pitchWheel(1, 16000), 0); run(1.0, "pitch wheel up: arp");
        pend.addEvent(juce::MidiMessage::pitchWheel(1, 8192), 0); run(1.5, "wheel centred");
        set("Pluck arp", 0.25f); run(1.0, "arp Up, 1/8");
        set("Pluck arp", 0.0f); run(2.0, "arp off");
        set("Drone chord", 7.0f / 8.0f); key(true, 57); key(false, 57); run(2.0, "A, quartal");
        key(true, 57); key(false, 57); run(1.0, "stopped");
        set("Pluck level", 0.0f); set("Drone overtones", 0.0f); set("Sympathetic strings", 0.0f);
        for (int k = 0; k < 7; ++k) {                                         // each recorded drone sound, held 8 s
            set("Drone sound", (8.0f + (float) k) / 14.0f);
            juce::MessageManager::getInstance()->runDispatchLoopUntil(2500);
            key(true, 50); key(false, 50);
            for (int sec = 0; sec < 8; ++sec) run(1.0, (juce::String("rec ") + juce::String(k) + " s" + juce::String(sec)).toRawUTF8());
            key(true, 50); key(false, 50); run(1.5, "  stopped");
        }
        set("Drone sound", 8.0f / 14.0f);
        juce::MessageManager::getInstance()->runDispatchLoopUntil(2500);
        key(true, 50); key(false, 50); run(3.0, "cellos, dry");
        set("Drone cloud", 1.0f); run(3.0, "cloud full");
        set("Drone cloud", 0.0f); run(2.0, "cloud off");
        set("Pluck level", 1.0f); set("Pluck arp", 0.25f); run(2.0, "arp, no ring");
        set("Sympathetic strings", 1.0f); run(3.0, "arp, ring full");
        return 0;
    }
    if (argc > 2) {                                                       // vst3host plugin.vst3 long: hold each page 20 s
        for (int pg : {3, 0, 2}) {
            setPage(pg);
            juce::MessageManager::getInstance()->runDispatchLoopUntil(8000);
            if (pg == 2) { key(true, 62); key(false, 62); } else key(true, 62);
            for (int sec = 0; sec < 20; ++sec) run(1.0, (juce::String("page ") + juce::String(pg) + " s" + juce::String(sec)).toRawUTF8());
            if (pg == 2) { key(true, 62); key(false, 62); } else key(false, 62);
            run(1.0, "released");
        }
        return 0;
    }
    setPage(0);                                                           // the Glide page is the default
    juce::MessageManager::getInstance()->runDispatchLoopUntil(6000);       // the sounds render
    key(true, 62); run(0.5, "Chord page: D");
    key(false, 62); run(0.5, "released");
    for (auto* q : p->getParameters()) if (q->getName(64) == "Octave") q->setValueNotifyingHost(3.0f / 4.0f);   // +1
    juce::MessageManager::getInstance()->runDispatchLoopUntil(3000);
    key(true, 62); run(0.5, "octave +1: D");
    key(false, 62); run(0.5, "released");
    for (auto* q : p->getParameters()) if (q->getName(64) == "Octave") q->setValueNotifyingHost(0.5f);
    setPage(1); run(0.1, "Lead page");
    key(true, 69); run(0.3, "A4");
    key(false, 69); run(0.3, "released");
    setPage(2); run(0.1, "Drone page");
    key(true, 62); key(false, 62); run(0.5, "D: drone");
    key(true, 62); key(false, 62); run(0.5, "D again: stops");
    setPage(3);
    juce::MessageManager::getInstance()->runDispatchLoopUntil(8000);   // the glide sound renders
    run(0.1, "Glide page");
    key(true, 57); run(0.05, "A"); key(false, 57); run(1.5, "Am, let go: holds");
    key(true, 62); run(0.05, "D"); key(false, 62); run(0.4, "gliding to Dm"); run(1.2, "Dm");
    for (auto* q : p->getParameters()) if (q->getName(64) == "Octave") q->setValueNotifyingHost(3.0f / 4.0f);
    key(true, 57); run(0.05, "A"); key(false, 57); run(2.0, "glide octave +1: Am");
    for (auto* q : p->getParameters()) if (q->getName(64) == "Octave") q->setValueNotifyingHost(0.5f);
    key(true, 55); key(true, 59); key(true, 62); run(0.05, "G B D"); key(false, 55); key(false, 59); key(false, 62); run(2.0, "G from keys");
    if (auto* ap = dynamic_cast<juce::AudioPluginInstance*>(p.get())) {
        std::cout << "presets:";
        for (int i = 0; i < ap->getNumPrograms(); ++i) std::cout << " [" << ap->getProgramName(i) << "]";
        std::cout << "\n";
    }
    p->releaseResources();
    return 0;
}
