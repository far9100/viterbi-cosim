// viterbi_top.sv —— 合成用的 top。**沒有任何 debug port。**
//
// 為什麼 debug 訊號不從這裡出去：SystemVerilog 沒辦法「有條件地移除」一個 port，
// 只能停止驅動它。64 個 PM × W 位元就是 640 支腳，加上 survivor 與 bm 超過 700 支——
// 那些腳在 ORFS 會變成真實的 IO pad，一個 40 kGE 的核心配 700+ 支腳會變成
// pad-ring limited，量到的面積是垃圾。
//
// 改用 XMR：tb/dbg/viterbi_dbg.sv 從外面伸手進來拉 u_acs.pm_pk 等訊號。
// 模擬器會自動把 XMR 的目標標成 public（不需要 pragma，也不需要 --public-flat-rw
// ——後者會全域關掉最佳化）。Icarus 原生就解得開 XMR。
// 合成的 filelist 裡永遠不會有 tb/dbg/。
//
// （註：註解開頭不要寫模擬器的名字。Verilator 把 `// <它的名字> …` 當成 pragma 解析，
//  一句中文註解就會被當成不認識的 pragma 而報錯。第一版就踩到了。）
//
// ---- 架構 ----
//
//   full-parallel（PAR=32）：32 個 radix-2 butterfly，1 bit/cycle。
//   traceback 用 register exchange（uniform depth D，見 rtl/traceback.sv 的說明）。
//
// 折疊架構（8-way / 1-way）是 PPA 的比較點，屬於 M5；依 CLAUDE.md §4.1「MVP 先做對」，
// M3 只做 full-parallel，把整條驗證鏈路先打通。

`include "viterbi_defs.svh"

module viterbi_top #(
    parameter int Q     = 4,      // 軟值位元數
    parameter int W     = 10,     // path metric 字寬
    parameter int D     = 32,     // 回溯深度
    parameter int NINFO = 1024    // 每 frame 的資訊位元數
) (
    input  logic         clk,
    input  logic         rst,        // 同步 active-high
    input  logic         in_valid,   // 餵入一個 trellis stage
    input  logic [Q-1:0] r0,         // 量化後的無號軟值
    input  logic [Q-1:0] r1,
    output logic         out_valid,
    output logic         dec_bit,
    output logic         frame_done
);

    localparam int BM_W = Q + 1;

    logic                 stage_en, stage_done, flush_load, flush_en;
    logic [4*BM_W-1:0]    bm_pk;        // 架構狀態：bm[4]（組合）
    logic [4*BM_W-1:0]    bm_r;         // 打拍後與 pm/surv 對齊，給 C2 比對
    logic [NSTATES*W-1:0] pm_pk;        // 架構狀態：pm[64]（已 mod 2^W）
    logic [NSTATES-1:0]   surv_pk;      // 架構狀態：survivor[64]（打拍後，給 C2 比對）
    logic [NSTATES-1:0]   surv_comb_pk; // 同一個 stage 的組合值（給 traceback）
    logic [VM-1:0]        best;

    ctrl #(.D(D), .NINFO(NINFO)) u_ctrl (
        .clk (clk), .rst (rst), .in_valid (in_valid),
        .stage_en (stage_en), .stage_done (stage_done),
        .flush_load (flush_load), .flush_en (flush_en),
        .out_valid (out_valid), .frame_done (frame_done)
    );

    bmu #(.Q(Q)) u_bmu (
        .r0 (r0), .r1 (r1), .bm_pk (bm_pk)
    );

    // bm 要跟 pm / surv 對齊在同一個 stage 上，C2 才比得起來
    always_ff @(posedge clk) begin
        if (rst)              bm_r <= '0;
        else if (stage_en)    bm_r <= bm_pk;
    end

    acs_array #(.Q(Q), .W(W)) u_acs (
        .clk (clk), .rst (rst), .stage_en (stage_en),
        .bm_pk (bm_pk), .pm_pk (pm_pk),
        .surv_pk (surv_pk), .surv_comb_pk (surv_comb_pk)
    );

    minpm #(.W(W)) u_minpm (
        .pm_pk (pm_pk), .best (best)
    );

    // traceback 吃的是**組合**的 survivor：register exchange 的遞迴要用
    // 「這個 stage」的決策，而 surv_pk 是打拍後的（上一個 stage）。
    // 餵錯會讓 RE 整個錯開一格——見 rtl/acs_array.sv 底部的說明。
    traceback #(.D(D)) u_tb (
        .clk (clk), .rst (rst), .stage_en (stage_en),
        .flush_load (flush_load), .flush_en (flush_en),
        .surv_pk (surv_comb_pk), .best (best), .dec_bit (dec_bit)
    );

    // ---- G6：modulo normalization 的**決策等價**（模擬用的哨兵）----
    //
    // 用 immediate assertion 包在 always_ff 裡，**不用 bind、不用 concurrent SVA**：
    // Icarus 不支援 bind，兩個模擬器都不給可用的 concurrent SVA（修訂 B5）。
    // Yosys 用 -DSYNTHESIS 編譯，會整段跳過。
    //
    // ---- 為什麼不能只查 spread（第一版的錯誤）----
    //
    // 第一版養了一份影子 PM，但讓它**跟著 RTL 實際做出的決策走**，再量它的 spread。
    // 那是錯的，而且錯得很隱蔽：wraparound 一旦發生，RTL 會讓**所有**狀態都選到
    // 「錯的那條分支」，於是影子的所有 PM 都擠在一個很窄的帶子裡（Q=4/W=8 時是 181~211），
    // **spread 從來不會變大，assertion 從來不會響**。哨兵在量的是「解碼器實際走過的
    // 那些路徑之間的差距」——而那些路徑一起壞掉時，它們彼此看起來很一致。
    //
    // 正確的不變式（docs/wordlength_bound.md §5）是**決策等價**：
    // 影子必須自己做**無界的、正確的** ACS 決策，再去比對 RTL 的 survivor 是否相同。
    // 這與 golden model 的 pm_mod / pm_ref 雙軌是同一件事。
`ifndef SYNTHESIS
    int  pm_ref      [NSTATES];    // 無界的參考 path metric
    int  pm_ref_next [NSTATES];
    logic [NSTATES-1:0] surv_ref;  // 由無界算術導出的 survivor
    int  g6_bx, g6_bxc, g6_a, g6_b;
    int  g6_stage;
    int  g6_min, g6_max, g6_spread;

    // Icarus 不支援在 always 區塊裡宣告 automatic 變數，所以暫存值提到模組層級。
    localparam int LAM_I = 2 * ((1 << Q) - 1);
    localparam int PMI_I = 6 * LAM_I + 1;

    always_ff @(posedge clk) begin
        if (rst) begin
            for (int s = 0; s < NSTATES; s++) pm_ref[s] <= (s == 0) ? 0 : PMI_I;
            g6_stage <= 0;
        end else if (stage_en) begin
            for (int j = 0; j < NBFLY; j++) begin
                g6_bx  = int'(bm_pk[venc(1'b0, VM'(j)) * BM_W +: BM_W]);
                g6_bxc = LAM_I - g6_bx;

                // 進入 2j（u=0）：影子自己做決策，**不看 RTL 的**
                g6_a = pm_ref[j]         + g6_bx;
                g6_b = pm_ref[j + NBFLY] + g6_bxc;
                surv_ref[2*j]        = (g6_a <= g6_b) ? 1'b0 : 1'b1;   // 平手選 A
                pm_ref_next[2*j]     = (g6_a <= g6_b) ? g6_a : g6_b;

                // 進入 2j+1（u=1）
                g6_a = pm_ref[j]         + g6_bxc;
                g6_b = pm_ref[j + NBFLY] + g6_bx;
                surv_ref[2*j + 1]    = (g6_a <= g6_b) ? 1'b0 : 1'b1;
                pm_ref_next[2*j + 1] = (g6_a <= g6_b) ? g6_a : g6_b;
            end
            for (int s = 0; s < NSTATES; s++) pm_ref[s] <= pm_ref_next[s];

            // 實測的 PM spread（畫「實測 Δ_max vs 最壞界」那張圖的資料）
            g6_min = pm_ref_next[0];
            g6_max = pm_ref_next[0];
            for (int s = 1; s < NSTATES; s++) begin
                if (pm_ref_next[s] < g6_min) g6_min = pm_ref_next[s];
                if (pm_ref_next[s] > g6_max) g6_max = pm_ref_next[s];
            end
            g6_spread = g6_max - g6_min;

            // **G6 的定義：決策等價。** modulo 算術導出的 survivor 必須等於無界算術導出的。
            //
            // G6_OFF 這個 define 存在的理由：assertion 一響，模擬就中止（Verilator 5.x
            // 連沒有 --assert 都會執行 immediate assertion，然後 $stop）。
            // 但在不安全格點上，我們**同時**想證明兩件事：
            //   (a) G6 會響（開著 assertion 跑）
            //   (b) C2 仍然零 mismatch —— RTL 與 golden 會「錯得一模一樣」（關掉 assertion 跑完）
            // (b) 本身就是 C2 有效性的強力佐證：連在壞掉的字寬下，兩邊的每一個 bit 都相同。
`ifndef G6_OFF
            assert (surv_comb_pk == surv_ref)
                else $error("G6 violated @ stage %0d: survivor mismatch (mod=%h ref=%h), PM spread=%0d, 2^(W-1)=%0d (Q=%0d W=%0d)",
                            g6_stage, surv_comb_pk, surv_ref, g6_spread,
                            (1 << (W - 1)), Q, W);
`endif

            g6_stage <= g6_stage + 1;
        end
    end
`endif

endmodule
