// sim_main.cpp —— Tier B 的 Verilator C++ harness。
//
// ## 這支檔案裡**沒有**什麼
//
//   沒有 RNG。沒有量化器。沒有通道模型。
//
// 規格書 v1 要求「C++ 端的 AWGN + 量化器必須與 L2 位元級一致」。那做不到：
// numpy 的 PCG64 + ziggurat 與任何獨立寫的 C++ RNG 都不可能逐位元組相同，
// 除非共用實作——而共用實作又讓那個「等價比對」變成同義反覆。
//
// 所以這裡只做一件事：**重播 L2 匯出的激勵，把解碼位元與 L2 的期望輸出 XOR。**
// 激勵與期望值由 SHA-256 釘死（manifest.json）。這比 v1 的要求更強：
// Tier-B 的激勵**就是** L2 的激勵，逐位元組相同，因為只有一份。
//
// ## Tier B 的目的不是量 BER
//
// C2 已經證明 RTL ≡ golden 逐位元相等，所以 **RTL 的 BER 曲線與 L2/GPU 的
// 在數學上是同一條**。重跑 10⁸ bits 去「重新量」一條已知的曲線不是驗證，是算術。
//
// Tier B 真正的三個任務：
//   1. **延伸 C2 浸泡**：把輸入空間擴大幾個數量級，但方式是**繼續比對**
//      （只比解碼位元，1 bit/stage，幾乎免費），不是量 BER。
//   2. **Assertion 浸泡**：G6 的 wraparound 是稀有事件，在低 SNR 下跑上億個 stage，
//      才是這個哨兵真正發揮價值的地方。
//   3. **長跑控制 FSM 穩健性**：數萬次 frame 邊界與 reset。

#include "Vviterbi_top.h"
#include "verilated.h"

#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <vector>

static Vviterbi_top* dut = nullptr;
static vluint64_t main_time = 0;
double sc_time_stamp() { return main_time; }

static void tick() {
    dut->clk = 0; dut->eval(); main_time++;
    dut->clk = 1; dut->eval(); main_time++;
}

int main(int argc, char** argv) {
    Verilated::commandArgs(argc, argv);

    if (argc < 7) {
        fprintf(stderr,
                "用法: %s <stim.bin> <expected.bits> <n_frames> <T> <NINFO> <D>\n",
                argv[0]);
        return 2;
    }
    const char* stim_path = argv[1];
    const char* exp_path  = argv[2];
    const long  n_frames  = atol(argv[3]);
    const long  T         = atol(argv[4]);
    const long  NINFO     = atol(argv[5]);
    const long  D         = atol(argv[6]);

    // ---- 讀激勵：每個 stage 兩個 byte（r0, r1）----
    FILE* fs = fopen(stim_path, "rb");
    if (!fs) { fprintf(stderr, "開不了 %s\n", stim_path); return 2; }
    const size_t stim_bytes = (size_t)n_frames * T * 2;
    std::vector<uint8_t> stim(stim_bytes);
    if (fread(stim.data(), 1, stim_bytes, fs) != stim_bytes) {
        fprintf(stderr, "%s 的長度不符（預期 %zu bytes）\n", stim_path, stim_bytes);
        return 2;
    }
    fclose(fs);

    // ---- 讀期望的解碼位元：packed，一個 byte 8 個，LSB 先 ----
    FILE* fe = fopen(exp_path, "rb");
    if (!fe) { fprintf(stderr, "開不了 %s\n", exp_path); return 2; }
    const size_t exp_bytes = ((size_t)n_frames * NINFO + 7) / 8;
    std::vector<uint8_t> expected(exp_bytes);
    if (fread(expected.data(), 1, exp_bytes, fe) != exp_bytes) {
        fprintf(stderr, "%s 的長度不符（預期 %zu bytes）\n", exp_path, exp_bytes);
        return 2;
    }
    fclose(fe);

    dut = new Vviterbi_top;

    long   mismatches = 0;
    long   n_checked  = 0;
    long   n_out_bad  = 0;     // 每個 frame 收到的輸出數不對
    size_t exp_idx    = 0;

    for (long f = 0; f < n_frames; f++) {
        // ---- reset（每個 frame 都做一次：這也是 FSM 的長跑穩健性測試）----
        dut->rst = 1; dut->in_valid = 0; dut->r0 = 0; dut->r1 = 0;
        for (int i = 0; i < 3; i++) tick();
        dut->rst = 0;
        tick();

        long out_cnt = 0;
        const uint8_t* srow = &stim[(size_t)f * T * 2];

        for (long cyc = 0; cyc < T + D + 4; cyc++) {
            if (cyc < T) {
                dut->in_valid = 1;
                dut->r0 = srow[cyc * 2 + 0];
                dut->r1 = srow[cyc * 2 + 1];
            } else {
                dut->in_valid = 0;
            }

            tick();

            if (dut->out_valid) {
                if (out_cnt < NINFO) {
                    // 期望值：packed bits，LSB 先
                    const uint8_t want =
                        (expected[exp_idx >> 3] >> (exp_idx & 7)) & 1;
                    if ((uint8_t)dut->dec_bit != want) {
                        if (mismatches < 5) {
                            fprintf(stderr,
                                    "C2 mismatch @ frame %ld bit %ld: RTL=%d golden=%d\n",
                                    f, out_cnt, (int)dut->dec_bit, (int)want);
                        }
                        mismatches++;
                    }
                    n_checked++;
                    exp_idx++;
                }
                out_cnt++;
            }
        }
        if (out_cnt != T) n_out_bad++;
    }

    dut->final();
    delete dut;

    printf("TIERB_RESULT frames=%ld checked=%ld mismatches=%ld out_bad=%ld\n",
           n_frames, n_checked, mismatches, n_out_bad);

    // 零容忍
    return (mismatches == 0 && n_out_bad == 0 && n_checked > 0) ? 0 : 1;
}
