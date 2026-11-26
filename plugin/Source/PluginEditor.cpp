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
    value.addCentredArc(cx, cy, rad, rad, 0, s.getMinimum() < 0 ? (a0 + a1) * 0.5f : a0, ang, true);   // two-way ones: from the top
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
    glideMpe.addItemList({"Out: MPE", "Out: notes", "Out: walk"}, 1);   // one item per choice of the parameter, in its order
    for (auto* c : {&glideSound, &glideChord, &glidePath, &glideTiming, &glideMove, &glideCross, &glideTime, &glideFade, &glideBend, &glideMpe})
        addAndMakeVisible(c);
    glideSub.setClickingTogglesState(true);
    glideSubBox.addItemList({"Sub off", "Sub", "Sub from E1", "Sub from A1", "Sub from C2"}, 1);   // on or off, and how low it may go
    glideSubBox.onChange = [this] {
        const int k = glideSubBox.getSelectedItemIndex();
        if (k < 0) return;
        if (auto* p = proc.params.getParameter("glidesub")) p->setValueNotifyingHost(k > 0 ? 1.0f : 0.0f);
        if (k > 0) if (auto* p = proc.params.getParameter("glidesubfloor")) p->setValueNotifyingHost(p->convertTo0to1((float) (k - 1)));
    };
    addAndMakeVisible(glideSubBox);
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
    for (auto& r : brick::kDroneRecs) droneSound.addItem(r.name, droneSound.getNumItems() + 1);
    octave.addItemList({"Oct -2", "Oct -1", "Oct 0", "Oct +1", "Oct +2"}, 1);
    droneSlide.addItemList({"Slide off", "Slide 0.5 s", "Slide 1 s", "Slide 2 s", "Slide 4 s"}, 1);
    for (int i = 0; i < brick::kNumDroneChords; ++i) droneChord.addItem(brick::kDroneChords[i], i + 1);
    for (int i = 0; i < brick::kNumChordColours; ++i) chordColour.addItem(brick::kChordColours[i], i + 1);
    addAndMakeVisible(chordColour);
    for (int i = 0; i < brick::kNumPluckInsts; ++i) pluckSound.addItem(juce::String("Strum: ") + brick::kPluckInsts[i].name, i + 1);
    glideReach.addItemList({"Range: tight", "Range: normal", "Range: free"}, 1);
    addAndMakeVisible(glideReach);
    pluckArp.addItemList({"Arp off", "Arp up", "Arp down", "Arp bounce", "Arp random"}, 1);
    pluckRate.addItemList({"1/4", "1/8", "1/8 T", "1/16", "1/32"}, 1);
    cloudStyle.addItemList({"Cloud: grains", "Cloud: sparse", "Cloud: long", "Cloud: shimmer", "Cloud: deep", "Cloud: scatter", "Cloud: freeze"}, 1);
    addAndMakeVisible(cloudStyle);
    for (auto* c : {&droneChord, &pluckSound, &pluckArp, &pluckRate}) addAndMakeVisible(c);
    for (auto* k : {&droneDrift, &droneAir, &pluckLevel, &pluckEcho, &pluckRing, &droneCloud}) { k->setTextBoxStyle(juce::Slider::NoTextBox, false, 0, 0); addAndMakeVisible(k); }
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
    aDroneChord = std::make_unique<juce::AudioProcessorValueTreeState::ComboBoxAttachment>(ps, "dronechord", droneChord);
    aChordColour = std::make_unique<juce::AudioProcessorValueTreeState::ComboBoxAttachment>(ps, "chordcolour", chordColour);
    aPluckSound = std::make_unique<juce::AudioProcessorValueTreeState::ComboBoxAttachment>(ps, "plucksound", pluckSound);
    aPluckArp = std::make_unique<juce::AudioProcessorValueTreeState::ComboBoxAttachment>(ps, "pluckarp", pluckArp);
    aPluckRate = std::make_unique<juce::AudioProcessorValueTreeState::ComboBoxAttachment>(ps, "pluckrate", pluckRate);
    aCloudStyle = std::make_unique<juce::AudioProcessorValueTreeState::ComboBoxAttachment>(ps, "cloudstyle", cloudStyle);
    aDroneDrift = std::make_unique<juce::AudioProcessorValueTreeState::SliderAttachment>(ps, "dronedrift", droneDrift);
    aDroneAir = std::make_unique<juce::AudioProcessorValueTreeState::SliderAttachment>(ps, "droneair", droneAir);
    aPluckLevel = std::make_unique<juce::AudioProcessorValueTreeState::SliderAttachment>(ps, "plucklevel", pluckLevel);
    aPluckEcho = std::make_unique<juce::AudioProcessorValueTreeState::SliderAttachment>(ps, "pluckecho", pluckEcho);
    aPluckRing = std::make_unique<juce::AudioProcessorValueTreeState::SliderAttachment>(ps, "pluckring", pluckRing);
    aDroneCloud = std::make_unique<juce::AudioProcessorValueTreeState::SliderAttachment>(ps, "dronecloud", droneCloud);
    aDroneX = std::make_unique<juce::AudioProcessorValueTreeState::SliderAttachment>(ps, "dronex", droneX);
    using CA = juce::AudioProcessorValueTreeState::ComboBoxAttachment;
    aGlideSound = std::make_unique<CA>(ps, "glidesound", glideSound);
    aGlideChord = std::make_unique<CA>(ps, "glidechord", glideChord);
    aGlidePath = std::make_unique<CA>(ps, "glidepath", glidePath);
    aGlideTiming = std::make_unique<CA>(ps, "glidetiming", glideTiming);
    aGlideMove = std::make_unique<CA>(ps, "glidemove", glideMove);
    aGlideCross = std::make_unique<CA>(ps, "glidecross", glideCross);
    aGlideReach = std::make_unique<CA>(ps, "glidereach", glideReach);
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

    for (auto* k : {&glideTone, &space, &volume, &droneY, &droneX, &droneDrift, &droneAir, &pluckLevel, &pluckEcho, &pluckRing, &droneCloud}) {          // the knobs
        k->setSliderStyle(juce::Slider::RotaryHorizontalVerticalDrag);
        k->setRotaryParameters(juce::MathConstants<float>::pi * 1.25f, juce::MathConstants<float>::pi * 2.75f, true);
        k->setMouseDragSensitivity(140);
    }
    glideTone.setName("Tone"); space.setName("Space"); volume.setName("Volume");
    droneY.setName("Pulse"); droneX.setName("Bloom"); droneDrift.setName("Drift"); droneAir.setName("Air");
    pluckLevel.setName("Strum"); pluckEcho.setName("Echo"); pluckRing.setName("Ring"); droneCloud.setName("Cloud");
    viewBtn.onClick = [this] {                               // Field or Terrain
        const int v = ((int) proc.params.getRawParameterValue("view")->load() + 1) % 3;   // field, terrain, spectrum, and round again
        if (auto* p = proc.params.getParameter("view")) p->setValueNotifyingHost(p->convertTo0to1((float) v));
    };
    canvas.addAndMakeVisible(viewBtn);
    {
        juce::Random r(7);
        for (int i = 0; i < 46; ++i) dust.push_back({r.nextFloat() * 2.6f - 1.3f, r.nextFloat(), 8.0f + r.nextFloat() * 46.0f, r.nextFloat() * 6.28f});
    }
    canvas.pointer = [this](juce::Point<float> p, bool down) {   // Drone: the field is the strings; drag across to strum
        if (tab != 2 || !down || p.y < 150) { proc.uiStrum = -1.0f; return; }
        const float sc = (p.y - fieldHor) / fieldK;             // undo the perspective: which lane is under the pointer
        proc.uiStrum = juce::jlimit(0.0f, 1.0f, ((p.x - 440.0f) / (79.0f * std::max(0.5f, sc)) - camX / 79.0f + 1.0f) * 0.5f);
    };
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
    glideSub.setVisible(false);                              // the Sub menu does this now
    show({&glideChord, &glideChordL, &bloomBtn, &stopBtn, &glideSubBox, &glideMore, &glideReach}, gl);
    show({&glideTone, &glideToneL}, gl && sounds);
    show({&glidePath, &glideMove, &glideCross, &glideTime, &glideFade, &glideTiming, &glideBend}, gl && more && !curves);
    show({&glideMpe, &glideStrike}, gl && proc.kMidiFx);
    show({&leadGlide, &glideL}, lead);
    third.setVisible(false);                                 // the Triad chord shape does this now
    show({&droneSlide, &droneChord, &droneY, &droneX, &pluckArp, &pluckRate}, drone);
    stopBtn.setVisible(gl || drone);
    chordColour.setVisible(tab == 0);
    show({&pluckSound, &cloudStyle, &droneDrift, &droneAir, &pluckLevel, &pluckEcho, &pluckRing, &droneCloud}, drone && sounds);
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
    const int viewNow = (int) proc.params.getRawParameterValue("view")->load();
    const bool terrainView = viewNow == 1, spectrumView = viewNow == 2;
    const float cx = 440, hor = fieldHor + camY, K = fieldK, LK = 79;
    // the camera drifts a little from side to side: near things move across far ones, which is what reads as depth
    auto proj = [&](float x, float z) { const float s = 1.0f / (0.22f + z * 1.9f); return Point<float>(cx + (x * LK + camX) * s, hor + K * s); };
    if (bloom > 0.01f) {                                    // a change of chord lights the horizon
        Graphics::ScopedSaveState keep(g);                   // a round glow, pressed flat along the horizon
        g.addTransform(AffineTransform::scale(1.0f, 0.24f, cx, hor + 12));
        g.setGradientFill(ColourGradient(orange.withAlpha(0.40f * bloom), cx, hor + 12, orange.withAlpha(0.0f), cx + 340, hor + 12, true));
        g.fillEllipse(cx - 340, hor + 12 - 340, 680, 680);
    }
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
            std::vector<Point<float>> GL, GR;                // its glow on the floor, wider
            auto flush = [&] {                              // fill the run gathered so far
                if (L.size() >= 2) {
                    const float z = (float) k0 / (kHist - 1);
                    const Colour cc = colAt ? colAt(k0) : col;
                    Path gp, p;
                    gp.startNewSubPath(GL[0]);
                    for (size_t i = 1; i < GL.size(); ++i) gp.lineTo(GL[i]);
                    for (size_t i = GR.size(); i-- > 0;) gp.lineTo(GR[i]);
                    gp.closeSubPath();
                    g.setColour(cc.withAlpha(0.20f * std::pow(1 - z, 1.6f)));
                    g.fillPath(gp);
                    p.startNewSubPath(L[0]);
                    for (size_t i = 1; i < L.size(); ++i) p.lineTo(L[i]);
                    for (size_t i = R.size(); i-- > 0;) p.lineTo(R[i]);
                    p.closeSubPath();
                    g.setColour(cc.withAlpha(0.92f * std::pow(1 - z, 1.6f) + 0.02f));
                    g.fillPath(p);
                }
                L.clear(); R.clear(); GL.clear(); GR.clear();
            };
            for (int k = k0; k <= std::min(kHist - 1, k0 + chunk); ++k) {
                float x, w;
                if (!at(k, x, w)) { flush(); continue; }
                const float z = (float) k / (kHist - 1), up = kLift / (0.22f + z * 1.9f);   // lifted off the floor
                auto a = proj(x - w, z), b2 = proj(x + w, z);
                GL.push_back(proj(x - w * 2.2f, z)); GR.push_back(proj(x + w * 2.2f, z));
                L.push_back({a.x, a.y - up}); R.push_back({b2.x, b2.y - up});
            }
            flush();
        }
    };
    auto orb = [&](float x, Colour col, float lvl) {
        auto c = proj(x, 0);
        g.setColour(col.withAlpha(0.22f * lvl));              // its light on the floor
        g.fillEllipse(c.x - 30, c.y - 7, 60, 14);
        c.y -= kLift / 0.22f;
        g.setColour(col.withAlpha(0.16f * lvl));
        g.fillEllipse(c.x - 24, c.y - 24, 48, 48);
        g.setColour(col.withAlpha(0.3f * lvl));
        g.fillEllipse(c.x - 13, c.y - 13, 26, 26);
        g.setColour(col);
        g.fillEllipse(c.x - 7, c.y - 7, 14, 14);
        g.setColour(Colours::white);
        g.fillEllipse(c.x - 2.5f, c.y - 2.5f, 5, 5);
    };
    if (viewNow == 0)                                       // dust in the air, drifting towards you
        for (auto& d : dust) {
            const float sc = 1.0f / (0.22f + d.z * 1.9f);
            auto c = proj(d.x, d.z);
            const float tw = 0.5f + 0.5f * std::sin(d.ph);
            g.setColour(Colours::white.withAlpha(0.05f + 0.20f * tw * (1 - d.z)));
            g.fillEllipse(c.x - 0.5f * sc, c.y - d.h * sc * 0.45f, 0.5f + 0.45f * sc, 0.5f + 0.45f * sc);
        }
    if (spectrumView) {                                     // Spectrum: a spectrogram you could walk on. Loudness is height and
        // colour together (blue for quiet, through green and yellow to red), and the surface rolls away as it ages.
        static std::array<PixelARGB, 256> lut;
        static bool made = false;
        if (!made) {
            made = true;
            const Colour cs[] = {Colour(0xff15113a), Colour(0xff2f35c8), Colour(0xff1fb6c9), Colour(0xff58cf62), Colour(0xffffd84a), Colour(0xffff8a3c), Colour(0xffff3b4e)};
            const float at[] = {0.0f, 0.16f, 0.36f, 0.54f, 0.72f, 0.87f, 1.0f};
            for (int i = 0; i < 256; ++i) {
                const float v = (float) i / 255.0f;
                int k = 0;
                while (k < 5 && v > at[k + 1]) ++k;
                lut[(size_t) i] = cs[k].interpolatedWith(cs[k + 1], (v - at[k]) / (at[k + 1] - at[k])).getPixelARGB();
            }
        }
        const int yOff = (int) hor - 20, yBot = std::min((int) (hor + K / 0.22f) + 1, kH - 1), hh = yBot - yOff + 1;
        Image img(Image::ARGB, kW, hh, true);
        {
            Image::BitmapData bd(img, Image::BitmapData::readWrite);
            std::array<int, kW> top;                         // per column, the highest point drawn so far (nearer land hides farther)
            top.fill(hh);
            const float ph = terrainPhase ? 0.5f : 0.0f, a0 = (ph + 0.5f) / (float) kRows;
            auto hist = [&](int r) -> const std::array<float, kSpec>& { return spec[(size_t) ((terrainAt - 1 - std::clamp(r, 0, kRows - 1) + 2 * kRows) % kRows)]; };
            std::array<float, kSpec> row;
            const int steps = 230;
            int lastRow = -2;
            for (int d = 0; d <= steps; ++d) {                // from your feet outwards
                const float age = (float) d / (float) steps, z = std::pow(age, 1.35f) * 0.94f, sc = 1.0f / (0.22f + z * 1.9f);
                bool seam = false;                            // where one moment's slice meets the next: a faint line, like a mesh
                if (age < a0) {
                    const auto& h0 = hist(0);
                    const float t = age / a0;
                    for (int b = 0; b < kSpec; ++b) row[(size_t) b] = specNow[(size_t) b] + (h0[(size_t) b] - specNow[(size_t) b]) * t;
                } else {
                    const float u = age * (float) kRows - ph - 0.5f;
                    const int r = (int) u;
                    const float f = u - (float) r;
                    const auto &h0 = hist(r), &h1 = hist(r + 1);
                    for (int b = 0; b < kSpec; ++b) row[(size_t) b] = h0[(size_t) b] + (h1[(size_t) b] - h0[(size_t) b]) * f;
                    seam = r != lastRow; lastRow = r;
                }
                const float floorY = hor + K * sc - (float) yOff, amp = 36.0f * sc;
                const float light = (d == 0 ? 0.42f : (seam ? 0.80f : 1.0f)) * (0.25f + 0.75f * std::pow(1.0f - z, 0.7f));   // the cut face at the front is in shade
                const float far = jlimit(0.0f, 1.0f, (0.94f - z) / 0.36f);   // the far end melts into the haze
                const float per = (float) (kSpec - 1) / (2.44f * LK * sc), x0 = cx + (-1.22f * LK + camX) * sc;
                const int xa = std::max(0, (int) std::ceil(x0)), xb = std::min(kW - 1, (int) (x0 + 2.44f * LK * sc));
                for (int x = xa; x <= xb; ++x) {
                    const float bp = ((float) x - x0) * per;
                    const int b = std::min(kSpec - 2, (int) bp);
                    float v = row[(size_t) b] + (row[(size_t) (b + 1)] - row[(size_t) b]) * (bp - (float) b);
                    v = jmin(1.0f, v * v * 1.2f);                 // squared: the peaks stand up out of the plain
                    const int yt = std::max(0, (int) (floorY - v * amp));
                    int& tp = top[(size_t) x];
                    if (yt >= tp) continue;                       // behind something nearer
                    PixelARGB px = lut[(size_t) (int) (v * 255.0f)];
                    px.setARGB((uint8) (255.0f * far), (uint8) ((float) px.getRed() * light * far), (uint8) ((float) px.getGreen() * light * far), (uint8) ((float) px.getBlue() * light * far));
                    for (int y = yt; y < tp; ++y) ((PixelARGB*) bd.getLinePointer(y))[x] = px;
                    tp = yt;
                }
            }
        }
        g.drawImageAt(img, 0, yOff);
    } else if (terrainView) {                               // Terrain: the sound itself as a landscape
        static const Colour stops[] = {VCOL[0], VCOL[1], VCOL[2], VCOL[3], VCOL[4]};
        auto rowAt = [&](int r) -> const std::array<float, kBands>& { return terrain[(size_t) ((terrainAt - 1 - std::clamp(r, 0, kRows - 1) + 2 * kRows) % kRows)]; };
        for (int r = kRows - 1; r >= -1; --r) {              // the far ridges first, so the near ones stand in front of them
            // r = -1 is the land as it is this instant, at your feet; the rest slide back from there
            const float age = r < 0 ? 0.0f : ((float) r + (terrainPhase ? 0.5f : 0.0f) + 0.5f) / (float) kRows;
            if (r < 0 && !terrainPhase) continue;
            std::array<float, kBands> row;
            if (r < 0) row = bandNow;
            else {                                           // each ridge shares a little with its neighbours in time: a surface
                const auto &a0 = rowAt(r - 1), &a1 = rowAt(r), &a2 = rowAt(r + 1);
                const float swell = 1.0f + 0.10f * std::sin((float) (terrainCount - r) * 0.42f);   // a slow swell riding back with it
                for (int b = 0; b < kBands; ++b) row[(size_t) b] = (0.25f * a0[(size_t) b] + 0.5f * a1[(size_t) b] + 0.25f * a2[(size_t) b]) * swell;
            }
            const float z = std::pow(age, 1.35f) * 0.94f, sc = 1.0f / (0.22f + z * 1.9f), near = 1.0f - z;
            const float floorY = hor + K * sc, amp = 30.0f * sc;
            Path line, fill;
            Point<float> prev;
            for (int b = 0; b < kBands; ++b) {
                const float x = -1.22f + 2.44f * (float) b / (float) (kBands - 1);
                const Point<float> pt(cx + (x * LK + camX) * sc, floorY - row[(size_t) b] * amp);
                if (b == 0) { line.startNewSubPath(pt); fill.startNewSubPath(pt.x, floorY); fill.lineTo(pt); }
                else { const auto mid = (prev + pt) * 0.5f; line.quadraticTo(prev, mid); fill.quadraticTo(prev, mid); }
                prev = pt;
            }
            line.lineTo(prev); fill.lineTo(prev); fill.lineTo(prev.x, floorY); fill.closeSubPath();
            g.setColour(chassis.interpolatedWith(Colour(0xff1c1932), 0.35f * near).withAlpha(0.94f));   // it hides what is behind it
            g.fillPath(fill);
            const float x0 = cx + (-1.22f * LK + camX) * sc, x1 = cx + (1.22f * LK + camX) * sc;
            ColourGradient gr(stops[0].withAlpha(0.15f * near * near), 0, floorY - amp, stops[0].withAlpha(0.0f), 0, floorY, false);
            g.setGradientFill(gr);                           // a glow inside each ridge
            g.fillPath(fill);
            ColourGradient across(stops[0], x0, 0, stops[4], x1, 0, false);
            for (int k = 1; k < 4; ++k) across.addColour(k / 4.0, stops[k]);
            across.multiplyOpacity(0.06f + 0.94f * std::pow(near, 1.5f));
            g.setGradientFill(across);
            g.strokePath(line, PathStrokeType(0.7f + 1.5f * near, PathStrokeType::curved, PathStrokeType::rounded));
        }
    } else if (gl) {                                        // Glide: each voice a ribbon; a glide is a lane change
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
                    t.y -= kLift / 0.22f;
                    g.setColour(VCOL[v].withAlpha(0.8f));
                    g.drawEllipse(t.x - 7, t.y - 7, 14, 14, 1.5f);
                }
                orb(nx, VCOL[v], jlimit(0.3f, 1.0f, proc.glide.level[(size_t) v] / 0.6f));
            }
        }
    } else if (tab == 2) {                                  // Drone: strings across the floor, the voices standing in it
        const Colour hue = CCOL[(size_t) jlimit(0, 6, (int) chordHist[(size_t) ((trailAt - 1 + kHist) % kHist)])];
        const double now = Time::getMillisecondCounterHiRes() * 0.001;
        std::vector<int> strs;
        const uint64_t sLo = proc.stringBitsLo.load(), sHi = proc.stringBitsHi.load();
        for (int m = 0; m < 128; ++m) if ((m < 64 ? sLo >> m : sHi >> (m - 64)) & 1) strs.push_back(m);
        auto laneOf = [&](int m) {
            for (size_t i = 0; i < strs.size(); ++i) if (strs[i] == m) return strs.size() > 1 ? -1.0f + 2.0f * (float) i / (float) (strs.size() - 1) : 0.0f;
            return 0.0f;
        };
        for (size_t i = 0; i < strs.size(); ++i) {           // the strings: brighter while they ring
            const float x = laneOf(strs[i]), gl2 = stringGlow[(size_t) strs[i]];
            auto a = proj(x, 0), b = proj(x, 1);
            const bool hov = (int) i == hoverString;
            g.setGradientFill(ColourGradient(hue.interpolatedWith(Colours::white, gl2 * 0.6f).withAlpha(0.28f + 0.6f * gl2 + (hov ? 0.25f : 0.0f)), a.x, a.y,
                                             hue.withAlpha(0.0f), b.x, b.y, false));
            g.drawLine(a.x, a.y, b.x, b.y, 1.2f + 2.6f * gl2);
            g.setColour(hue.withAlpha(0.35f + 0.65f * gl2));
            g.fillEllipse(a.x - 2.5f - 3 * gl2, a.y - 2.5f - 3 * gl2, 5 + 6 * gl2, 5 + 6 * gl2);
        }
        // the drone's voices: columns of light that sway; the overtones stand further back, paler
        struct Col { float cents, lvl; };
        std::vector<Col> cols;
        const auto& pl = proc.dronePlayer();
        for (int i = 0; i < std::min((int) brick::Player::kShown, pl.dCount.load()); ++i) cols.push_back({pl.dCents[(size_t) i].load(), pl.dLevel[(size_t) i].load()});
        if (cols.empty()) {                                  // the MIDI builds: the notes it's sending
            const uint64_t nLo = proc.noteBitsLo.load(), nHi = proc.noteBitsHi.load();
            for (int m = 0; m < 128; ++m) if ((m < 64 ? nLo >> m : nHi >> (m - 64)) & 1) cols.push_back({m * 100.0f, 1.0f});
        }
        std::sort(cols.begin(), cols.end(), [](const Col& p, const Col& q) { return p.cents > q.cents; });   // far ones first
        int ci = 0;
        for (auto& c : cols) {
            const bool air = c.cents >= 7150;
            const float lvl = jlimit(0.0f, 1.3f, c.lvl);
            if (lvl < 0.01f) { ++ci; continue; }
            const float x = jlimit(-1.1f, 1.1f, (c.cents * 0.01f - (air ? 78.0f : 58.0f)) / (air ? 9.0f : 16.0f));
            const float z = air ? 0.35f : 0.06f, sc = 1.0f / (0.22f + z * 1.9f);
            const auto b = proj(x, z);
            const float hgt = (air ? 95.0f : 30.0f + 34.0f * lvl) * sc, wd = (air ? 2.4f : 4.0f) * sc;
            const float sway = (float) std::sin(now * (air ? 0.9 : 0.45) + ci * 1.9) * (air ? 7.0f : 4.0f) * sc;
            const Colour cc = air ? hue.interpolatedWith(Colours::white, 0.7f) : hue;
            Path p;
            p.startNewSubPath(b.x - wd, b.y); p.lineTo(b.x + wd, b.y);
            p.lineTo(b.x + sway + wd * 0.35f, b.y - hgt); p.lineTo(b.x + sway - wd * 0.35f, b.y - hgt);
            p.closeSubPath();
            g.setGradientFill(ColourGradient(cc.withAlpha(jmin(0.9f, (air ? 0.75f : 0.8f) * lvl)), b.x, b.y, cc.withAlpha(0.0f), b.x + sway, b.y - hgt, false));
            g.fillPath(p);
            g.setColour(cc.withAlpha(jmin(0.5f, 0.3f * lvl)));
            g.fillEllipse(b.x - wd * 2.6f, b.y - wd * 0.7f, wd * 5.2f, wd * 1.4f);
            g.setColour(Colours::white.withAlpha(jmin(0.9f, 0.7f * lvl)));
            g.fillEllipse(b.x - wd * 0.6f, b.y - wd * 0.3f, wd * 1.2f, wd * 0.6f);
            ++ci;
        }
        for (auto& sp : sparks) {                            // plucked notes run away down their strings
            const float x = laneOf(sp.midi), z = sp.age * sp.age * 0.9f, fade = 1.0f - sp.age;
            const auto c = proj(x, z), t = proj(x, std::max(0.0f, z - 0.05f));
            const float sc = 1.0f / (0.22f + z * 1.9f) / 4.5f;
            g.setColour(hue.interpolatedWith(Colours::white, 0.5f).withAlpha(0.7f * fade));
            g.drawLine(t.x, t.y, c.x, c.y, 3.0f * sc + 0.6f);
            g.setColour(hue.withAlpha(0.3f * fade));
            g.fillEllipse(c.x - 14 * sc, c.y - 14 * sc, 28 * sc, 28 * sc);
            g.setColour(Colours::white.withAlpha(fade));
            g.fillEllipse(c.x - 4.5f * sc, c.y - 4.5f * sc, 9 * sc, 9 * sc);
        }
    } else {                                                // Chord: every note a bar of light laid on the floor
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

    {                                                       // haze where the floor meets the sky
        g.setGradientFill(ColourGradient(chassis.withAlpha(0.0f), 0, hor + K / 0.6f, Colour(0xff1c1932).withAlpha(0.55f), 0, hor + K / 2.12f, false));
        g.fillRect(0.0f, hor + K / 2.12f, (float) kW, K / 0.6f - K / 2.12f);
        g.setGradientFill(ColourGradient(Colour(0xff1c1932).withAlpha(0.55f), 0, hor + K / 2.12f, Colour(0xff1c1932).withAlpha(0.0f), 0, hor + K / 2.12f - 46, false));
        g.fillRect(0.0f, hor + K / 2.12f - 46, (float) kW, 46.0f);   // and up into the sky, so there is no edge
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
    else if (tab == 2) sub = String::fromUTF8("drag across the strings to strum   \xc2\xb7   mod wheel strums   \xc2\xb7   pitch wheel arps");
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
    if (tab == 2) glass({740, 68, 146, sounds ? 332.0f : 76.0f}, 16);
    else if (sounds) glass({810, 68, 76, gl ? 204.0f : 140.0f}, 16);
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
                                                                      &volumeL, &glideToneL, &outNote, &soon, &pulseL, &bloomL})
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
    if (drone) {                                             // two columns: the drone's motion, the strum, the room
        juce::Slider* ks[] = {&droneY, &droneX, &droneDrift, &droneAir, &pluckLevel, &pluckEcho, &pluckRing, &droneCloud, &space, &volume};
        int k = 0;
        for (auto* sl : ks) {
            if (!sl->isVisible()) continue;
            sl->setBounds(748 + (k % 2) * 66, 74 + (k / 2) * 64, 60, 62);
            ++k;
        }
    } else {
        space.setBounds(818, ky, 60, 62);
        volume.setBounds(818, ky + 64, 60, 62);
    }

    // the dock: the pads, the page's main row above them, its second row above that
    const int w = (856 - 6 * 8) / 7;
    for (int i = 0; i < pads.size(); ++i) pads[i]->setBounds(22 + i * (w + 8), 512, w, 60);
    auto b = juce::Rectangle<int>(22, 466, 856, 32);
    const bool mf = proc.kMidiFx;
    if (gl) { put(b, bloomBtn, 60); put(b, stopBtn, 56); put(b, glideChord, mf ? 100 : 108); put(b, glideSubBox, mf ? 88 : 96); }
    if (!proc.kMidiFx) {
        auto sb = b.removeFromLeft(gl ? 160 : 190); b.removeFromLeft(8);
        for (auto* c : {&sound, &leadSound, &droneSound, &glideSound}) c->setBounds(sb);
    }
    if (gl && proc.kMidiFx) { put(b, glideMpe, 96); put(b, glideStrike, 104); }
    put(b, key, 60);
    put(b, scale, gl ? (mf ? 104 : 124) : 140);
    if (gl) put(b, glideReach, 104);
    if (!gl) put(b, octave, 84);

    auto a = juce::Rectangle<int>(22, 424, 856, 32);
    if (chord) {
        for (auto* m : modButtons) put(a, *m, 52);
        put(a, latch, 52);
        a.removeFromLeft(8);
        put(a, chordColour, 124); put(a, mode, 130); put(a, arpOct, 74); put(a, bassMode, 110); put(a, bassLvl, 70);
    } else if (drone) {
        put(a, stopBtn, 52); put(a, droneChord, 132); put(a, droneSlide, 104);
        a.removeFromLeft(12);
        if (!proc.kMidiFx) put(a, pluckSound, 160);
        put(a, pluckArp, 104); put(a, pluckRate, 70);
        a.removeFromLeft(12);
        if (!proc.kMidiFx) put(a, cloudStyle, 134);
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
    viewBtn.setBounds(24, 172, 76, 22);
    viewBtn.setVisible(!(tab == 3 && curvesBtn.getToggleState()));
}

void BricklabStudioEditor::layoutRows() { layout(); }

void BricklabStudioEditor::timerCallback() {
    for (int v = 0; v < 6; ++v) {                          // the Glide trails
        const bool on = proc.glide.level[(size_t) v] > 0.01f;
        trail[(size_t) v][(size_t) trailAt] = on ? proc.glide.cents[(size_t) v].load() : 0.0f;
        trailLv[(size_t) v][(size_t) trailAt] = proc.glide.level[(size_t) v];
        trailLvl[(size_t) v] = proc.glide.level[(size_t) v];
    }
    {                                                      // the Sub menu follows its two parameters (a preset, the host)
        const bool on = proc.params.getRawParameterValue("glidesub")->load() > 0.5f;
        const int k = on ? 1 + (int) proc.params.getRawParameterValue("glidesubfloor")->load() : 0;
        if (glideSubBox.getSelectedItemIndex() != k && !glideSubBox.isPopupActive()) glideSubBox.setSelectedItemIndex(k, juce::dontSendNotification);
    }
    if (++shotTick >= 30) {                                // for testing: while ~/BrickchordBuild/shot.on exists, a picture of
        shotTick = 0;                                      // this window goes to ~/BrickchordBuild/shot_<program>.png once a second
        const auto dir = juce::File::getSpecialLocation(juce::File::userHomeDirectory).getChildFile("BrickchordBuild");
        const auto host = juce::File::getSpecialLocation(juce::File::hostApplicationPath).getFileNameWithoutExtension();   // each program its own picture
        if (dir.getChildFile("shot.on").existsAsFile()) {
            const auto img = createComponentSnapshot(getLocalBounds(), true, 1.5f);
            const auto tmp = dir.getChildFile("shot_" + host + ".tmp");
            tmp.deleteFile();
            { juce::FileOutputStream os(tmp); if (os.openedOk()) juce::PNGImageFormat().writeImageToStream(img, os); }
            tmp.moveFileTo(dir.getChildFile("shot_" + host + ".png"));
        }
    }
    {                                                      // the camera, the bloom, the dust
        const double t = juce::Time::getMillisecondCounterHiRes() * 0.001;
        camX = 5.0f * (float) std::sin(t * 0.21) + 2.0f * (float) std::sin(t * 0.57 + 1.3);
        camY = 2.5f * (float) std::sin(t * 0.16 + 0.7);
        const auto nm = proc.chordName();
        if (nm != bloomName) { bloomName = nm; if (nm.isNotEmpty()) bloom = 1.0f; }
        bloom *= 0.93f;
        for (auto& d : dust) { d.z -= 0.0016f; d.ph += 0.05f; if (d.z < 0) { d.z = 1.0f; } }
        const int vw = (int) proc.params.getRawParameterValue("view")->load();
        const bool tv = vw > 0;
        const char* vn = vw == 0 ? "field" : (vw == 1 ? "terrain" : "spectrum");
        if (viewBtn.getButtonText() != vn) viewBtn.setButtonText(vn);
        if (tv) {                                            // a new ridge: the spectrum of the last moment
            const double sr = std::max(8000.0, proc.getSampleRate());
            std::array<float, kBands> band{};
            std::array<float, kSpec> fine{};                 // the same, twice as finely, for the Spectrum view
            if (!proc.kMidiFx) {
                const int at = proc.scopeAt.load(), N = 4096;
                for (int i = 0; i < N; ++i) {
                    const float w = 0.5f - 0.5f * std::cos(6.2831853f * (float) i / (float) (N - 1));
                    fftBuf[(size_t) i] = proc.scope[(size_t) ((at - N + i + 16384) & 8191)] * w;
                }
                std::fill(fftBuf.begin() + N, fftBuf.end(), 0.0f);
                fft.performFrequencyOnlyForwardTransform(fftBuf.data());
                auto read = [&](float* out, int nb) {         // bands of equal width in pitch, 41 Hz to 6 kHz
                    for (int b = 0; b < nb; ++b) {
                        const double f0 = 440.0 * std::pow(2.0, (28.0 + (b - 0.5) * 86.0 / (nb - 1) - 69.0) / 12.0);
                        const double f1 = 440.0 * std::pow(2.0, (28.0 + (b + 0.5) * 86.0 / (nb - 1) - 69.0) / 12.0);
                        const double p0 = f0 * N / sr, p1 = f1 * N / sr;
                        float m = 0;
                        if (p1 - p0 < 1.0) {                  // down low the bands are narrower than the bins: read between them
                            const double pc = 0.5 * (p0 + p1); const int i0 = (int) pc;
                            m = fftBuf[(size_t) i0] + (fftBuf[(size_t) (i0 + 1)] - fftBuf[(size_t) i0]) * (float) (pc - i0);
                        } else
                            for (int i = (int) p0; i <= (int) p1 && i < N / 2; ++i) m = std::max(m, fftBuf[(size_t) i]);
                        const float db = 20.0f * std::log10(std::max(1e-7f, m / (float) N * 4.0f)) - 6.0f + 15.0f * (float) b / (float) nb;   // a tilt: the bass held back, the top brought out
                        out[b] = juce::jlimit(0.0f, 1.0f, (db + 62.0f) / 46.0f);
                    }
                };
                read(band.data(), kBands);
                read(fine.data(), kSpec);
            } else {                                         // the MIDI builds make no sound: the notes they send, and their overtones
                auto add = [&](double midi, float lv) {
                    for (int h = 1; h <= 5; ++h) {
                        const double m = midi + 12.0 * std::log2((double) h);
                        auto put = [&](float* out, int nb, double wide) {
                            const double bb = (m - 28.0) * (nb - 1) / 86.0;
                            for (int b = std::max(0, (int) bb - 4); b <= std::min(nb - 1, (int) bb + 5); ++b)
                                out[b] = std::max(out[b], lv / (float) h * (float) std::exp(-(b - bb) * (b - bb) / wide));
                        };
                        put(band.data(), kBands, 1.2);
                        put(fine.data(), kSpec, 2.0);
                    }
                };
                if (tab == 3) { for (int v = 0; v < 6; ++v) if (proc.glide.level[(size_t) v] > 0.01f) add(proc.glide.cents[(size_t) v] / 100.0, juce::jlimit(0.0f, 1.0f, proc.glide.level[(size_t) v] / 0.6f)); }
                else {
                    const uint64_t lo = proc.noteBitsLo.load(), hi = proc.noteBitsHi.load();
                    for (int m = 0; m < 128; ++m) if ((m < 64 ? lo >> m : hi >> (m - 64)) & 1) add(m, 0.85f);
                }
            }
            for (int b = 0; b < kSpec; ++b) {                 // the spectrograph keeps its detail, and follows quickly
                fine[(size_t) b] *= juce::jlimit(0.0f, 1.0f, (float) std::min(b, kSpec - 1 - b) / 8.0f);
                specNow[(size_t) b] += (fine[(size_t) b] - specNow[(size_t) b]) * (fine[(size_t) b] > specNow[(size_t) b] ? 0.45f : 0.16f);
            }
            for (int pass = 0; pass < 2; ++pass) {            // rounded: hills, not spikes
                auto in = band;
                for (int b = 1; b < kBands - 1; ++b) band[(size_t) b] = 0.25f * in[(size_t) (b - 1)] + 0.5f * in[(size_t) b] + 0.25f * in[(size_t) (b + 1)];
            }
            for (int b = 0; b < kBands; ++b) {                // the land runs out to nothing at either side
                band[(size_t) b] *= juce::jlimit(0.0f, 1.0f, (float) std::min(b, kBands - 1 - b) / 5.0f);
                // it eases to each new shape, so one chord's land melts into the next as a wave, not a step
                bandNow[(size_t) b] += (band[(size_t) b] - bandNow[(size_t) b]) * (band[(size_t) b] > bandNow[(size_t) b] ? 0.16f : 0.07f);
            }
            terrainPhase = !terrainPhase;                    // a new ridge every other frame; between them the land slides half a step
            if (!terrainPhase) {
                spec[(size_t) terrainAt] = specNow;
                terrain[(size_t) terrainAt] = bandNow;
                terrainAt = (terrainAt + 1) % kRows;
                ++terrainCount;
            }
        }
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
    {                                                      // the plucks since last time: sparks, and their strings glow
        const int serial = proc.pluckSerial.load();
        for (int k = std::max(pluckSeen, serial - 16); k < serial; ++k) {
            const int m = juce::jlimit(0, 127, proc.pluckRing[(size_t) (k & 31)].load());
            sparks.push_back({m, 0.0f});
            stringGlow[(size_t) m] = 1.0f;
        }
        pluckSeen = serial;
        for (auto& sp : sparks) sp.age += 1.0f / 42.0f;
        sparks.erase(std::remove_if(sparks.begin(), sparks.end(), [](const Spark& sp) { return sp.age >= 1.0f; }), sparks.end());
        for (auto& gl : stringGlow) gl *= 0.9f;
        const float ux = proc.uiStrum.load();
        int ns = 0;
        const uint64_t sLo = proc.stringBitsLo.load(), sHi = proc.stringBitsHi.load();
        for (int m = 0; m < 128; ++m) if ((m < 64 ? sLo >> m : sHi >> (m - 64)) & 1) ++ns;
        hoverString = ux < 0 || ns == 0 ? -1 : (int) std::lround(ux * (float) (ns - 1));
    }
    if (proc.page() != tab) showTab(proc.page());       // the host changed it (automation, a preset)
    if (tab == 2) {                                     // the pad that's droning stays lit
        litDrone = proc.droneDegree();
        for (int d = 0; d < pads.size(); ++d)
            if (pads[d]->lit != (d == litDrone)) { pads[d]->lit = d == litDrone; pads[d]->repaint(); }
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
