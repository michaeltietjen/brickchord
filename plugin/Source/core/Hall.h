// The plugin's reverb: an eight-line feedback delay network with input diffusion, damping and a
// little modulation, so long pads and glides get a smooth, wide tail instead of a metallic one.
// Space sets the decay (about 1.5 to 7.5 seconds) and the wet level.
#pragma once
#include <array>
#include <cmath>
#include <vector>

namespace brick {

class Hall {
public:
    void prepare(double sr) {
        sr_ = sr;
        static const double ms[8] = {31.7, 37.9, 41.3, 45.1, 53.9, 59.3, 67.7, 73.1};
        for (int i = 0; i < 8; ++i) {
            len_[i] = (int) (ms[i] * 0.001 * sr);
            line_[i].assign((size_t) len_[i] + 64, 0.0f);
            pos_[i] = 0; lp_[i] = 0;
        }
        static const double ap[4] = {4.77, 3.59, 12.73, 9.31};
        for (int i = 0; i < 4; ++i) { apLen_[i] = (int) (ap[i] * 0.001 * sr); apBuf_[i].assign((size_t) apLen_[i], 0.0f); apPos_[i] = 0; }
        pre_.assign((size_t) (0.025 * sr) + 1, 0.0f);
        preIdx_ = 0;
        ph_ = 0;
    }
    // space 0..1: decay and wet; adds the tail into L and R
    void process(float* L, float* R, int n, float space) {
        if (space <= 0.001f) return;
        const double rt60 = 1.5 + 6.0 * space;
        const float wet = 0.42f * space;
        float g[8];
        for (int i = 0; i < 8; ++i) g[i] = (float) std::pow(10.0, -3.0 * len_[i] / (rt60 * sr_));
        const float damp = 0.32f;                                   // a gentle low-pass in the loop: darker as it fades
        for (int s = 0; s < n; ++s) {
            float x = 0.5f * (L[s] + R[s]);
            pre_[(size_t) preIdx_] = x;                                 // pre-delay
            preIdx_ = (preIdx_ + 1) % (int) pre_.size();
            x = pre_[(size_t) preIdx_];
            for (int a = 0; a < 4; ++a) {                               // input diffusion: four all-passes
                float& d = apBuf_[a][(size_t) apPos_[a]];
                const float y = d - 0.6f * x;
                d = x + 0.6f * y;
                x = y;
                apPos_[a] = (apPos_[a] + 1) % apLen_[a];
            }
            ph_ += 2 * 3.14159265358979 * 0.3 / sr_;
            if (ph_ > 2 * 3.14159265358979) ph_ -= 2 * 3.14159265358979;
            float o[8], sum = 0;
            for (int i = 0; i < 8; ++i) {                               // read each line (two of them gently modulated)
                double rd = pos_[i] - len_[i] + (i == 2 ? 6.0 * std::sin(ph_) : (i == 5 ? 6.0 * std::cos(ph_ * 1.3) : 0.0));
                const int sz = (int) line_[i].size();
                while (rd < 0) rd += sz;
                const int k = (int) rd;
                const float fr = (float) (rd - k);
                o[i] = line_[i][(size_t) (k % sz)] * (1 - fr) + line_[i][(size_t) ((k + 1) % sz)] * fr;
                lp_[i] += (1 - damp) * (o[i] - lp_[i]);
                o[i] = lp_[i];
                sum += o[i];
            }
            const float h = sum * (2.0f / 8.0f);                        // Householder mixing: lossless, dense
            for (int i = 0; i < 8; ++i) {
                const int sz = (int) line_[i].size();
                line_[i][(size_t) pos_[i]] = (o[i] - h) * g[i] + x * 0.35f;
                pos_[i] = (pos_[i] + 1) % sz;
            }
            const float wl = (o[0] - o[2] + o[4] - o[6]) * 0.5f, wr = (o[1] - o[3] + o[5] - o[7]) * 0.5f;
            L[s] += wl * wet;
            R[s] += wr * wet;
        }
    }

private:
    double sr_ = 44100, ph_ = 0;
    std::array<std::vector<float>, 8> line_;
    std::array<int, 8> len_{}, pos_{};
    std::array<float, 8> lp_{};
    std::array<std::vector<float>, 4> apBuf_;
    std::array<int, 4> apLen_{}, apPos_{};
    std::vector<float> pre_;
    int preIdx_ = 0;
};

}  // namespace brick
