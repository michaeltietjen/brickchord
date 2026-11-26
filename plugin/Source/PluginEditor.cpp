#include "PluginEditor.h"
#include "core/PatchData.h"

namespace {
constexpr int kW = 900, kH = 590;                         // the page's own size; the window scales it
constexpr int kPadTop = 312, kPadH = 96;                  // the pads sit under the screen
// the dark studio palette
const juce::Colour chassis(0xff07060c), panel(0xff12111a), plate(0xff211f2e), ink(0xffecebf3), dim(0xff9d9ab0),
    seam(0xff37344a), orange(0xffb9a6ff) /* the accent: violet now */, screen(0xff07060c), sink(0xffecebf3), teal(0xff3f9e95);
const char* TAB_NAMES[] = {"Chord", "Lead", "Drone", "Glide"};    // by page; Lead stays in the engine, off the tabs
const int TAB_PAGES[] = {3, 0, 2};
const char* SOON[] = {"", "", "", ""};
// one colour per chord of the scale (pads 1 to 7)
const juce::Colour CCOL[] = {juce::Colour(0xffb9a6ff), juce::Colour(0xff6ec8be), juce::Colour(0xffffc46b), juce::Colour(0xff78a0ff),
                             juce::Colour(0xffff7896), juce::Colour(0xff8cd278), juce::Colour(0xffffaa6e)};
static juce::String chordRoot(const juce::String& s) {    // "F#m7" gives "F#"
    int n = s.isEmpty() ? 0 : 1;
    while (n < s.length() && (s[n] == '#' || s[n] == 'b' || s[n] == 0x266f || s[n] == 0x266d)) ++n;
    return s.substring(0, n);
}
const juce::Colour VCOL[] = {juce::Colour(110, 200, 190), juce::Colour(190, 140, 255), juce::Colour(255, 170, 110),
                             juce::Colour(120, 200, 140), juce::Colour(255, 120, 160), juce::Colour(140, 170, 255)};
}

void Pad::paint(juce::Graphics& g) {
    auto r = getLocalBounds().toFloat().reduced(2);
    const juce::Colour hue = tint.isTransparent() ? orange : tint;
    if (lit) {
        g.setColour(hue.withAlpha(0.25f));
        g.fillRoundedRectangle(r.expanded(2), 14);
        g.setGradientFill(juce::ColourGradient(hue.brighter(0.15f), 0, r.getY(), hue.darker(0.15f), 0, r.getBottom(), false));
    } else
        g.setColour(juce::Colours::white.withAlpha(0.05f));
    g.fillRoundedRectangle(r, 12);
    g.setColour(lit ? hue.brighter(0.4f) : seam);
    g.drawRoundedRectangle(r, 12, 1.0f);
    if (!lit && !tint.isTransparent()) {                   // a stripe in its chord's colour
        g.setColour(tint);
        g.fillRoundedRectangle(r.getCentreX() - 14, r.getBottom() - 7, 28, 3, 1.5f);
    }
    g.setColour(juce::Colours::white.withAlpha(lit ? 0.25f : 0.05f));     // a light edge along the top
    g.drawLine(r.getX() + 12, r.getY() + 1, r.getRight() - 12, r.getY() + 1, 1.0f);
    g.setColour(lit ? chassis : ink);
    g.setFont(juce::FontOptions(17.f, juce::Font::bold));
    g.drawFittedText(top, r.withTrimmedBottom(r.getHeight() * 0.40f).toNearestInt(), juce::Justification::centredBottom, 1);
    g.setColour(lit ? chassis.withAlpha(0.75f) : dim);
    g.setFont(juce::FontOptions(10.5f));
    g.drawFittedText(sub, r.withTrimmedTop(r.getHeight() * 0.62f).toNearestInt(), juce::Justification::centredTop, 1);
}

// ---------------------------------------------------------------- the look: dark, flat, one accent
BrickLook::BrickLook() {
    setColour(juce::TextButton::buttonColourId, plate);
    setColour(juce::TextButton::buttonOnColourId, orange);
    setColour(juce::TextButton::textColourOffId, ink);
    setColour(juce::TextButton::textColourOnId, chassis);
    setColour(juce::ComboBox::backgroundColourId, plate);
    setColour(juce::ComboBox::textColourId, ink);
    setColour(juce::ComboBox::outlineColourId, seam);
    setColour(juce::ComboBox::arrowColourId, dim);
    setColour(juce::PopupMenu::backgroundColourId, juce::Colour(0xff17171e));
    setColour(juce::PopupMenu::textColourId, ink);
    setColour(juce::PopupMenu::headerTextColourId, dim);
    setColour(juce::PopupMenu::highlightedBackgroundColourId, orange);
    setColour(juce::PopupMenu::highlightedTextColourId, chassis);
    setColour(juce::Label::textColourId, dim);
    setColour(juce::Slider::thumbColourId, ink);
    setColour(juce::Slider::trackColourId, orange);
    setColour(juce::Slider::backgroundColourId, seam);
}

void BrickLook::drawButtonBackground(juce::Graphics& g, juce::Button& b, const juce::Colour&, bool over, bool down) {
    auto r = b.getLocalBounds().toFloat().reduced(0.5f);
    const bool on = b.getToggleState();
    juce::Colour c = on ? orange : plate;
    if (down) c = c.brighter(0.12f); else if (over) c = c.brighter(0.06f);
    g.setColour(c);
    g.fillRoundedRectangle(r, 8);
    g.setColour(on ? orange.brighter(0.3f) : seam);
    g.drawRoundedRectangle(r, 8, 1.0f);
}

juce::Font BrickLook::getTextButtonFont(juce::TextButton&, int) { return juce::FontOptions(13.5f); }
juce::Font BrickLook::getComboBoxFont(juce::ComboBox&) { return juce::FontOptions(13.5f); }
juce::Font BrickLook::getPopupMenuFont() { return juce::FontOptions(14.f); }

void BrickLook::drawComboBox(juce::Graphics& g, int w, int h, bool, int, int, int, int, juce::ComboBox& box) {
    auto r = juce::Rectangle<float>(0, 0, (float) w, (float) h).reduced(0.5f);
    g.setColour(box.isMouseOver(true) ? plate.brighter(0.06f) : plate);
    g.fillRoundedRectangle(r, 8);
    g.setColour(seam);
    g.drawRoundedRectangle(r, 8, 1.0f);
    juce::Path p;                                           // a chevron
    const float cx = (float) w - 15, cy = (float) h * 0.5f;
    p.startNewSubPath(cx - 4, cy - 2); p.lineTo(cx, cy + 2); p.lineTo(cx + 4, cy - 2);
    g.setColour(dim);
    g.strokePath(p, juce::PathStrokeType(1.6f, juce::PathStrokeType::curved, juce::PathStrokeType::rounded));
}

void BrickLook::drawLinearSlider(juce::Graphics& g, int x, int y, int w, int h, float pos, float, float,
                                 juce::Slider::SliderStyle, juce::Slider& s) {
    const float cy = (float) y + (float) h * 0.5f;
    g.setColour(seam);
    g.fillRoundedRectangle((float) x, cy - 2, (float) w, 4, 2);
    const bool bipolar = s.getMinimum() < 0;                // from the centre, for the two-way ones
    const float from = bipolar ? (float) x + (float) w * 0.5f : (float) x;
    g.setColour(orange);
    g.fillRoundedRectangle(std::min(from, pos), cy - 2, std::abs(pos - from), 4, 2);
    g.setColour(chassis);
    g.fillEllipse(pos - 7, cy - 7, 14, 14);
    g.setColour(ink);
    g.fillEllipse(pos - 5, cy - 5, 10, 10);
}

void BrickLook::drawRotarySlider(juce::Graphics& g, int x, int y, int w, int h, float pos, float a0, float a1, juce::Slider& s) {
    auto area = juce::Rectangle<float>((float) x, (float) y, (float) w, (float) h);
    auto label = area.removeFromBottom(16);
    const float rad = std::min(area.getWidth(), area.getHeight()) * 0.5f - 5, cx = area.getCentreX(), cy = area.getCentreY();
    const float ang = a0 + pos * (a1 - a0);
    juce::Path track, value;
    track.addCentredArc(cx, cy, rad, rad, 0, a0, a1, true);
    value.addCentredArc(cx, cy, rad, rad, 0, a0, ang, true);
    const juce::PathStrokeType st(3.5f, juce::PathStrokeType::curved, juce::PathStrokeType::rounded);
    g.setColour(seam);
    g.strokePath(track, st);
    g.setColour(orange.withAlpha(0.25f));
    g.strokePath(value, juce::PathStrokeType(8.0f, juce::PathStrokeType::curved, juce::PathStrokeType::rounded));
    g.setColour(orange);
    g.strokePath(value, st);
    const float kr = rad - 7;                               // the cap
    g.setGradientFill(juce::ColourGradient(juce::Colour(0xff34343f), cx, cy - kr, juce::Colour(0xff1b1b22), cx, cy + kr, false));
    g.fillEllipse(cx - kr, cy - kr, kr * 2, kr * 2);
    g.setColour(juce::Colours::black.withAlpha(0.5f));
    g.drawEllipse(cx - kr, cy - kr, kr * 2, kr * 2, 1.0f);
    g.setColour(ink);
    g.drawLine(cx + std::sin(ang) * kr * 0.35f, cy - std::cos(ang) * kr * 0.35f, cx + std::sin(ang) * kr * 0.85f, cy - std::cos(ang) * kr * 0.85f, 2.2f);
    g.setColour(s.isMouseOverOrDragging() ? ink : dim);
    g.setFont(juce::FontOptions(10.5f));
    g.drawText(s.isMouseOverOrDragging() ? juce::String(juce::roundToInt(s.getValue() * 100)) : s.getName().toUpperCase(), label, juce::Justification::centred);
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
    for (int i = 0; i < brick::kNumGlideCrossings; ++i) glideCross.addItem(brick::kGlideCrossings[i], i + 1);
    for (auto& t : brick::timeNames(brick::kGlideTimes, brick::kNumGlideTimes, "Glide")) glideTime.addItem(t, glideTime.getNumItems() + 1);
    for (auto& t : brick::timeNames(brick::kGlideFades, brick::kNumGlideFades, "Fade")) glideFade.addItem(t, glideFade.getNumItems() + 1);
    for (int i = 0; i < brick::kNumGlideBends; ++i) glideBend.addItem("Bend " + juce::String(brick::kGlideBends[i]) + " st", i + 1);
    glideMpe.addItemList({"Out: MPE", "Out: notes", "Out: MPE + pressure"}, 1);
    for (auto* c : {&glideSound, &glideChord, &glidePath, &glideTiming, &glideMove, &glideCross, &glideTime, &glideFade, &glideBend, &glideMpe})
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
    aGlideCross = std::make_unique<CA>(ps, "glidecross", glideCross);
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
    glideStrike.setClickingTogglesState(true);
    addAndMakeVisible(glideStrike);
    aGlideStrike = std::make_unique<juce::AudioProcessorValueTreeState::ButtonAttachment>(ps, "glidestrike", glideStrike);
    aGlideSub = std::make_unique<juce::AudioProcessorValueTreeState::ButtonAttachment>(ps, "glidesub", glideSub);
    aLatch = std::make_unique<juce::AudioProcessorValueTreeState::ButtonAttachment>(ps, "latch", latch);
    aMode = std::make_unique<juce::AudioProcessorValueTreeState::ComboBoxAttachment>(ps, "mode", mode);
    aArpOct = std::make_unique<juce::AudioProcessorValueTreeState::ComboBoxAttachment>(ps, "arpoct", arpOct);
    aBassMode = std::make_unique<juce::AudioProcessorValueTreeState::ComboBoxAttachment>(ps, "bassmode", bassMode);
    aSpace = std::make_unique<juce::AudioProcessorValueTreeState::SliderAttachment>(ps, "space", space);
    aVolume = std::make_unique<juce::AudioProcessorValueTreeState::SliderAttachment>(ps, "volume", volume);
    aBassLvl = std::make_unique<juce::AudioProcessorValueTreeState::SliderAttachment>(ps, "basslevel", bassLvl);

    for (auto* k : {&glideTone, &space, &volume}) {          // the knobs
        k->setSliderStyle(juce::Slider::RotaryHorizontalVerticalDrag);
        k->setRotaryParameters(juce::MathConstants<float>::pi * 1.25f, juce::MathConstants<float>::pi * 2.75f, true);
        k->setMouseDragSensitivity(140);
    }
    glideTone.setName("Tone"); space.setName("Space"); volume.setName("Volume");
    setLookAndFeel(&look);
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
    startTimerHz(30);
}

BricklabStudioEditor::~BricklabStudioEditor() { stopTimer(); releaseKey(); setLookAndFeel(nullptr); }

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
    const bool more = glideMore.getToggleState();
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
    show({&octave}, !gl || (more && !curves));
    octL.setVisible(!gl);
    show({&glideSound}, gl && sounds);
    show({&glideChord, &glideChordL, &bloomBtn, &stopBtn, &glideSub, &glideMore}, gl);
    show({&glideTone, &glideToneL}, gl && sounds);
    show({&glidePath, &glideMove, &glideCross, &glideTime, &glideFade, &glideTiming, &glideBend}, gl && more && !curves);
    show({&glideMpe, &glideStrike}, gl && proc.kMidiFx);
    show({&leadGlide, &glideL}, lead);
    show({&third, &droneSlide, &slideL, &droneY, &droneX, &pulseL, &bloomL}, drone);
    outNote.setText(chord ? (proc.kMidiFx ? "Chords on ch 1, bass on ch 2" : "") : (lead ? "Mod wheel: vibrato  Bend: 2 st" : ""),
                    juce::dontSendNotification);
    outNote.setVisible(chord || lead);
    for (auto* p : pads) p->lit = false;
    litDrone = -2;
    soon.setText(SOON[t], juce::dontSendNotification);
    soon.setVisible(!playing);
    layout();
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

void BricklabStudioEditor::paintContent(juce::Graphics& g) {   // drawn at 900 x 590, scaled to the window
    using namespace juce;
    const bool gl = tab == 3, sounds = !proc.kMidiFx;
    const bool rowA = !gl || glideMore.getToggleState() || curvesBtn.getToggleState();
    g.setGradientFill(ColourGradient(Colour(0xff1c1932), kW * 0.5f, 90, chassis, kW * 0.5f, 560, true));
    g.fillAll();

    // ---- the field: a floor running to a horizon. "Now" is at the front; the past recedes.
    const float cx = 440, hor = 118, K = 60, LK = 79;
    auto proj = [&](float x, float z) { const float s = 1.0f / (0.22f + z * 1.9f); return Point<float>(cx + x * LK * s, hor + K * s); };
    for (int k = 0; k <= 12; ++k) {                         // bars of time
        const float z = (float) k / 12.0f;
        auto a = proj(-1.3f, z), b = proj(1.3f, z);
        g.setColour(Colour(0xff3a3658).withAlpha(0.55f * (1 - z) * (1 - z) + 0.03f));
        g.drawLine(a.x, a.y, b.x, b.y, 1.0f);
    }
    for (int k = -6; k <= 6; ++k) {                         // lanes of pitch
        auto a = proj((float) k / 5.0f, 0), b = proj((float) k / 5.0f, 1);
        g.setGradientFill(ColourGradient(Colour(0xff3a3658).withAlpha(0.5f), a.x, a.y, Colour(0x003a3658), b.x, b.y, false));
        g.drawLine(a.x, a.y, b.x, b.y, 1.0f);
    }
    // a ribbon along the floor: xs (lateral, -1..1) and widths by age; gaps where w <= 0
    auto ribbon = [&](const std::function<bool(int, float&, float&)>& at, Colour col, const std::function<Colour(int)>& colAt = nullptr) {
        const int chunk = 6;
        for (int k0 = 0; k0 < kHist - 1; k0 += chunk) {
            std::vector<Point<float>> L, R;
            auto flush = [&] {                              // fill the run gathered so far
                if (L.size() >= 2) {
                    Path p;
                    p.startNewSubPath(L[0]);
                    for (size_t i = 1; i < L.size(); ++i) p.lineTo(L[i]);
                    for (size_t i = R.size(); i-- > 0;) p.lineTo(R[i]);
                    p.closeSubPath();
                    const float z = (float) k0 / (kHist - 1);
                    g.setColour((colAt ? colAt(k0) : col).withAlpha(0.92f * std::pow(1 - z, 1.6f) + 0.02f));
                    g.fillPath(p);
                }
                L.clear(); R.clear();
            };
            for (int k = k0; k <= std::min(kHist - 1, k0 + chunk); ++k) {
                float x, w;
                if (!at(k, x, w)) { flush(); continue; }
                const float z = (float) k / (kHist - 1);
                L.push_back(proj(x - w, z)); R.push_back(proj(x + w, z));
            }
            flush();
        }
    };
    auto orb = [&](float x, Colour col, float lvl) {
        auto c = proj(x, 0);
        g.setColour(col.withAlpha(0.16f * lvl));
        g.fillEllipse(c.x - 24, c.y - 24, 48, 48);
        g.setColour(col.withAlpha(0.3f * lvl));
        g.fillEllipse(c.x - 13, c.y - 13, 26, 26);
        g.setColour(col);
        g.fillEllipse(c.x - 7, c.y - 7, 14, 14);
        g.setColour(Colours::white);
        g.fillEllipse(c.x - 2.5f, c.y - 2.5f, 5, 5);
    };
    if (gl) {                                               // Glide: each voice a ribbon; a glide is a lane change
        float lo = 1e9f, hi = -1e9f;
        for (auto& tv : trail) for (float c : tv) if (c > 0) { lo = std::min(lo, c); hi = std::max(hi, c); }
        for (int v = 0; v < 6; ++v) if (proc.glide.on[(size_t) v]) { float t = proc.glide.target[(size_t) v]; lo = std::min(lo, t); hi = std::max(hi, t); }
        if (lo > hi) { lo = 3300; hi = 7200; }
        if (hi - lo < 3000) { const float m = (hi + lo) / 2; lo = m - 1500; hi = m + 1500; }
        fieldLo += (lo - fieldLo) * 0.08f; fieldHi += (hi - fieldHi) * 0.08f;   // the view eases to the range in use
        const float mid = (fieldLo + fieldHi) / 2, half = (fieldHi - fieldLo) / 2 * 1.12f;
        for (int v = 5; v >= 0; --v) {
            ribbon([&](int k, float& x, float& w) {
                const size_t i = (size_t) ((trailAt - 1 - k + 2 * kHist) % kHist);
                const float c = trail[(size_t) v][i];
                if (c <= 0) return false;
                x = (c - mid) / half;
                w = 0.012f + 0.03f * jlimit(0.0f, 1.0f, trailLv[(size_t) v][i] / 0.7f);
                return true;
            }, VCOL[v]);
            if (proc.glide.level[(size_t) v] > 0.01f) {
                const float tx = (proc.glide.target[(size_t) v] - mid) / half, nx = (proc.glide.cents[(size_t) v] - mid) / half;
                if (proc.glide.on[(size_t) v] && std::abs(tx - nx) > 0.01f) {   // where it's headed
                    auto t = proj(tx, 0);
                    g.setColour(VCOL[v].withAlpha(0.8f));
                    g.drawEllipse(t.x - 7, t.y - 7, 14, 14, 1.5f);
                }
                orb(nx, VCOL[v], jlimit(0.3f, 1.0f, proc.glide.level[(size_t) v] / 0.6f));
            }
        }
    } else {                                                // Chord and Drone: every note a bar of light laid on the floor
        const uint64_t nowLo = noteHist[(size_t) ((trailAt - 1 + kHist) % kHist)][0], nowHi = noteHist[(size_t) ((trailAt - 1 + kHist) % kHist)][1];
        uint64_t anyLo = 0, anyHi = 0;
        for (auto& h : noteHist) { anyLo |= h[0]; anyHi |= h[1]; }
        for (int m = 0; m < 128; ++m) {
            if (!((m < 64 ? anyLo >> m : anyHi >> (m - 64)) & 1)) continue;
            const float x = jlimit(-1.15f, 1.15f, ((float) m - 58.0f) / 30.0f);
            auto colAt = [&](int k) { return CCOL[(size_t) jlimit(0, 6, (int) chordHist[(size_t) ((trailAt - 1 - k + 2 * kHist) % kHist)])]; };
            ribbon([&](int k, float& xx, float& w) {
                const auto& h = noteHist[(size_t) ((trailAt - 1 - k + 2 * kHist) % kHist)];
                if (!((m < 64 ? h[0] >> m : h[1] >> (m - 64)) & 1)) return false;
                xx = x; w = m < 48 ? 0.05f : 0.03f;            // the bass lays a wider bar
                return true;
            }, orange, colAt);
            if ((m < 64 ? nowLo >> m : nowHi >> (m - 64)) & 1) orb(x, colAt(0), 1.0f);
        }
    }

    // ---- the words
    g.setColour(ink);
    g.setFont(Font(FontOptions(15.f, Font::bold)).withExtraKerningFactor(0.16f));
    g.drawText("BRICKLAB", 22, 10, 110, 32, Justification::centredLeft);
    g.setColour(ink.withAlpha(0.5f));
    g.setFont(Font(FontOptions(15.f)).withExtraKerningFactor(0.16f));
    g.drawText("STUDIO", 112, 10, 70, 32, Justification::centredLeft);
    auto* sc = tab == 0 ? &sound : (tab == 1 ? &leadSound : (tab == 2 ? &droneSound : &glideSound));
    g.setColour(dim);
    g.setFont(Font(FontOptions(11.f)).withExtraKerningFactor(0.14f));
    g.drawText((key.getText() + " " + scale.getText() + (sounds ? String::fromUTF8("   \xc2\xb7   ") + sc->getText() : String())).toUpperCase(), 24, 62, 500, 14, Justification::centredLeft);
    const auto name = proc.chordName();
    g.setColour(ink);
    g.setFont(FontOptions(gl ? 46.f : 58.f));
    g.drawText(name, 22, 78, 520, 62, Justification::centredLeft);
    String sub = gl ? String() : proc.chordRoman();
    const int ready = proc.soundsReady(), want = proc.soundsWanted();
    if (ready < want) sub = "making the sound: " + String(ready) + " / " + String(want) + " notes";
    else if (name.isEmpty()) sub = gl ? "play a pad or a chord: the voices glide from one to the next"
                                  : (tab == 2 ? "tap a pad or a key to drone on it, again to stop" : "play a pad, or chords from your keyboard");
    g.setColour(dim);
    g.setFont(FontOptions(12.5f));
    g.drawText(sub, 24, name.isEmpty() ? 84 : 142, 600, 16, Justification::centredLeft);

    // ---- the glass the controls sit on
    auto glass = [&](Rectangle<float> r, float rad) {
        g.setColour(Colour(0xd012111a));
        g.fillRoundedRectangle(r, rad);
        g.setColour(Colours::white.withAlpha(0.10f));
        g.drawRoundedRectangle(r, rad, 1.0f);
    };
    const float dockTop = rowA ? 412.0f : 454.0f;
    glass({12, dockTop, kW - 24.0f, 582.0f - dockTop}, 18);
    if (sounds) glass({810, 68, 76, gl ? 204.0f : 140.0f}, 16);
}

void BricklabStudioEditor::resized() {                     // any size: the whole page scales, keeping its shape
    canvas.setBounds(0, 0, kW, kH);
    canvas.setTransform(juce::AffineTransform::scale((float) getWidth() / (float) kW));
    layout();
}

void BricklabStudioEditor::layout() {
    const bool gl = tab == 3, chord = tab == 0, drone = tab == 2, lead = tab == 1;
    const bool curves = gl && curvesBtn.getToggleState();
    const juce::Rectangle<int> none;
    for (juce::Component* c : std::initializer_list<juce::Component*>{&modeL, &arpL, &bassL, &octL, &glideChordL, &slideL, &glideL, &spaceL,
                                                                      &volumeL, &glideToneL, &outNote, &soon})
        c->setBounds(none);                                // the glass layout needs no captions
    auto put = [](juce::Rectangle<int>& r, juce::Component& c, int w) { c.setBounds(r.removeFromLeft(w)); r.removeFromLeft(8); };

    // the top bar
    int x = 196;
    for (auto* t : tabs) { t->setBounds(x, 10, 76, 32); x += 82; }
    dragMidi.setBounds(kW - 20 - 96, 10, 96, 32);
    glideMore.setBounds(kW - 20 - 96 - 6 - 60, 10, 60, 32);
    curvesBtn.setBounds(kW - 20 - 96 - 6 - 60 - 6 - 70, 10, 70, 32);
    presetBox.setBounds(gl ? 466 : 608, 10, 170, 32);

    // the knobs, on the right
    int ky = 74;
    if (gl) { glideTone.setBounds(818, ky, 60, 62); ky += 64; } else glideTone.setBounds(none);
    space.setBounds(818, ky, 60, 62);
    volume.setBounds(818, ky + 64, 60, 62);

    // the dock: the pads, the page's main row above them, its second row above that
    const int w = (856 - 6 * 8) / 7;
    for (int i = 0; i < pads.size(); ++i) pads[i]->setBounds(22 + i * (w + 8), 512, w, 60);
    auto b = juce::Rectangle<int>(22, 466, 856, 32);
    if (gl) { put(b, bloomBtn, 64); put(b, stopBtn, 64); put(b, glideChord, 120); put(b, glideSub, 54); }
    if (!proc.kMidiFx) {
        auto sb = b.removeFromLeft(190); b.removeFromLeft(8);
        for (auto* c : {&sound, &leadSound, &droneSound, &glideSound}) c->setBounds(sb);
    }
    if (gl && proc.kMidiFx) { put(b, glideMpe, 110); put(b, glideStrike, 130); }
    put(b, key, 64);
    put(b, scale, 140);
    if (!gl) put(b, octave, 84);

    auto a = juce::Rectangle<int>(22, 424, 856, 32);
    if (chord) {
        for (auto* m : modButtons) put(a, *m, 60);
        put(a, latch, 60);
        a.removeFromLeft(8);
        put(a, mode, 150); put(a, arpOct, 78); put(a, bassMode, 120); put(a, bassLvl, 90);
    } else if (drone) {
        put(a, third, 60); put(a, droneSlide, 130);
        put(a, pulseL, 90); put(a, droneY, 120); put(a, bloomL, 88); put(a, droneX, 120);
    } else if (lead)
        put(a, leadGlide, 140);
    else if (curves) {                                      // the routing, under the editor
        put(a, prL, 62); put(a, prSrc, 150); put(a, prDepth, 90); a.removeFromLeft(8);
        put(a, tbL, 52); put(a, tbSrc, 150); put(a, tbDepth, 90); a.removeFromLeft(8);
        put(a, lfoL, 32); put(a, lfoRate, 100);
    } else {
        put(a, glideTime, 100); put(a, glidePath, 112); put(a, glideCross, 118); put(a, glideMove, 100); put(a, glideFade, 90);
        put(a, glideTiming, 124); put(a, glideBend, 80); put(a, octave, 70);
    }
    curveEd->setBounds(20, 56, 782, 350);
}

void BricklabStudioEditor::layoutRows() { layout(); }

void BricklabStudioEditor::timerCallback() {
    for (int v = 0; v < 6; ++v) {                          // the Glide trails
        const bool on = proc.glide.level[(size_t) v] > 0.01f;
        trail[(size_t) v][(size_t) trailAt] = on ? proc.glide.cents[(size_t) v].load() : 0.0f;
        trailLv[(size_t) v][(size_t) trailAt] = proc.glide.level[(size_t) v];
        trailLvl[(size_t) v] = proc.glide.level[(size_t) v];
    }
    noteHist[(size_t) trailAt] = {proc.noteBitsLo.load(), proc.noteBitsHi.load()};
    {                                                      // which pad's chord is sounding: its colour
        const auto root = chordRoot(proc.chordName());
        int deg = chordHist[(size_t) ((trailAt - 1 + kHist) % kHist)];
        for (int i = 0; i < pads.size(); ++i) if (root.isNotEmpty() && chordRoot(pads[i]->top) == root) deg = i;
        chordHist[(size_t) trailAt] = (int8_t) deg;
        for (int i = 0; i < pads.size(); ++i) {
            const juce::Colour t = tab == 3 ? juce::Colour() : CCOL[i % 7];
            if (pads[i]->tint != t) { pads[i]->tint = t; pads[i]->repaint(); }
        }
    }
    trailAt = (trailAt + 1) % kHist;
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
    canvas.repaint();
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
