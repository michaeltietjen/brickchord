#include "PluginEditor.h"
#include "core/PatchData.h"

namespace {
constexpr int kW = 900, kH = 560;                         // the page's own size; the window scales it
const juce::Colour chassis(0xffe4e2dc), plate(0xffefede8), ink(0xff18161c), dim(0xff6d6874),
    seam(0xffcfccc4), orange(0xffff5a1f), screen(0xff121016), sink(0xffece4d6), teal(0xff3f9e95);
const char* TAB_NAMES[] = {"Chord", "Lead", "Drone", "Glide"};    // by page; Lead stays in the engine, off the tabs
const int TAB_PAGES[] = {3, 0, 2};
const char* SOON[] = {"", "", "", ""};
const juce::Colour VCOL[] = {juce::Colour(110, 200, 190), juce::Colour(190, 140, 255), juce::Colour(255, 170, 110),
                             juce::Colour(120, 200, 140), juce::Colour(255, 120, 160), juce::Colour(140, 170, 255)};
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

void DragMidi::paint(juce::Graphics& g) {
    const bool on = ready && ready();
    auto r = getLocalBounds().toFloat().reduced(1);
    g.setColour(juce::Colour(0xff26242b));
    g.fillRoundedRectangle(r, 6);
    g.setColour(on ? orange : juce::Colour(0xff6d6874));
    g.drawRoundedRectangle(r, 6, 1.2f);
    g.setFont(juce::FontOptions(13.f));
    g.drawText(on ? "drag MIDI" : "play, then drag", r.toNearestInt(), juce::Justification::centred);
}

void DragMidi::mouseDrag(const juce::MouseEvent&) {
    if (dragging || !make) return;
    auto f = make();
    if (!f.existsAsFile()) return;
    dragging = true;
    juce::DragAndDropContainer::performExternalDragDropOfFiles({f.getFullPathName()}, false, this, [this] { dragging = false; });
}

BricklabStudioEditor::BricklabStudioEditor(BricklabStudioProcessor& p) : AudioProcessorEditor(&p), proc(p) {
    for (int k = 0; k < 3; ++k) {                         // Glide first: it's what this plugin is for
        const int t = TAB_PAGES[k];
        auto* b = tabs.add(new juce::TextButton(TAB_NAMES[t]));
        b->setClickingTogglesState(false);
        b->onClick = [this, t] {                             // the page is the instance's: saved with the project
            if (auto* p = proc.params.getParameter("page")) p->setValueNotifyingHost(p->convertTo0to1((float) t));
            showTab(t);
        };
        addAndMakeVisible(b);
    }
    for (int i = 0; i < proc.getNumPrograms(); ++i) presetBox.addItem(proc.getProgramName(i), i + 1);
    presetBox.setTextWhenNothingSelected("Presets");
    presetBox.onChange = [this] {
        const int i = presetBox.getSelectedItemIndex();
        if (i >= 0) { proc.setCurrentProgram(i); proc.updateHostDisplay(); showTab(proc.page()); }
    };
    addAndMakeVisible(presetBox);
    dragMidi.make = [this] { return proc.writePhrase(); };
    dragMidi.ready = [this] { return proc.hasPhrase(); };
    addAndMakeVisible(dragMidi);
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
        static const char* ids[] = {"mod7", "modsus", "mod9", "modflip"};
        modAttach.add(new juce::AudioProcessorValueTreeState::ButtonAttachment(proc.params, ids[i], *b));
        addAndMakeVisible(b);
    }
    latch.setClickingTogglesState(true);
    addAndMakeVisible(latch);
    third.setClickingTogglesState(true);
    addAndMakeVisible(third);
    // the Glide page
    for (int i : BricklabStudioProcessor::glideSounds()) glideSound.addItem(brick::kPatches[i].name, glideSound.getNumItems() + 1);
    for (int i = 0; i < brick::kNumGlideChords; ++i) glideChord.addItem(brick::kGlideChords[i], i + 1);
    for (int i = 0; i < brick::kNumGlidePaths; ++i) glidePath.addItem(juce::String("Path: ") + brick::kGlidePaths[i], i + 1);
    for (int i = 0; i < brick::kNumGlideTimings; ++i) glideTiming.addItem(juce::String("Timing: ") + brick::kGlideTimings[i], i + 1);
    for (int i = 0; i < brick::kNumGlideMoves; ++i) glideMove.addItem(brick::kGlideMoves[i], i + 1);
    for (auto& t : brick::timeNames(brick::kGlideTimes, brick::kNumGlideTimes, "Glide")) glideTime.addItem(t, glideTime.getNumItems() + 1);
    for (auto& t : brick::timeNames(brick::kGlideFades, brick::kNumGlideFades, "Fade")) glideFade.addItem(t, glideFade.getNumItems() + 1);
    for (int i = 0; i < brick::kNumGlideBends; ++i) glideBend.addItem("Bend " + juce::String(brick::kGlideBends[i]) + " st", i + 1);
    glideMpe.addItemList({"Out: MPE", "Out: notes", "Out: MPE + pressure"}, 1);
    for (auto* c : {&glideSound, &glideChord, &glidePath, &glideTiming, &glideMove, &glideTime, &glideFade, &glideBend, &glideMpe})
        addAndMakeVisible(c);
    glideSub.setClickingTogglesState(true);
    bloomBtn.onClick = [this] { proc.uiPad(101, true); };
    stopBtn.onClick = [this] { proc.uiPad(100, true); };
    // the MPE editor: the curves a glide follows, and what drives pressure and timbre
    curveEd = std::make_unique<CurveEditor>(proc.glide, proc.params);
    addChildComponent(*curveEd);
    curvesBtn.setClickingTogglesState(true);
    curvesBtn.onClick = [this] { if (curvesBtn.getToggleState()) glideMore.setToggleState(false, juce::dontSendNotification); showTab(tab); };
    addAndMakeVisible(curvesBtn);
    for (int i = 0; i < brick::kNumPressureSources; ++i) prSrc.addItem(brick::kPressureSources[i], i + 1);
    for (int i = 0; i < brick::kNumTimbreSources; ++i) tbSrc.addItem(brick::kTimbreSources[i], i + 1);
    for (auto* c : {&prSrc, &tbSrc}) addAndMakeVisible(c);
    for (auto* s : {&prDepth, &tbDepth, &lfoRate}) {
        s->setSliderStyle(juce::Slider::LinearHorizontal);
        s->setTextBoxStyle(juce::Slider::NoTextBox, false, 0, 0);
        addAndMakeVisible(s);
    }
    prL.setText("Pressure", juce::dontSendNotification);
    tbL.setText("Timbre", juce::dontSendNotification);
    lfoL.setText("LFO", juce::dontSendNotification);
    for (auto* l : {&prL, &tbL, &lfoL}) { l->setColour(juce::Label::textColourId, dim); addAndMakeVisible(l); }
    glideMore.setClickingTogglesState(true);                 // the plumbing (timing, bend range, MIDI out) behind "more"
    glideMore.onClick = [this] { if (glideMore.getToggleState()) curvesBtn.setToggleState(false, juce::dontSendNotification); showTab(tab); };
    for (auto* b : {&bloomBtn, &stopBtn, &glideSub, &glideMore}) addAndMakeVisible(b);
    glideTone.setSliderStyle(juce::Slider::LinearHorizontal);
    glideTone.setTextBoxStyle(juce::Slider::NoTextBox, false, 0, 0);
    addAndMakeVisible(glideTone);
    glideToneL.setText("Tone", juce::dontSendNotification);
    glideToneL.setColour(juce::Label::textColourId, dim);
    addAndMakeVisible(glideToneL);
    glideChordL.setText("Chord", juce::dontSendNotification);
    glideChordL.setColour(juce::Label::textColourId, dim);
    addAndMakeVisible(glideChordL);
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
    for (int i = 0; i < brick::kNumScales; ++i) scale.addItem(brick::kScaleNames[i], i + 1);
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
    using CA = juce::AudioProcessorValueTreeState::ComboBoxAttachment;
    aGlideSound = std::make_unique<CA>(ps, "glidesound", glideSound);
    aGlideChord = std::make_unique<CA>(ps, "glidechord", glideChord);
    aGlidePath = std::make_unique<CA>(ps, "glidepath", glidePath);
    aGlideTiming = std::make_unique<CA>(ps, "glidetiming", glideTiming);
    aGlideMove = std::make_unique<CA>(ps, "glidemove", glideMove);
    aGlideTime = std::make_unique<CA>(ps, "glidetime", glideTime);
    aGlideFade = std::make_unique<CA>(ps, "glidefade", glideFade);
    aGlideBend = std::make_unique<CA>(ps, "glidebend", glideBend);
    aGlideMpe = std::make_unique<CA>(ps, "glidempe", glideMpe);
    aPrSrc = std::make_unique<CA>(ps, "glideprsrc", prSrc);
    aTbSrc = std::make_unique<CA>(ps, "glidetbsrc", tbSrc);
    aPrDepth = std::make_unique<juce::AudioProcessorValueTreeState::SliderAttachment>(ps, "glideprdepth", prDepth);
    aTbDepth = std::make_unique<juce::AudioProcessorValueTreeState::SliderAttachment>(ps, "glidetbdepth", tbDepth);
    aLfoRate = std::make_unique<juce::AudioProcessorValueTreeState::SliderAttachment>(ps, "glidelfo", lfoRate);
    aGlideTone = std::make_unique<juce::AudioProcessorValueTreeState::SliderAttachment>(ps, "glidetone", glideTone);
    aGlideSub = std::make_unique<juce::AudioProcessorValueTreeState::ButtonAttachment>(ps, "glidesub", glideSub);
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
    canvas.painter = [this](juce::Graphics& g) { paintContent(g); };
    std::vector<juce::Component*> kids;                     // everything lives on the canvas, which scales
    for (auto* c : getChildren()) kids.push_back(c);
    addAndMakeVisible(canvas);
    for (auto* c : kids) { const bool v = c->isVisible(); canvas.addChildComponent(c); c->setVisible(v); }
    setResizable(true, true);
    setResizeLimits(kW * 3 / 4, kH * 3 / 4, kW * 2, kH * 2);
    if (auto* k = getConstrainer()) k->setFixedAspectRatio((double) kW / kH);
    setSize(kW, kH);
    showTab(proc.page());
    startTimerHz(15);
}

BricklabStudioEditor::~BricklabStudioEditor() { stopTimer(); releaseKey(); }

void BricklabStudioEditor::releaseKey() {                 // a computer key held when the page loses focus or closes
    if (keyDown < 0) return;
    const int k = keyDown;
    keyDown = -1;
    if (k < pads.size()) { pads[k]->lit = false; pads[k]->repaint(); }
    padPress(k, false);
}

void BricklabStudioEditor::showTab(int t) {
    tab = t;
    for (int i = 0; i < tabs.size(); ++i) tabs[i]->setToggleState(TAB_PAGES[i] == t, juce::dontSendNotification);
    const bool chord = t == 0, lead = t == 1, drone = t == 2, gl = t == 3, playing = true, sounds = !proc.kMidiFx;
    auto show = [](std::initializer_list<juce::Component*> cs, bool on) { for (auto* c : cs) c->setVisible(on); };
    const bool curves = gl && curvesBtn.getToggleState();   // the MPE editor takes the screen and the pads' place
    for (auto* p : pads) p->setVisible(playing && !curves);
    curveEd->setVisible(curves);
    curvesBtn.setVisible(gl);
    show({&prSrc, &tbSrc, &prDepth, &tbDepth, &lfoRate, &prL, &tbL, &lfoL}, curves);
    for (auto* b : modButtons) b->setVisible(chord);
    latch.setVisible(chord);
    show({&sound, &bassLvl}, chord && sounds);
    show({&leadSound}, lead && sounds);
    show({&droneSound}, drone && sounds);
    show({&key, &scale}, playing);
    show({&space, &volume, &spaceL, &volumeL}, playing && sounds);
    show({&mode, &arpOct, &bassMode, &modeL, &arpL, &bassL}, chord);
    show({&octave, &octL}, !gl);
    show({&glideSound}, gl && sounds);
    const bool more = glideMore.getToggleState();
    show({&glideChord, &glideChordL, &bloomBtn, &stopBtn, &glideSub, &glideMore}, gl);
    show({&glideTone, &glideToneL}, gl && sounds);
    show({&glidePath, &glideMove, &glideTime, &glideFade}, gl && !more && !curves);
    show({&glideTiming, &glideBend}, gl && more);
    show({&glideMpe}, gl && more && proc.kMidiFx);
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
        if (down) { ++proc.padsDown; proc.uiPad(d, true); }      // played on the audio thread, in order
        else { proc.padsDown = std::max(0, proc.padsDown - 1); proc.uiPad(d, false); }
    } else if (pg == 1 || ((pg == 2 || pg == 3) && down))
        proc.uiPad(d, down);
}

void BricklabStudioEditor::paint(juce::Graphics& g) { g.fillAll(chassis); }

void BricklabStudioEditor::paintContent(juce::Graphics& g) {   // drawn at 900 x 560, scaled to the window
    g.fillAll(chassis);
    auto r = juce::Rectangle<int>(0, 0, kW, kH);
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
    auto scr = juce::Rectangle<int>(22, 72, kW - 44, 170);
    g.setColour(juce::Colour(0xff26242b));
    g.fillRoundedRectangle(scr.toFloat(), 16);
    g.setColour(screen);
    g.fillRoundedRectangle(scr.toFloat().reduced(7), 11);
    auto in = scr.reduced(22, 16);
    g.setColour(juce::Colour(0xffa39fae));
    g.setFont(juce::FontOptions(13.f));
    auto top = in.removeFromTop(18);
    g.drawText((key.getText() + " " + scale.getText()).toUpperCase(), top, juce::Justification::centredLeft);
    auto* sc = tab == 0 ? &sound : (tab == 1 ? &leadSound : (tab == 2 ? &droneSound : &glideSound));
    g.drawText(TAB_NAMES[tab] + juce::String("  ") + (!proc.kMidiFx ? sc->getText().toUpperCase() : ""), top, juce::Justification::centredRight);
    if (tab == 3) {                                       // the voices' paths over the last 10 seconds, as on the Brick
        auto area = in.toFloat().withTrimmedBottom(4).withTrimmedRight(26);   // the paths, full width; where they head, at the right
        float lo = 1e9f, hi = -1e9f;                       // the range the voices used, with room around it
        for (auto& tv : trail) for (float c : tv) if (c > 0) { lo = std::min(lo, c); hi = std::max(hi, c); }
        for (int v = 0; v < 6; ++v) if (proc.glide.on[(size_t) v]) { float t = proc.glide.target[(size_t) v]; lo = std::min(lo, t); hi = std::max(hi, t); }
        if (lo > hi) { lo = 3600; hi = 7200; }
        lo -= 300; hi += 300;
        if (hi - lo < 2400) { float m = (hi + lo) / 2; lo = m - 1200; hi = m + 1200; }
        auto y = [&](float cents) { return area.getBottom() - (cents - lo) / (hi - lo) * area.getHeight(); };
        for (int v = 0; v < 6; ++v) {
            juce::Path p;
            bool started = false;
            for (int k = 0; k < 150; ++k) {
                float c = trail[(size_t) v][(size_t) ((trailAt + k) % 150)];
                float x = area.getX() + area.getWidth() * (float) k / 149.0f;
                if (c <= 0) { started = false; continue; }
                if (!started) { p.startNewSubPath(x, y(c)); started = true; } else p.lineTo(x, y(c));
            }
            g.setColour(VCOL[v].withAlpha(0.35f + 0.65f * juce::jlimit(0.0f, 1.0f, trailLvl[(size_t) v] / 0.6f)));
            g.strokePath(p, juce::PathStrokeType(2.6f));
            if (proc.glide.on[(size_t) v]) {                 // where the voice is going: a dot, and its note
                const float ty = y(proc.glide.target[(size_t) v]);
                g.fillEllipse(area.getRight() + 6, ty - 4, 8, 8);
            }
        }
        g.setColour(juce::Colour(0xcc121016));               // the name sits on the paths, legible
        g.fillRoundedRectangle(in.toFloat().withWidth(260).withHeight(56).translated(-6, 2), 8);
        auto name = proc.chordName();
        g.setColour(orange);
        g.setFont(juce::FontOptions(40.f, juce::Font::bold));
        g.drawText(name.isEmpty() ? "" : name, in.withWidth(250).withTrimmedTop(4).withHeight(52), juce::Justification::centredLeft);
        g.setColour(sink);
        g.setFont(juce::FontOptions(14.f));
        int ready = proc.soundsReady(), want = proc.soundsWanted();
        juce::String sub = ready < want ? "making the sound: " + juce::String(ready) + " / " + juce::String(want) + " notes"
                                        : (name.isEmpty() ? "play a pad or chords: the voices glide from one to the next. Mod wheel stretches, bend bends" : "");
        g.drawText(sub, scr.reduced(22, 16).removeFromBottom(20), juce::Justification::centred);
    }
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

void BricklabStudioEditor::resized() {                     // any size: the whole page scales, keeping its shape
    canvas.setBounds(0, 0, kW, kH);
    canvas.setTransform(juce::AffineTransform::scale((float) getWidth() / (float) kW));
    layout();
}

void BricklabStudioEditor::layout() {
    auto bar = juce::Rectangle<int>(0, 0, kW, kH).removeFromTop(56).withTrimmedLeft(240).reduced(0, 11);
    for (auto* t : tabs) { t->setBounds(bar.removeFromLeft(96)); bar.removeFromLeft(6); }
    bar.removeFromLeft(14);
    presetBox.setBounds(bar.removeFromLeft(190));
    bar.removeFromLeft(10);
    dragMidi.setBounds(bar.removeFromLeft(120));
    soon.setBounds(60, 90, kW - 120, 140);
    auto r = juce::Rectangle<int>(0, 0, kW, kH).withTrimmedTop(260).reduced(22, 0);
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
    glideSound.setBounds(sound.getBounds());
    droneSound.setBounds(sound.getBounds());
    key.setBounds(row.removeFromLeft(80)); row.removeFromLeft(10);
    scale.setBounds(row.removeFromLeft(130)); row.removeFromLeft(18);
    spaceL.setBounds(row.removeFromLeft(56)); space.setBounds(row.removeFromLeft(120)); row.removeFromLeft(10);
    volumeL.setBounds(row.removeFromLeft(62)); volume.setBounds(row.removeFromLeft(120));
    layoutRows();
}

void BricklabStudioEditor::layoutRows() {           // the bottom row: what this page sets
    auto outRow = juce::Rectangle<int>(22, 260 + 110 + 14 + 34 + 16 + 30 + 14, kW - 44, 30);
    if (tab == 0) {                                   // the chord's octave sits by latch
        octL.setBounds(520, 260 + 110 + 14, 56, 34); octave.setBounds(576, 260 + 110 + 16, 96, 30);
        modeL.setBounds(outRow.removeFromLeft(38)); mode.setBounds(outRow.removeFromLeft(180)); outRow.removeFromLeft(14);
        arpL.setBounds(outRow.removeFromLeft(34)); arpOct.setBounds(outRow.removeFromLeft(84)); outRow.removeFromLeft(14);
        bassL.setBounds(outRow.removeFromLeft(40)); bassMode.setBounds(outRow.removeFromLeft(130)); outRow.removeFromLeft(8);
        bassLvl.setBounds(outRow.removeFromLeft(100));
    } else if (tab == 1) {
        octL.setBounds(outRow.removeFromLeft(56)); octave.setBounds(outRow.removeFromLeft(100)); outRow.removeFromLeft(18);
        glideL.setBounds(outRow.removeFromLeft(46)); leadGlide.setBounds(outRow.removeFromLeft(180));
    } else if (tab == 3) {
        auto mod = juce::Rectangle<int>(22, 260 + 110 + 14, kW - 44, 34);
        bloomBtn.setBounds(mod.removeFromLeft(86)); mod.removeFromLeft(8);
        stopBtn.setBounds(mod.removeFromLeft(86)); mod.removeFromLeft(20);
        glideChordL.setBounds(mod.removeFromLeft(48)); glideChord.setBounds(mod.removeFromLeft(140).reduced(0, 2)); mod.removeFromLeft(10);
        glideSub.setBounds(mod.removeFromLeft(70));
        glideMore.setBounds(mod.removeFromRight(86)); mod.removeFromRight(8);
        curvesBtn.setBounds(mod.removeFromRight(86)); mod.removeFromRight(12);
        curveEd->setBounds(22, 72, kW - 44, 298);
        {
            auto rt = outRow;                                // the routing, under the editor
            prL.setBounds(rt.removeFromLeft(66)); prSrc.setBounds(rt.removeFromLeft(150)); rt.removeFromLeft(6);
            prDepth.setBounds(rt.removeFromLeft(90)); rt.removeFromLeft(16);
            tbL.setBounds(rt.removeFromLeft(54)); tbSrc.setBounds(rt.removeFromLeft(150)); rt.removeFromLeft(6);
            tbDepth.setBounds(rt.removeFromLeft(90)); rt.removeFromLeft(16);
            lfoL.setBounds(rt.removeFromLeft(36)); lfoRate.setBounds(rt.removeFromLeft(110));
        }
        glideTone.setBounds(mod.removeFromRight(120)); glideToneL.setBounds(mod.removeFromRight(42));
        auto adv = outRow;
        glideTime.setBounds(outRow.removeFromLeft(150)); outRow.removeFromLeft(10);
        glidePath.setBounds(outRow.removeFromLeft(190)); outRow.removeFromLeft(10);
        glideMove.setBounds(outRow.removeFromLeft(170)); outRow.removeFromLeft(10);
        glideFade.setBounds(outRow.removeFromLeft(150));
        glideTiming.setBounds(adv.removeFromLeft(200)); adv.removeFromLeft(10);
        glideBend.setBounds(adv.removeFromLeft(130)); adv.removeFromLeft(10);
        glideMpe.setBounds(adv.removeFromLeft(140));
    } else if (tab == 2) {
        octL.setBounds(outRow.removeFromLeft(56)); octave.setBounds(outRow.removeFromLeft(96)); outRow.removeFromLeft(12);
        slideL.setBounds(outRow.removeFromLeft(42)); droneSlide.setBounds(outRow.removeFromLeft(120)); outRow.removeFromLeft(12);
        pulseL.setBounds(outRow.removeFromLeft(96)); droneY.setBounds(outRow.removeFromLeft(110)); outRow.removeFromLeft(10);
        bloomL.setBounds(outRow.removeFromLeft(90)); droneX.setBounds(outRow.removeFromLeft(110));
    }
    outNote.setBounds(outRow);
}

void BricklabStudioEditor::timerCallback() {
    for (int v = 0; v < 6; ++v) {                          // the Glide trails
        const bool on = proc.glide.level[(size_t) v] > 0.01f;
        trail[(size_t) v][(size_t) trailAt] = on ? proc.glide.cents[(size_t) v].load() : 0.0f;
        trailLvl[(size_t) v] = proc.glide.level[(size_t) v];
    }
    trailAt = (trailAt + 1) % 150;
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
    canvas.repaint(0, 56, kW, 200);
    if (curveEd->isVisible()) curveEd->repaint();
    dragMidi.repaint();
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
    if (d < 0) return false;
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
