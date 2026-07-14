// bmu.sv —— branch metric unit。
//
// 非負距離度量（docs/wordlength_bound.md §1）：以 Q-bit 無號軟值 r ∈ [0, 2^Q − 1]
//
//     bm(c=0) = r
//     bm(c=1) = (2^Q − 1) − r
//     BM(碼字 c) = bm(c0) + bm(c1)  ∈ [0, λ_max]，  λ_max = 2·(2^Q − 1)
//
// 為什麼是非負距離而不是相關度量（規格書 v1 的說法）：Hekstra modulo normalization
// 的標準證明要求 branch metric **非負且有界**。兩者只差一個每 stage 的常數
// （在 ACS 的比較中抵銷），決策與 BER 完全相同。
//
// 輸出是**長度 4** 的向量，以 2-bit 期望碼字索引：bm_pk[c] = bm(c0) + bm(c1)。
// 不是 128 個 per-edge metric —— trellis 表若有錯，會在 pm[64] 上現形，
// 所以 4 個 BM + pm[64] 就是完整而且便宜得多的比對面。

`include "viterbi_defs.svh"

module bmu #(
    parameter int Q = 4
) (
    input  logic [Q-1:0]         r0,
    input  logic [Q-1:0]         r1,
    output logic [4*(Q+1)-1:0]   bm_pk    // bm[3:0]，每個 (Q+1) bits
);

    localparam int BM_W = Q + 1;          // λ_max = 2^(Q+1) − 2，(Q+1) bits 剛好夠
    localparam logic [Q-1:0] MAXR = {Q{1'b1}};   // 2^Q − 1

    // 每個符號的度量：c=0 -> r；c=1 -> MAXR − r
    logic [Q-1:0] m0_0, m0_1, m1_0, m1_1;
    assign m0_0 = r0;
    assign m0_1 = MAXR - r0;
    assign m1_0 = r1;
    assign m1_1 = MAXR - r1;

    // 碼字 c = (c0 << 1) | c1
    assign bm_pk[0*BM_W +: BM_W] = m0_0 + m1_0;   // c = 2'b00
    assign bm_pk[1*BM_W +: BM_W] = m0_0 + m1_1;   // c = 2'b01
    assign bm_pk[2*BM_W +: BM_W] = m0_1 + m1_0;   // c = 2'b10
    assign bm_pk[3*BM_W +: BM_W] = m0_1 + m1_1;   // c = 2'b11

endmodule
