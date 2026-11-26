// Bricklab Studio: the chord theory of brickchord/theory.py, line for line.
#pragma once
#include <algorithm>
#include <array>
#include <cmath>
#include <cstdlib>
#include <string>
#include <vector>

namespace brick {

struct Mods { bool flip = false, seventh = false, sus = false, ninth = false, sus2 = false, dim = false, aug = false, maj7 = false; };

enum class Scale { Major, Minor, Dorian, Mixolydian, Lydian, Phrygian, Locrian, HarmonicMinor, MelodicMinor };
constexpr int kNumScales = 9;
inline const char* const kScaleNames[] = {"Major", "Minor", "Dorian", "Mixolydian", "Lydian", "Phrygian", "Locrian",
                                          "Harmonic minor", "Melodic minor"};
inline const char* scaleName(Scale s) { return kScaleNames[(int) s]; }
inline const std::array<int, 7>& scaleSteps(Scale s) {
    static const std::array<int, 7> t[] = {{0, 2, 4, 5, 7, 9, 11}, {0, 2, 3, 5, 7, 8, 10},
                                           {0, 2, 3, 5, 7, 9, 10}, {0, 2, 4, 5, 7, 9, 10},
                                           {0, 2, 4, 6, 7, 9, 11}, {0, 1, 3, 5, 7, 8, 10},
                                           {0, 1, 3, 5, 6, 8, 10}, {0, 2, 3, 5, 7, 8, 11},
                                           {0, 2, 3, 5, 7, 9, 11}};
    return t[(int) s];
}

inline std::string noteName(int pc, int key = -1, Scale scale = Scale::Major) {
    static const char* sharp[] = {"C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"};
    static const char* flat[] = {"C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B"};
    pc = ((pc % 12) + 12) % 12;
    if (key >= 0) {
        static const int parentOf[] = {0, 3, 10, 5, 7, 8, 1, 3, 3};   // the major key each scale's spelling follows
        int parent = (key + parentOf[(int) scale]) % 12;
        if (parent == 5 || parent == 10 || parent == 3 || parent == 8 || parent == 1 || parent == 6) return flat[pc];
    }
    return sharp[pc];
}

inline bool has(const std::vector<int>& iv, int x) {
    for (int i : iv) if (((i % 12) + 12) % 12 == x) return true;
    return false;
}

inline std::string chordName(int pc, const std::vector<int>& iv, bool sus, bool sus2, int key, Scale scale) {
    int third = (has(iv, 3) && !sus) ? 3 : (has(iv, 4) ? 4 : -1);
    int fifth = has(iv, 6) ? 6 : (has(iv, 8) ? 8 : 7);
    bool has7 = has(iv, 10) || has(iv, 11), maj7 = has(iv, 11), has9 = has(iv, 2) && !sus2;
    std::string n = noteName(pc, key, scale);
    if (sus2) return n + (maj7 ? "maj7sus2" : (has7 ? "7sus2" : "sus2"));
    if (sus) return n + (has9 ? "9sus4" : (has7 ? "7sus4" : "sus4"));
    if (third == 4 && fifth == 8) return n + (maj7 ? "augMaj7" : (has7 ? "aug7" : "aug"));
    if (third == 3 && fifth == 6) return has7 ? n + (maj7 ? "mMaj7b5" : "m7b5") : n + "dim";
    std::string base = third == 3 ? "m" : "";
    if (has9) return base.empty() ? n + (maj7 ? "maj9" : "9") : n + (maj7 ? "mMaj9" : "m9");
    if (has7) return base == "m" ? n + (maj7 ? "mMaj7" : "m7") : n + (maj7 ? "maj7" : "7");
    return n + base;
}

struct Chord { int root = 0; std::vector<int> iv; std::string name; };

inline Chord buildChord(int key, Scale scale, int degree, const Mods& m) {
    const auto& sc = scaleSteps(scale);
    auto tone = [&](int i) { return sc[(degree + i) % 7] + 12 * ((degree + i) / 7); };
    int root = tone(0), third = tone(2) - root, fifth = tone(4) - root, sev = tone(6) - root;
    if (m.flip) {
        third = third == 4 ? 3 : 4;
        if (fifth == 6) fifth = 7;
        sev = (sev == 11 || third == 3) ? 10 : sev;
    }
    if (m.dim) { third = 3; fifth = 6; sev = 10; }
    if (m.aug) { third = 4; fifth = 8; }
    if (m.maj7) sev = 11;
    std::vector<int> iv{0, third, fifth};
    bool sus = m.sus, sus2 = m.sus2 && !sus;
    if (sus) iv[1] = 5; else if (sus2) iv[1] = 2;
    if (m.seventh || m.ninth || m.maj7) iv.push_back(sev);
    if (m.ninth) iv.push_back(14);
    Chord c;
    c.root = (key + root) % 12;
    c.iv = iv;
    c.name = chordName(c.root, iv, sus, sus2, key, scale);
    return c;
}

inline std::string romanFor(int degree, const std::vector<int>& iv) {
    static const char* R[] = {"I", "II", "III", "IV", "V", "VI", "VII"};
    std::string r = R[degree % 7];
    if (has(iv, 3) && !has(iv, 5)) for (auto& ch : r) ch = (char) std::tolower(ch);
    if (has(iv, 6) && !has(iv, 7)) r += "\xC2\xB0";
    return r;
}

// The chord buttons' voicing: the bass, then each chord tone nearest the last chord's
// centre, kept between G3 and G5 (theory.voice). Returns the notes; prev becomes upper.
inline std::vector<int> voice(int pcRoot, const std::vector<int>& iv, std::vector<int>& prev, int octave = 0) {
    int bass = 36 + pcRoot;
    if (bass < 40) bass += 12;
    double center = 64;
    if (!prev.empty()) { double s = 0; for (int p : prev) s += p; center = s / prev.size(); }
    std::vector<int> upper;
    for (int i : iv) {
        int pc = (pcRoot + i) % 12, best = -1;
        double bd = 1e9;
        for (int o = 3; o < 8; ++o) {
            int m = pc + 12 * o;
            double d = std::abs(m - center);
            if (d < bd || (d == bd && m < best)) { bd = d; best = m; }
        }
        best = std::clamp(best, 55, 79);
        if (std::find(upper.begin(), upper.end(), best) == upper.end()) upper.push_back(best);
    }
    std::sort(upper.begin(), upper.end());
    prev = upper;
    std::vector<int> out{bass + 12 * octave};
    for (int u : upper) out.push_back(u + 12 * octave);
    return out;
}

}  // namespace brick
