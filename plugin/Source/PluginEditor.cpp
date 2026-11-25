#include "PluginEditor.h"
#include "core/PatchData.h"

namespace {
const juce::Colour chassis(0xffe4e2dc), plate(0xffefede8), ink(0xff18161c), dim(0xff6d6874),
    seam(0xffcfccc4), orange(0xffff5a1f), screen(0xff121016), sink(0xffece4d6), teal(0xff3f9e95);
const char* TAB_NAMES[] = {"Chord", "Lead", "Drone", "Glide"};
const char* SOON[] = {"", "", "",
    "Glide: six voices gliding from chord to chord, blooms, Moves, the progression with a melody over it. "
    "Play it from your keyboard, with the mod wheel and pitch bend shaping the glide. Coming next."};
}

void Pad::paint(juce::Graphics& g) {
    auto r = getLocalBounds().toFloat().reduced(2);
    g.setColour(lit ? orange : plate);
    g.fillRoundedRectangle(r, 12);
    g.setColour(seam);
    g.drawRoundedRectangle(r, 12, 1.2f);
    g.setColour(ink);
    g.setFont(juce::FontOptions(20.f, juce::Font::bold));
    g.drawFittedText(top, r.withTrimmedBottom(r.getHeight() * 0.35f).toNearestInt(), juce::Justification::centredBottom, 1);
    g.setColour(lit ? ink : dim);
    g.setFont(juce::FontOptions(13.f));
    g.drawFittedText(sub, r.withTrimmedTop(r.getHeight() * 0.62f).toNearestInt(), juce::Justification::centredTop, 1);
}

BricklabStudioEditor::BricklabStudioEditor(BricklabStudioProcessor& p) : AudioProcessorEditor(&p), proc(p) {
    for (int t = 0; t < 4; ++t) {
        auto* b = tabs.add(new juce::TextButton(TAB_NAMES[t]));
        b->setClickingTogglesState(false);
        b->onClick = [this, t] {                             // the page is the instance's: saved with the project
            if (auto* p = proc.params.getParameter("page")) p->setValueNotifyingHost(p->convertTo0to1((float) t));
            showTab(t);
        };
        addAndMakeVisible(b);
    }
    for (int d = 0; d < 7; ++d) {
        auto* pad = pads.add(new Pad());
        pad->onDown = [this, d] { padPress(d, true); };
        pad->onUp = [this, d] { padPress(d, false); };
        addAndMakeVisible(pad);
    }
    const char* modNames[] = {"7th", "sus4", "9th", "flip"};
    for (int i = 0; i < 4; ++i) {
        auto* b = modButtons.add(new juce::TextButton(modNames[i]));
        b->setClickingTogglesState(true);
        b->onClick = [this, i, b] {
            bool on = b->getToggleState();
            auto& m = proc.mods;
            if (i == 0) m.seventh = on; else if (i == 1) m.sus = on; else if (i == 2) m.ninth = on; else m.flip = on;
        };
        addAndMakeVisible(b);
    }
    latch.setClickingTogglesState(true);
    addAndMakeVisible(latch);
    third.setClickingTogglesState(true);
    addAndMakeVisible(third);
    for (int i : BricklabStudioProcessor::soundsOf(1)) leadSound.addItem(brick::kPatches[i].name, leadSound.getNumItems() + 1);
    for (int i : BricklabStudioProcessor::soundsOf(2)) droneSound.addItem(brick::kPatches[i].name, droneSound.getNumItems() + 1);
    octave.addItemList({"Oct -2", "Oct -1", "Oct 0", "Oct +1", "Oct +2"}, 1);
    droneSlide.addItemList({"Off (restrike)", "0.5 s", "1 s", "2 s", "4 s"}, 1);
    for (auto* c : {&leadSound, &droneSound, &octave, &droneSlide}) addAndMakeVisible(c);
    for (auto* s : {&leadGlide, &droneY, &droneX}) {
        s->setSliderStyle(juce::Slider::LinearHorizontal);
        s->setTextBoxStyle(juce::Slider::NoTextBox, false, 0, 0);
        addAndMakeVisible(s);
    }
    octL.setText("Octave", juce::dontSendNotification);
    glideL.setText("Glide", juce::dontSendNotification);
    slideL.setText("Slide", juce::dontSendNotification);
    pulseL.setText("Pulse | Swell", juce::dontSendNotification);
    bloomL.setText("Thin | Bloom", juce::dontSendNotification);
    for (auto* l : {&octL, &glideL, &slideL, &pulseL, &bloomL}) { l->setColour(juce::Label::textColourId, dim); addAndMakeVisible(l); }
    // the sound list, grouped as on the handheld: chord sounds, lead sounds, drone sounds
    const char* groups[] = {"Chord sounds", "Lead sounds", "Drone sounds"};
    int lastGroup = -1;
    for (int i = 0; i < brick::kNumPatches; ++i) {
        if (brick::kPatches[i].group != lastGroup) { lastGroup = brick::kPatches[i].group; sound.addSectionHeading(groups[lastGroup]); }
        sound.addItem(brick::kPatches[i].name, i + 1);
    }
    key.addItemList({"C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"}, 1);
    scale.addItemList({"Major", "Minor", "Dorian", "Mixolydian"}, 1);
    for (int i = 0; i < brick::kNumPlayModes; ++i) mode.addItem(brick::kPlayModes[i], i + 1);
    arpOct.addItemList({"1 oct", "2 oct", "3 oct", "4 oct"}, 1);
    for (int i = 0; i < brick::kNumBassModes; ++i) bassMode.addItem(brick::kBassModes[i], i + 1);
    for (auto* c : {&sound, &key, &scale, &mode, &arpOct, &bassMode}) addAndMakeVisible(c);
    modeL.setText("Play", juce::dontSendNotification);
    arpL.setText("Arp", juce::dontSendNotification);
    bassL.setText("Bass", juce::dontSendNotification);
    for (auto* l : {&modeL, &arpL, &bassL}) { l->setColour(juce::Label::textColourId, dim); addAndMakeVisible(l); }
    outNote.setText("MIDI: chords ch 1, bass ch 2", juce::dontSendNotification);
    outNote.setJustificationType(juce::Justification::centredRight);
    outNote.setColour(juce::Label::textColourId, dim);
    addAndMakeVisible(outNote);
    for (auto* s : {&space, &volume, &bassLvl}) {
        s->setSliderStyle(juce::Slider::LinearHorizontal);
        s->setTextBoxStyle(juce::Slider::NoTextBox, false, 0, 0);
        addAndMakeVisible(s);
    }
    spaceL.setText("Space", juce::dontSendNotification);
    volumeL.setText("Volume", juce::dontSendNotification);
    for (auto* l : {&spaceL, &volumeL}) { l->setColour(juce::Label::textColourId, dim); addAndMakeVisible(l); }
    soon.setJustificationType(juce::Justification::centred);
    soon.setColour(juce::Label::textColourId, sink);
    soon.setFont(juce::FontOptions(17.f));
    addChildComponent(soon);
    auto& ps = proc.params;
    aSound = std::make_unique<juce::AudioProcessorValueTreeState::ComboBoxAttachment>(ps, "sound", sound);
    aKey = std::make_unique<juce::AudioProcessorValueTreeState::ComboBoxAttachment>(ps, "key", key);
    aScale = std::make_unique<juce::AudioProcessorValueTreeState::ComboBoxAttachment>(ps, "scale", scale);
    aLeadSound = std::make_unique<juce::AudioProcessorValueTreeState::ComboBoxAttachment>(ps, "leadsound", leadSound);
    aDroneSound = std::make_unique<juce::AudioProcessorValueTreeState::ComboBoxAttachment>(ps, "dronesound", droneSound);
    aOctave = std::make_unique<juce::AudioProcessorValueTreeState::ComboBoxAttachment>(ps, "octave", octave);
    aDroneSlide = std::make_unique<juce::AudioProcessorValueTreeState::ComboBoxAttachment>(ps, "droneslide", droneSlide);
    aThird = std::make_unique<juce::AudioProcessorValueTreeState::ButtonAttachment>(ps, "dronethird", third);
    aLeadGlide = std::make_unique<juce::AudioProcessorValueTreeState::SliderAttachment>(ps, "leadglide", leadGlide);
    aDroneY = std::make_unique<juce::AudioProcessorValueTreeState::SliderAttachment>(ps, "droney", droneY);
    aDroneX = std::make_unique<juce::AudioProcessorValueTreeState::SliderAttachment>(ps, "dronex", droneX);
    aLatch = std::make_unique<juce::AudioProcessorValueTreeState::ButtonAttachment>(ps, "latch", latch);
    aMode = std::make_unique<juce::AudioProcessorValueTreeState::ComboBoxAttachment>(ps, "mode", mode);
    aArpOct = std::make_unique<juce::AudioProcessorValueTreeState::ComboBoxAttachment>(ps, "arpoct", arpOct);
    aBassMode = std::make_unique<juce::AudioProcessorValueTreeState::ComboBoxAttachment>(ps, "bassmode", bassMode);
    aSpace = std::make_unique<juce::AudioProcessorValueTreeState::SliderAttachment>(ps, "space", space);
    aVolume = std::make_unique<juce::AudioProcessorValueTreeState::SliderAttachment>(ps, "volume", volume);
    aBassLvl = std::make_unique<juce::AudioProcessorValueTreeState::SliderAttachment>(ps, "basslevel", bassLvl);

    auto& lf = getLookAndFeel();
    lf.setColour(juce::TextButton::buttonColourId, plate);
    lf.setColour(juce::TextButton::buttonOnColourId, ink);
    lf.setColour(juce::TextButton::textColourOffId, ink);
    lf.setColour(juce::TextButton::textColourOnId, plate);
    lf.setColour(juce::ComboBox::backgroundColourId, plate);
    lf.setColour(juce::ComboBox::textColourId, ink);
    lf.setColour(juce::ComboBox::outlineColourId, seam);
    lf.setColour(juce::ComboBox::arrowColourId, dim);
    lf.setColour(juce::PopupMenu::backgroundColourId, plate);
    lf.setColour(juce::PopupMenu::textColourId, ink);
    lf.setColour(juce::ToggleButton::textColourId, ink);
    lf.setColour(juce::ToggleButton::tickColourId, orange);
    lf.setColour(juce::Slider::thumbColourId, orange);
    lf.setColour(juce::Slider::trackColourId, orange.withAlpha(0.6f));
    lf.setColour(juce::Slider::backgroundColourId, seam);

    setWantsKeyboardFocus(true);
    setSize(900, 560);
    showTab(proc.page());
    startTimerHz(15);
}

BricklabStudioEditor::~BricklabStudioEditor() { stopTimer(); }

void BricklabStudioEditor::showTab(int t) {
    tab = t;
    for (int i = 0; i < tabs.size(); ++i) tabs[i]->setToggleState(i == t, juce::dontSendNotification);
    const bool chord = t == 0, lead = t == 1, drone = t == 2, playing = t <= 2, sounds = !proc.kMidiFx;
    auto show = [](std::initializer_list<juce::Component*> cs, bool on) { for (auto* c : cs) c->setVisible(on); };
    for (auto* p : pads) p->setVisible(playing);
    for (auto* b : modButtons) b->setVisible(chord);
    latch.setVisible(chord);
    show({&sound, &bassLvl}, chord && sounds);
    show({&leadSound}, lead && sounds);
    show({&droneSound}, drone && sounds);
    show({&key, &scale}, playing);
    show({&space, &volume, &spaceL, &volumeL}, playing && sounds);
    show({&mode, &arpOct, &bassMode, &modeL, &arpL, &bassL}, chord);
    show({&octave, &octL}, lead || drone);
    show({&leadGlide, &glideL}, lead);
    show({&third, &droneSlide, &slideL, &droneY, &droneX, &pulseL, &bloomL}, drone);
    outNote.setText(chord ? (proc.kMidiFx ? "Chords on ch 1, bass on ch 2" : "") : (lead ? "Mod wheel: vibrato  Bend: 2 st" : ""),
                    juce::dontSendNotification);
    outNote.setVisible(chord || lead);
    for (auto* p : pads) p->lit = false;
    litDrone = -2;
    soon.setText(SOON[t], juce::dontSendNotification);
    soon.setVisible(!playing);
    layoutRows();
    repaint();
}

void BricklabStudioEditor::padPress(int d, bool down) {
    const int pg = proc.page();
    if (pg == 0) {
        if (down) { ++proc.padsDown; proc.padDown(d); }
        else { proc.padsDown = std::max(0, proc.padsDown - 1); proc.padUp(); }
    } else if (pg == 1 || (pg == 2 && down))
        proc.uiPad(d, down);
}

void BricklabStudioEditor::paint(juce::Graphics& g) {
    g.fillAll(chassis);
    auto r = getLocalBounds();
    auto bar = r.removeFromTop(56);
    g.setColour(ink);
    g.fillRect(bar);
    g.setColour(sink);
    g.setFont(juce::FontOptions(22.f, juce::Font::bold));
    g.drawText("bricklab", bar.withTrimmedLeft(22).withWidth(110), juce::Justification::centredLeft);
    g.setColour(sink.withAlpha(0.6f));
    g.setFont(juce::FontOptions(22.f));
    g.drawText("studio", bar.withTrimmedLeft(122).withWidth(90), juce::Justification::centredLeft);
    // the screen: key, sound, the chord
    auto scr = juce::Rectangle<int>(22, 72, getWidth() - 44, 170);
    g.setColour(juce::Colour(0xff26242b));
    g.fillRoundedRectangle(scr.toFloat(), 16);
    g.setColour(screen);
    g.fillRoundedRectangle(scr.toFloat().reduced(7), 11);
    auto in = scr.reduced(22, 16);
    g.setColour(juce::Colour(0xffa39fae));
    g.setFont(juce::FontOptions(13.f));
    auto top = in.removeFromTop(18);
    g.drawText((key.getText() + " " + scale.getText()).toUpperCase(), top, juce::Justification::centredLeft);
    auto* sc = tab == 0 ? &sound : (tab == 1 ? &leadSound : &droneSound);
    g.drawText(TAB_NAMES[tab] + juce::String("  ") + (tab <= 2 && !proc.kMidiFx ? sc->getText().toUpperCase() : ""), top, juce::Justification::centredRight);
    if (tab <= 2) {
        auto name = proc.chordName();
        g.setColour(orange);
        g.setFont(juce::FontOptions(86.f, juce::Font::bold));
        g.drawText(name.isEmpty() ? "-" : name, in.withTrimmedBottom(22), juce::Justification::centred);
        g.setColour(sink);
        g.setFont(juce::FontOptions(14.f));
        juce::String sub = proc.chordRoman();
        int ready = proc.soundsReady(), want = proc.soundsWanted();
        if (ready < want) sub += (sub.isEmpty() ? "" : "   ") + juce::String("making the sound: ") + juce::String(ready) + " / " + juce::String(want) + " notes";
        if (sub.isEmpty()) sub = tab == 0 ? "play a pad, or chords from your MIDI keyboard"
                               : (tab == 1 ? "play a pad, or your MIDI keyboard: one note at a time"
                                           : "tap a pad or key to drone on it, again to stop. Mod wheel pulses, bend thins or blooms");
        g.drawText(sub, in.removeFromBottom(20), juce::Justification::centred);
    }
}

void BricklabStudioEditor::resized() {
    auto bar = getLocalBounds().removeFromTop(56).withTrimmedLeft(240).reduced(0, 11);
    for (auto* t : tabs) { t->setBounds(bar.removeFromLeft(96)); bar.removeFromLeft(6); }
    soon.setBounds(60, 90, getWidth() - 120, 140);
    auto r = getLocalBounds().withTrimmedTop(260).reduced(22, 0);
    auto padRow = r.removeFromTop(110);
    int w = (padRow.getWidth() - 6 * 8) / 7;
    for (int i = 0; i < pads.size(); ++i) pads[i]->setBounds(padRow.getX() + i * (w + 8), padRow.getY(), w, padRow.getHeight());
    r.removeFromTop(14);
    auto modRow = r.removeFromTop(34);
    for (auto* b : modButtons) { b->setBounds(modRow.removeFromLeft(86)); modRow.removeFromLeft(8); }
    modRow.removeFromLeft(16);
    latch.setBounds(modRow.removeFromLeft(86));
    third.setBounds(22, modRow.getY(), 86, modRow.getHeight());
    r.removeFromTop(16);
    auto row = r.removeFromTop(30);
    sound.setBounds(row.removeFromLeft(240)); row.removeFromLeft(10);
    leadSound.setBounds(sound.getBounds());
    droneSound.setBounds(sound.getBounds());
    key.setBounds(row.removeFromLeft(80)); row.removeFromLeft(10);
    scale.setBounds(row.removeFromLeft(130)); row.removeFromLeft(18);
    spaceL.setBounds(row.removeFromLeft(56)); space.setBounds(row.removeFromLeft(120)); row.removeFromLeft(10);
    volumeL.setBounds(row.removeFromLeft(62)); volume.setBounds(row.removeFromLeft(120));
    layoutRows();
}

void BricklabStudioEditor::layoutRows() {           // the bottom row: what this page sets
    auto outRow = juce::Rectangle<int>(22, 260 + 110 + 14 + 34 + 16 + 30 + 14, getWidth() - 44, 30);
    if (tab == 0) {
        modeL.setBounds(outRow.removeFromLeft(38)); mode.setBounds(outRow.removeFromLeft(180)); outRow.removeFromLeft(14);
        arpL.setBounds(outRow.removeFromLeft(34)); arpOct.setBounds(outRow.removeFromLeft(84)); outRow.removeFromLeft(14);
        bassL.setBounds(outRow.removeFromLeft(40)); bassMode.setBounds(outRow.removeFromLeft(130)); outRow.removeFromLeft(8);
        bassLvl.setBounds(outRow.removeFromLeft(100));
    } else if (tab == 1) {
        octL.setBounds(outRow.removeFromLeft(56)); octave.setBounds(outRow.removeFromLeft(100)); outRow.removeFromLeft(18);
        glideL.setBounds(outRow.removeFromLeft(46)); leadGlide.setBounds(outRow.removeFromLeft(180));
    } else if (tab == 2) {
        octL.setBounds(outRow.removeFromLeft(56)); octave.setBounds(outRow.removeFromLeft(96)); outRow.removeFromLeft(12);
        slideL.setBounds(outRow.removeFromLeft(42)); droneSlide.setBounds(outRow.removeFromLeft(120)); outRow.removeFromLeft(12);
        pulseL.setBounds(outRow.removeFromLeft(96)); droneY.setBounds(outRow.removeFromLeft(110)); outRow.removeFromLeft(10);
        bloomL.setBounds(outRow.removeFromLeft(90)); droneX.setBounds(outRow.removeFromLeft(110));
    }
    outNote.setBounds(outRow);
}

void BricklabStudioEditor::timerCallback() {
    if (proc.page() != tab) showTab(proc.page());       // the host changed it (automation, a preset)
    if (tab == 2 && proc.droneDegree() != litDrone) {   // the pad that's droning stays lit
        litDrone = proc.droneDegree();
        for (int d = 0; d < pads.size(); ++d) { pads[d]->lit = d == litDrone; pads[d]->repaint(); }
    }
    auto names = proc.padNames();
    for (int d = 0; d < pads.size(); ++d) {
        auto parts = juce::StringArray::fromLines(names[(size_t) d]);
        if (pads[d]->top != parts[0] || pads[d]->sub != parts[1]) {
            pads[d]->top = parts[0];
            pads[d]->sub = juce::String(d + 1) + "  " + parts[1];
            pads[d]->repaint();
        }
    }
    repaint(0, 56, getWidth(), 200);
}

// the computer keyboard plays the pads too: 1 to 7, or A to J (as on Bricklab web)
static int padForKey(int code) {
    const juce::String keys1 = "1234567", keys2 = "ASDFGHJ";
    int i = keys1.indexOfChar((juce::juce_wchar) code);
    if (i < 0) i = keys2.indexOfChar((juce::juce_wchar) juce::CharacterFunctions::toUpperCase((juce::juce_wchar) code));
    return i;
}

bool BricklabStudioEditor::keyPressed(const juce::KeyPress& k) {
    int d = padForKey(k.getKeyCode());
    if (d < 0 || tab > 2) return false;
    if (d != keyDown) {
        if (keyDown >= 0) {
            pads[keyDown]->lit = false; pads[keyDown]->repaint();
            if (tab == 0) proc.padsDown = std::max(0, proc.padsDown - 1);   // the chord just moves on
            else padPress(keyDown, false);
        }
        keyDown = d;
        if (tab != 2) { pads[d]->lit = true; pads[d]->repaint(); }
        padPress(d, true);
    }
    return true;
}

bool BricklabStudioEditor::keyStateChanged(bool isKeyDown) {
    if (!isKeyDown && keyDown >= 0) {
        const juce::String keys1 = "1234567", keys2 = "ASDFGHJ";
        if (!juce::KeyPress::isKeyCurrentlyDown(keys1[keyDown]) && !juce::KeyPress::isKeyCurrentlyDown(keys2[keyDown])
            && !juce::KeyPress::isKeyCurrentlyDown(juce::CharacterFunctions::toLowerCase(keys2[keyDown]))) {
            if (tab != 2) { pads[keyDown]->lit = false; pads[keyDown]->repaint(); }
            const int k = keyDown;
            keyDown = -1;
            padPress(k, false);
            return true;
        }
    }
    return false;
}
