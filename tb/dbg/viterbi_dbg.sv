// viterbi_dbg.sv —— 驗證用的 wrapper。**永遠不會進合成的 filelist。**
//
// 它用 XMR（cross-module reference）從 viterbi_top 內部把架構狀態拉出來給 cocotb 比對。
//
// 為什麼不直接在 viterbi_top 上開 debug port：SystemVerilog 沒辦法「有條件地移除」port，
// 只能停止驅動。64 個 PM × W 位元 = 640 支腳，加上 survivor(64) 與 bm 超過 700 支——
// 那些腳在 ORFS 會變成真實 IO pad，一個 40 kGE 的核心配 700+ 支腳會 pad-ring limited，
// 量到的面積是垃圾。
//
// XMR 的好處：
//   - viterbi_top 完全乾淨，合成看到的就是要出貨的東西
//   - 模擬器會自動把 XMR 的目標標成 public，不需要 pragma，也不需要 --public-flat-rw
//     （後者會全域關掉最佳化，重創模擬速度）
//   - cocotb 每個 stage 只讀 **4 個寬 handle**，不是 64+ 個，VPI 呼叫數少一個數量級
//
// 限制：XMR 只能打進**非 generate scope**。下面拉的四個訊號都是 viterbi_top 裡的
// 平坦 wire，符合這個限制。

`include "viterbi_defs.svh"

module viterbi_dbg #(
    parameter int Q     = 4,
    parameter int W     = 10,
    parameter int D     = 32,
    parameter int NINFO = 256
) (
    input  logic                clk,
    input  logic                rst,
    input  logic                in_valid,
    input  logic [Q-1:0]        r0,
    input  logic [Q-1:0]        r1,

    output logic                out_valid,
    output logic                dec_bit,
    output logic                frame_done,

    // ---- C2 的比對面（架構狀態）----
    output logic                dbg_stage_done,   // 比對點：不是靠數 cycle
    output logic [4*(Q+1)-1:0]  dbg_bm,           // bm[4]
    output logic [NSTATES*W-1:0] dbg_pm,          // pm[64]（已 mod 2^W）
    output logic [NSTATES-1:0]  dbg_surv,         // survivor[64]
    output logic [VM-1:0]       dbg_best
);

    viterbi_top #(.Q(Q), .W(W), .D(D), .NINFO(NINFO)) u_dut (
        .clk (clk), .rst (rst), .in_valid (in_valid), .r0 (r0), .r1 (r1),
        .out_valid (out_valid), .dec_bit (dec_bit), .frame_done (frame_done)
    );

    assign dbg_stage_done = u_dut.stage_done;
    assign dbg_bm         = u_dut.bm_r;
    assign dbg_pm         = u_dut.pm_pk;
    assign dbg_surv       = u_dut.surv_pk;
    assign dbg_best       = u_dut.best;

endmodule
