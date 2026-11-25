// Plays the seven chords through the engine at 48 kHz and reports level and timing.
#include <chrono>
#include <cmath>
#include <cstdio>
#include <thread>
#include "../Source/core/Engine.h"
using namespace brick;
int main() {
    NoteCache cache; Player eng(cache); eng.prepare(48000); eng.setKey(9, Scale::Minor);
    cache.setSound(0); auto t0 = std::chrono::steady_clock::now(); cache.want(eng.wanted());
    std::this_thread::sleep_for(std::chrono::milliseconds(1500));
    printf("ready after 1.5 s: %d notes\n", cache.ready());
    std::vector<float> L(512), R(512);
    for (int d = 0; d < 7; ++d) {
        Mods m; auto c = eng.playDegree(d, m);
        double s = 0; int N = 0; float pk = 0;
        for (int b = 0; b < 94; ++b) { std::fill(L.begin(), L.end(), 0.f); std::fill(R.begin(), R.end(), 0.f); eng.render(L.data(), R.data(), 512);
            for (int i = 0; i < 512; ++i) { s += L[i]*L[i] + R[i]*R[i]; N += 2; pk = std::max(pk, std::abs(L[i])); } }
        printf("%-5s rms %.3f peak %.3f ready %d\n", c.name.c_str(), std::sqrt(s / N), pk, cache.ready());
    }
    eng.release(); double s = 0;
    for (int b = 0; b < 200; ++b) { std::fill(L.begin(), L.end(), 0.f); std::fill(R.begin(), R.end(), 0.f); eng.render(L.data(), R.data(), 512); if (b > 180) for (float x : L) s += x*x; }
    printf("after release, last blocks rms %.6f\n", std::sqrt(s / (19*512)));
    auto ms = std::chrono::duration<double>(std::chrono::steady_clock::now() - t0).count();
    printf("all %d wanted notes ready? %d in %.1f s\n", (int) eng.wanted().size(), cache.ready(), ms);
}
