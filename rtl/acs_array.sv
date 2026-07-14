// acs_array.sv —— 32 個 butterfly + PM 暫存器檔。
//
// **禁止 in-place / shuffle-exchange 的 butterfly 技巧**（把 butterfly j 的輸出存回
// j 與 j+32、並隱含一個 per-stage 的狀態重新標號）。它省掉一組雙緩衝，
// 但摧毀了 pm[64] 這個「架構狀態」的穩定定義——而 C2 比對的正是那個東西。
// 全平行（PAR=32）時所有 butterfly 在同一個時脈邊緣讀舊值、寫新值，本來就沒有 hazard，
// 也不需要雙緩衝。
//
// 這個模組 materialize 出三個打包好的架構狀態向量（pm_pk / surv_pk / bm_pk）。
// 它們**本來就存在**，把它們接成連續的 wire 不花任何成本；
// tb/dbg/viterbi_dbg.sv 用 XMR 從這裡拉出去給 cocotb 比對，
// 所以 viterbi_top 上**不需要任何 debug port**——那很重要，
// 861 支輸出腳會讓 ORFS 量到的面積變成垃圾（pad-ring limited）。

`include "viterbi_defs.svh"

module acs_array #(
    parameter int Q = 4,
    parameter int W = 10
) (
    input  logic                    clk,
    input  logic                    rst,          // 同步 active-high
    input  logic                    stage_en,     // 這個 cycle 推進一個 trellis stage
    input  logic [4*(Q+1)-1:0]      bm_pk,
    output logic [NSTATES*W-1:0]    pm_pk,        // 架構狀態：pm[64]（已 mod 2^W）
    output logic [NSTATES-1:0]      surv_pk,      // 架構狀態：survivor[64]（**打拍後**）
    output logic [NSTATES-1:0]      surv_comb_pk  // 同一個 stage 的組合值（給 traceback）
);

    localparam int BM_W = Q + 1;
    localparam logic [BM_W-1:0] LAM = BM_W'(2 * ((1 << Q) - 1));   // λ_max

    // PM_INIT = 6·λ_max + 1（docs/wordlength_bound.md §2）。
    // 假起始狀態的路徑必須永遠贏不了：m = 6 步之後任何狀態都能從狀態 0 抵達，
    // 在那之前合法路徑最壞累積 t·λ_max，所以 PM_INIT > 6·λ_max 就夠了。
    //
    // 注意 PM_INIT 未必放得下 W bits（Q=6 時是 757，W=8 只能存到 255）——
    // 那正是「不安全格點」的定義，不是 bug。截斷後的值就是 RTL 真正會存的東西。
    localparam int PM_INIT_FULL = 6 * (2 * ((1 << Q) - 1)) + 1;
    localparam logic [W-1:0] PM_INIT = W'(PM_INIT_FULL);

    logic [W-1:0] pm      [NSTATES];
    logic [W-1:0] pm_next [NSTATES];
    logic         surv    [NSTATES];

    // ---- 32 個 butterfly ----
    genvar j;
    generate
        for (j = 0; j < NBFLY; j++) begin : g_bfly
            // X = c(j, 0)：由 venc() 在 elaboration 時從八進位多項式推導，
            // **不是**從 L2 抄過來的表。
            localparam logic [NOUT-1:0] X = venc(1'b0, VM'(j));

            logic [BM_W-1:0] bm_x;
            assign bm_x = bm_pk[X*BM_W +: BM_W];

            acs_butterfly #(.W(W), .BM_W(BM_W)) u_b (
                .pm_a      (pm[j]),
                .pm_b      (pm[j + NBFLY]),
                .bm_x      (bm_x),
                .lam       (LAM),
                .pm_even   (pm_next[2*j]),
                .pm_odd    (pm_next[2*j + 1]),
                .surv_even (surv[2*j]),
                .surv_odd  (surv[2*j + 1])
            );
        end
    endgenerate

    // ---- PM 暫存器檔 ----
    //
    // 迴圈變數必須在每個 always 區塊裡各自宣告（`for (int s = ...)`），
    // 不能共用一個模組層級的 integer —— 那會被 Verilator 判成 MULTIDRIVEN
    // （同一個變數被兩個 process 寫），而且那個警告是對的：共用的迴圈變數
    // 在模擬語意上確實是兩個 process 在寫同一個東西。
    always_ff @(posedge clk) begin
        if (rst) begin
            for (int s = 0; s < NSTATES; s++)
                pm[s] <= (s == 0) ? W'(0) : PM_INIT;
        end else if (stage_en) begin
            for (int s = 0; s < NSTATES; s++)
                pm[s] <= pm_next[s];
        end
    end

    // survivor 要跟著 PM 一起被暫存，這樣 C2 比對時 bm / pm / surv 三者對齊在同一個 stage
    logic [NSTATES-1:0] surv_r;
    always_ff @(posedge clk) begin
        if (rst) begin
            surv_r <= '0;
        end else if (stage_en) begin
            for (int s = 0; s < NSTATES; s++) surv_r[s] <= surv[s];
        end
    end

    // ---- 打包出架構狀態 ----
    genvar g;
    generate
        for (g = 0; g < NSTATES; g++) begin : g_pack
            assign pm_pk[g*W +: W]  = pm[g];
            assign surv_comb_pk[g]  = surv[g];
        end
    endgenerate
    assign surv_pk = surv_r;

    // 為什麼要吐**兩份** survivor：
    //
    //   surv_pk（打拍後）  給 C2 比對用。它與 pm_pk 對齊在同一個 stage 上，
    //                      cocotb 在 stage_done 的脈衝上一次讀齊 bm / pm / surv。
    //
    //   surv_comb_pk（組合）給 traceback 用。register exchange 的遞迴是
    //                      RE[s'] <= (RE[pred(s')] << 1) | (s' & 1)，
    //                      而 pred(s') 要用**這個 stage** 的 survivor。
    //
    // 第一版把打拍後的那份餵給 traceback，於是 RE 跟著**上一個 stage** 的決策走，
    // 整個遞迴錯開一格。症狀非常陰險：bm / pm / survivor / best 全部完全正確
    // （C2 對它們零 mismatch），只有解碼位元在 **frame 的頭尾**錯掉——
    // 因為高 SNR 下存活路徑很快就收斂，中間的位元「剛好」還是對的。
    // 全零向量完全測不出來；是全一向量在 256 個位元裡露出 3 個（位置 0, 254, 255）。
    //
    // 這正是「解碼位元必須納入 C2 比對集」的理由：只比 bm/pm/survivor 的話，
    // 這個 bug 會完整地通過 C2，然後在 BER 上表現為「差一點點」而永遠找不到。

endmodule
