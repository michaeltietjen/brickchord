// The MPE editor's curves: for each Glide voice, how a glide travels (Pitch: 0 the old note, 1 the
// new one, overshoot allowed), and how its Pressure and Timbre move over the glide (0..1). Nine
// points each, evenly spaced through the glide, joined smoothly. The page edits them; the audio
// thread reads them (plain atomics, no locks).
#pragma once
#include <algorithm>
#include <array>
#include <atomic>
#include <cmath>
#include <sstream>
#include <string>

namespace brick {

constexpr int kCurvePts = 9, kCurveVoices = 6;
enum Lane { LanePitch, LanePressure, LaneTimbre, kNumLanes };

struct GlideCurves {
    std::atomic<float> y[kNumLanes][kCurveVoices][kCurvePts];
    GlideCurves() { for (int l = 0; l < kNumLanes; ++l) for (int v = 0; v < kCurveVoices; ++v) reset(l, v); }
    static float minY(int lane) { return lane == LanePitch ? -0.25f : 0.0f; }
    static float maxY(int lane) { return lane == LanePitch ? 1.25f : 1.0f; }
    void reset(int lane, int voice) {
        for (int k = 0; k < kCurvePts; ++k) {
            const float p = (float) k / (kCurvePts - 1);
            y[lane][voice][k] = lane == LanePitch ? p * p * (3 - 2 * p) : (lane == LanePressure ? 1.0f : 0.5f);
        }
    }
    float at(int lane, int voice, double p) const {         // Catmull-Rom through the points
        p = std::clamp(p, 0.0, 1.0) * (kCurvePts - 1);
        const int i = std::min(kCurvePts - 2, (int) p);
        const float t = (float) (p - i);
        auto pt = [&](int k) { return y[lane][voice][std::clamp(k, 0, kCurvePts - 1)].load(std::memory_order_relaxed); };
        const float p0 = pt(i - 1), p1 = pt(i), p2 = pt(i + 1), p3 = pt(i + 2);
        const float v = 0.5f * ((2 * p1) + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t * t + (-p0 + 3 * p1 - 3 * p2 + p3) * t * t * t);
        return std::clamp(v, minY(lane), maxY(lane));
    }
    std::string toString() const {
        std::ostringstream o;
        for (int l = 0; l < kNumLanes; ++l) for (int v = 0; v < kCurveVoices; ++v) for (int k = 0; k < kCurvePts; ++k) o << y[l][v][k].load() << ' ';
        return o.str();
    }
    void fromString(const std::string& s) {
        std::istringstream in(s);
        for (int l = 0; l < kNumLanes; ++l) for (int v = 0; v < kCurveVoices; ++v) for (int k = 0; k < kCurvePts; ++k) {
            float f;
            if (!(in >> f)) return;
            y[l][v][k] = std::clamp(f, minY(l), maxY(l));
        }
    }
};

}  // namespace brick
