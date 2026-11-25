// Renders every sound at C4 and prints RMS of its attack and loop, to compare with
// brickchord/synth.py (tests/render_check.py runs both).
#include <cmath>
#include <cstdio>
#include "../Source/core/PatchData.h"
#include "../Source/core/Render.h"
#include "../Source/core/Theory.h"
using namespace brick;
static double rms(const std::vector<float>& v) { double s = 0; for (float x : v) s += (double) x * x; return v.empty() ? 0 : std::sqrt(s / v.size()); }
int main(int argc, char** argv) {
    int midi = argc > 1 ? atoi(argv[1]) : 60;
    for (int i = 0; i < kNumPatches; ++i) {
        auto n = renderNote(midi, kPatches[i]);
        printf("%s|%d|%d|%.5f|%.5f\n", kPatches[i].name, n->attackFrames(), n->loopFrames(), rms(n->attack), rms(n->loop));
    }
    std::vector<int> prev;
    for (int d = 0; d < 7; ++d) {
        Mods m; auto c = buildChord(9, Scale::Minor, d, m); auto v = voice(c.root, c.iv, prev);
        printf("chord|%s|%s|", c.name.c_str(), romanFor(d, c.iv).c_str());
        for (int x : v) printf("%d ", x);
        printf("\n");
    }
}
