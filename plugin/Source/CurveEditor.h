// The MPE editor: draw how a glide travels. Three lanes (Pitch, Pressure, Timbre), for all the
// voices at once or one voice at a time. Pick a shape for a quick start, drag the points to make
// it yours. Editing a lane turns it on (the Custom path, or that lane as the pressure / timbre
// source), so what you draw is what you hear.
#pragma once
#include <juce_audio_processors/juce_audio_processors.h>
#include "core/Glide.h"

class CurveEditor : public juce::Component {
public:
    CurveEditor(brick::GlideEngine& g, juce::AudioProcessorValueTreeState& p) : glide(g), params(p) {}
    std::function<void()> onEdit;                          // the page refreshes its menus

    void paint(juce::Graphics& g) override {
        using namespace juce;
        const Colour bg(0xff0b0a12), line(0xff37344a), text(0xff9d9ab0), orange(0xffb9a6ff), cream(0xffece4d6);
        g.setColour(Colour(0xff37344a));
        g.fillRoundedRectangle(getLocalBounds().toFloat(), 16);
        g.setColour(bg);
        g.fillRoundedRectangle(getLocalBounds().toFloat().reduced(1), 15);
        chips.clear();
        auto top = getLocalBounds().reduced(18, 14).removeFromTop(26);
        g.setFont(FontOptions(13.f));
        auto chip = [&](Rectangle<int>& row, const String& label, int kind, int value, bool on, Colour c, bool fromRight = false) {
            const int w = GlyphArrangement::getStringWidthInt(g.getCurrentFont(), label) + 18;
            auto r = fromRight ? row.removeFromRight(w) : row.removeFromLeft(w);
            if (fromRight) row.removeFromRight(5); else row.removeFromLeft(5);
            g.setColour(on ? c : line);
            g.fillRoundedRectangle(r.toFloat(), 6);
            g.setColour(on ? bg : text);
            g.drawText(label, r, Justification::centred);
            chips.push_back({r, kind, value});
        };
        static const char* lanes[] = {"Pitch", "Pressure", "Timbre"};
        for (int l = 0; l < 3; ++l) chip(top, lanes[l], 0, l, lane == l, orange);
        top.removeFromLeft(12);
        chip(top, "All", 1, -1, voice < 0, cream);
        for (int v = 0; v < 5; ++v) chip(top, String(v + 1), 1, v, voice == v, voiceColour(v));
        chip(top, "Reset", 3, 0, false, cream, true);
        const auto& sh = shapes(lane);
        for (int i = (int) sh.size() - 1; i >= 0; --i) chip(top, sh[(size_t) i], 2, i, false, cream, true);

        plot = getLocalBounds().reduced(30, 14).withTrimmedTop(40).withTrimmedBottom(18).toFloat();
        const float lo = brick::GlideCurves::minY(lane), hi = brick::GlideCurves::maxY(lane);
        auto yOf = [&](float v) { return plot.getBottom() - (v - lo) / (hi - lo) * plot.getHeight(); };
        auto xOf = [&](double p) { return plot.getX() + (float) p * plot.getWidth(); };
        g.setFont(FontOptions(11.f));
        auto guide = [&](float v, const String& label) {
            g.setColour(line);
            g.drawHorizontalLine((int) yOf(v), plot.getX(), plot.getRight());
            g.setColour(text);
            g.drawText(label, Rectangle<float>(plot.getX() + 4, yOf(v) - 14, 160, 12), Justification::left);
        };
        if (lane == brick::LanePitch) { guide(0, "the old note"); guide(1, "the new note"); }
        else if (lane == brick::LanePressure) { guide(0, "none"); guide(1, "full pressure"); }
        else { guide(0, "dark"); guide(0.5f, "centre"); guide(1, "bright"); }
        g.setColour(text);
        g.drawText("glide starts", Rectangle<float>(plot.getX(), plot.getBottom() + 3, 120, 12), Justification::left);
        g.drawText("arrives", Rectangle<float>(plot.getRight() - 120, plot.getBottom() + 3, 120, 12), Justification::right);
        for (int k = 0; k < brick::kCurvePts; ++k) {
            g.setColour(line.withAlpha(0.5f));
            g.drawVerticalLine((int) xOf((double) k / (brick::kCurvePts - 1)), plot.getY(), plot.getBottom());
        }
        auto draw = [&](int v, Colour c, float width) {
            Path p;
            for (int s = 0; s <= 160; ++s) {
                const double t = s / 160.0;
                const float y = yOf(glide.curves.at(lane, v, t));
                if (s == 0) p.startNewSubPath(xOf(t), y); else p.lineTo(xOf(t), y);
            }
            g.setColour(c);
            g.strokePath(p, PathStrokeType(width));
        };
        if (voice < 0) {                                    // all: the others faint behind, in case they differ
            for (int v = 4; v >= 1; --v) draw(v, voiceColour(v).withAlpha(0.25f), 1.5f);
            draw(0, orange, 2.8f);
        } else {
            for (int v = 0; v < 5; ++v) if (v != voice) draw(v, voiceColour(v).withAlpha(0.22f), 1.5f);
            draw(voice, voiceColour(voice), 2.8f);
        }
        const int ev = voice < 0 ? 0 : voice;
        for (int k = 0; k < brick::kCurvePts; ++k) {
            const float x = xOf((double) k / (brick::kCurvePts - 1)), y = yOf(glide.curves.y[lane][ev][k]);
            g.setColour(bg);
            g.fillEllipse(x - 7, y - 7, 14, 14);
            g.setColour(k == dragging ? cream : (voice < 0 ? orange : voiceColour(voice)));
            g.drawEllipse(x - 6, y - 6, 12, 12, 2.2f);
        }
        for (int v = 0; v < 5; ++v) {                       // where each gliding voice is, right now
            const float p = glide.progress[(size_t) v];
            if (p <= 0.0f || p >= 1.0f || !glide.on[(size_t) v]) continue;
            g.setColour(voiceColour(v));
            g.fillEllipse(xOf(p) - 4, yOf(glide.curves.at(lane, v, p)) - 4, 8, 8);
        }
    }

    void mouseDown(const juce::MouseEvent& e) override {
        for (auto& c : chips)
            if (c.r.contains(e.getPosition())) {
                if (c.kind == 0) lane = c.value;
                else if (c.kind == 1) voice = c.value;
                else if (c.kind == 2) { applyShape(c.value); engage(); }
                else { forVoices([&](int v) { glide.curves.reset(lane, v); }); }
                repaint();
                if (onEdit) onEdit();
                return;
            }
        dragging = -1;
        const int k = juce::roundToInt((e.position.x - plot.getX()) / plot.getWidth() * (brick::kCurvePts - 1));
        if (k >= 0 && k < brick::kCurvePts && plot.expanded(12).contains(e.position)) { dragging = k; mouseDrag(e); engage(); if (onEdit) onEdit(); }
    }
    void mouseDrag(const juce::MouseEvent& e) override {
        if (dragging < 0) return;
        const float lo = brick::GlideCurves::minY(lane), hi = brick::GlideCurves::maxY(lane);
        float v = lo + (plot.getBottom() - e.position.y) / plot.getHeight() * (hi - lo);
        if (lane == brick::LanePitch) for (float snap : {0.0f, 1.0f}) if (std::abs(v - snap) < 0.03f) v = snap;   // the notes themselves
        v = juce::jlimit(lo, hi, v);
        const int k = dragging;
        forVoices([&](int vv) { glide.curves.y[lane][vv][k] = v; });
        repaint();
    }
    void mouseUp(const juce::MouseEvent&) override { dragging = -1; repaint(); }

    static juce::Colour voiceColour(int v) {
        static const juce::Colour c[] = {juce::Colour(110, 200, 190), juce::Colour(190, 140, 255), juce::Colour(255, 170, 110),
                                         juce::Colour(120, 200, 140), juce::Colour(255, 120, 160), juce::Colour(140, 170, 255)};
        return c[v % 6];
    }

private:
    struct Chip { juce::Rectangle<int> r; int kind, value; };
    brick::GlideEngine& glide;
    juce::AudioProcessorValueTreeState& params;
    std::vector<Chip> chips;
    juce::Rectangle<float> plot;
    int lane = 0, voice = -1, dragging = -1;

    template <typename F> void forVoices(F f) {            // All: every voice (and the sub); one: just it
        if (voice < 0) for (int v = 0; v < brick::kCurveVoices; ++v) f(v); else f(voice);
    }
    static const std::vector<juce::String>& shapes(int lane) {
        static const std::vector<juce::String> s[] = {{"Ease", "Linear", "Late", "Snap", "Over", "Bounce", "Stairs"},
                                                      {"Full", "Fade in", "Dip", "Swell", "Fade out"},
                                                      {"Centre", "Open", "Close", "Peak", "Dip"}};
        return s[lane];
    }
    void applyShape(int i) {
        const float pi = 3.14159265f;
        for (int k = 0; k < brick::kCurvePts; ++k) {
            const float p = (float) k / (brick::kCurvePts - 1), e = p * p * (3 - 2 * p);
            float v = 0;
            if (lane == brick::LanePitch) {
                const float q5 = std::max(0.0f, (p - 0.6f) / 0.4f), q6 = std::min(1.0f, p / 0.3f);
                switch (i) {
                    case 0: v = e; break;
                    case 1: v = p; break;
                    case 2: v = q5 * q5 * (3 - 2 * q5); break;
                    case 3: v = q6 * q6 * (3 - 2 * q6); break;
                    case 4: v = e + 0.35f * std::sin(pi * p) * p; break;
                    case 5: v = 1.0f - std::pow(1.0f - p, 3.0f) * std::cos(3.0f * pi * p); break;
                    default: v = std::floor(p * 4.0f + 0.001f) / 4.0f; break;
                }
            } else if (lane == brick::LanePressure) {
                switch (i) {
                    case 0: v = 1; break;
                    case 1: v = 0.15f + 0.85f * e; break;
                    case 2: v = 1 - 0.7f * std::sin(pi * p); break;
                    case 3: v = 0.45f + 0.55f * std::sin(pi * p); break;
                    default: v = 1 - 0.85f * e; break;
                }
            } else {
                switch (i) {
                    case 0: v = 0.5f; break;
                    case 1: v = 0.15f + 0.85f * e; break;
                    case 2: v = 1 - 0.85f * e; break;
                    case 3: v = 0.5f + 0.5f * std::sin(pi * p); break;
                    default: v = 0.5f - 0.45f * std::sin(pi * p); break;
                }
            }
            forVoices([&](int vv) { glide.curves.y[lane][vv][k] = v; });
        }
    }
    void engage() {                                         // what you draw is what you hear
        auto set = [&](const char* id, float index) {
            if (auto* p = params.getParameter(id))
                if (std::abs(p->convertFrom0to1(p->getValue()) - index) > 0.5f) p->setValueNotifyingHost(p->convertTo0to1(index));
        };
        if (lane == brick::LanePitch) set("glidepath", (float) brick::kPathCustom);
        else if (lane == brick::LanePressure) set("glideprsrc", 2);
        else set("glidetbsrc", 1);
    }
};
