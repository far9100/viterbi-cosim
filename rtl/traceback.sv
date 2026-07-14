// traceback.sv —— register exchange，固定回溯深度 D。
//
// ---- 為什麼是 register exchange，不是 memory traceback ----
//
// docs/traceback_convention.md 凍結的語意是 **uniform depth D**：每個 stage 從 PM 最小的
// 狀態往回追**固定 D 步**，輸出 1 個位元。教科書上常見的「one-pointer 批次 memory
// traceback」（每 D 個 stage 從 argmin 起回走 2D 步、丟掉最新的 D 個、輸出最舊的 D 個）
// 的有效深度落在 **[D, 2D]** 而不是固定 D —— 解碼位元會與凍結文件不同，C2 直接噴 mismatch。
//
// register exchange 天生就是固定深度 D、1 bit/cycle：
//
//     RE[s'] <= (RE[pred(s')] << 1) | (s' & 1)
//     dec     = RE[best] 的最高位
//
// 每個 RE[s] 存的是「進入狀態 s 的存活路徑上，最近 D 個輸入位元」，最舊的在最高位。
// 所以在 stage t 之後，RE[best] 的最高位就是 u_{t-D+1} —— 正是凍結文件要求的輸出。
//
// 代價：面積 64 × D 個 flop，而且**每個 stage 全部 64 個暫存器都要改寫**（翻轉率高、
// 功耗高）。這正是 M5 要量的東西。
//
// ---- 兩個會讓面積爆掉的陷阱 ----
//
// 1. `re[pred]` 用**變數索引**會合成出「每個狀態一個 64:1 的 D-bit mux」——64 個 64:1 mux。
//    但 pred(s) 只可能是 (s>>1) 或 (s>>1)+32 這**兩個編譯期常數**之一。
//    所以要直接在兩個常數索引的暫存器之間做 2:1 選擇。
// 2. `re[best][D-1]` 的 best 是動態的，那個 64:1 mux 躲不掉——但先把 64 個最高位收成
//    一個向量，就只剩「64:1 選 1 個 bit」，而不是「64:1 選 D 個 bit」。
//
// ---- 尾端沖出 ----
//
// frame 是 terminated 的，所以時間 T 的狀態必為 0。RE[0] 這時存的就是 u_{T-D} … u_{T-1}
// （最高位到最低位）。主迴圈在 stage T-1 已經輸出了最高位 u_{T-D}，
// 所以尾端只要把 RE[0] 左移一位，再逐 cycle 吐最高位，共 D-1 個位元。
// 這與凍結文件「從已知終止狀態 0 出發精確回溯」的定義完全相同。

`include "viterbi_defs.svh"

module traceback #(
    parameter int D = 32
) (
    input  logic                clk,
    input  logic                rst,        // 同步 active-high
    input  logic                stage_en,   // 推進一個 trellis stage
    input  logic                flush_load, // 載入 RE[0]，準備沖出
    input  logic                flush_en,   // 沖出中（每 cycle 吐 1 bit）
    input  logic [NSTATES-1:0]  surv_pk,    // 這個 stage 的 survivor bits
    input  logic [VM-1:0]       best,       // PM 最小的狀態
    output logic                dec_bit
);

    logic [D-1:0]       re      [NSTATES];
    logic [D-1:0]       re_next [NSTATES];
    logic [D-1:0]       flush_sr;
    logic [NSTATES-1:0] re_msb;

    genvar s;
    generate
        for (s = 0; s < NSTATES; s++) begin : g_re
            // pred(s) 只有兩個可能，而且都是編譯期常數：
            localparam int PRED0 = s >> 1;              // survivor bit = 0
            localparam int PRED1 = (s >> 1) + NBFLY;    // survivor bit = 1
            localparam logic IN_BIT = ((s % 2) != 0);          // 進入狀態 s 的輸入位元 = s & 1

            // 2:1 選擇，不是 64:1
            assign re_next[s] = surv_pk[s] ? {re[PRED1][D-2:0], IN_BIT}
                                           : {re[PRED0][D-2:0], IN_BIT};
            assign re_msb[s] = re[s][D-1];
        end
    endgenerate

    always_ff @(posedge clk) begin
        if (rst) begin
            for (int i = 0; i < NSTATES; i++) re[i] <= '0;
        end else if (stage_en) begin
            for (int i = 0; i < NSTATES; i++) re[i] <= re_next[i];
        end
    end

    always_ff @(posedge clk) begin
        if (rst)              flush_sr <= '0;
        else if (flush_load)  flush_sr <= {re[0][D-2:0], 1'b0};   // 最高位已由主迴圈輸出
        else if (flush_en)    flush_sr <= {flush_sr[D-2:0], 1'b0};
    end

    assign dec_bit = flush_en ? flush_sr[D-1] : re_msb[best];

endmodule
