// viterbi_defs.svh —— trellis 的常數與推導函式。
//
// 用 `include 而不是 package：Yosys 0.64 的 package 支援不完整，而且會失敗得很晚很難看。
// .svh 在 Verilator、Icarus、Yosys 三邊的行為完全一致。
//
// **這裡的 trellis 表必須從八進位多項式自己推導，不得從 L2 匯入。**
// 理由（docs/trellis_convention.md §8）：兩邊若共用同一份表，表本身若有 bug 就變成
// common-mode 錯誤，C2 對它完全盲目——兩邊會「錯同一個錯」。這正是規格書 §2.1
// 說的最重要的反模式。RTL 端另有 KAT 把 elaborate 出來的表 dump 出來與凍結文件比對。

`ifndef VITERBI_DEFS_SVH
`define VITERBI_DEFS_SVH

// ---- 定案的碼參數（規格書 §3）----
localparam int VK       = 7;              // 約束長度
localparam int VM       = VK - 1;         // 記憶元 = 6
localparam int NSTATES  = 1 << VM;        // 64
localparam int NBFLY    = NSTATES / 2;    // 32 個 radix-2 butterfly
localparam int NOUT     = 2;              // rate 1/2

// 生成多項式 (133, 171)₈。最高位對應**當前輸入** u_t，最低位對應最舊的 u_{t-6}。
localparam logic [VM:0] VG0 = 7'o133;     // 0b1011011
localparam logic [VM:0] VG1 = 7'o171;     // 0b1111001

// 由生成多項式推導碼字：給定輸入 u 與狀態 s，回傳 2-bit 的 {c0, c1}。
//
// 狀態慣例（docs/trellis_convention.md §2）：s' = ((s << 1) | u) & 63，
// 也就是 s 的 bit k = u_{t-1-k}（bit 0 = 最近一次輸入）。
// 於是移位暫存器的內容 reg_bits[i] = u_{t-i}：
//     reg_bits[0] = u_t          （當前輸入）
//     reg_bits[i] = s[i-1]       （i >= 1）
// 而生成多項式 g 的 bit (VM - i) 對應 u_{t-i}。
function automatic logic [NOUT-1:0] venc(input logic u, input logic [VM-1:0] s);
    logic [VM:0] reg_bits;
    logic c0, c1;
    begin
        reg_bits[0] = u;
        for (int i = 1; i <= VM; i++) reg_bits[i] = s[i-1];

        c0 = 1'b0;
        c1 = 1'b0;
        for (int i = 0; i <= VM; i++) begin
            if (VG0[VM-i]) c0 = c0 ^ reg_bits[i];
            if (VG1[VM-i]) c1 = c1 ^ reg_bits[i];
        end
        venc = {c0, c1};
    end
endfunction

`endif
