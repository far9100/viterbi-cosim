// minpm.sv —— 在 modulo 算術下找 PM 最小的狀態。
//
// **不能直接對 wrapped 的 pm[] 取最小值。** 它們會 wrap，直接比大小會挑到錯的狀態。
//
// 正確做法（docs/wordlength_bound.md §6，L2 / GPU / RTL 三方相同）：
// 以狀態 0 為參考點相減，把差值解讀為 W-bit **有號數**，再取最小：
//
//     d_s  = signed_W( pm[s] − pm[0] )      // 由 G6 保證 |spread| < 2^(W−1)，故合法
//     best = argmin_s d_s                    // 平手取**最低索引**
//
// 平手規則靠 tournament tree 的結構天然滿足：每一層都把 (2k, 2k+1) 配對，
// 左邊的索引一定較小，而 `<=` 讓平手時選左邊。

`include "viterbi_defs.svh"

module minpm #(
    parameter int W = 10
) (
    input  logic [NSTATES*W-1:0] pm_pk,
    output logic [VM-1:0]        best
);

    // 以狀態 0 為參考點的有號差
    logic signed [W-1:0] d [NSTATES];
    logic [W-1:0] pm0;
    assign pm0 = pm_pk[0 +: W];

    genvar s;
    generate
        for (s = 0; s < NSTATES; s++) begin : g_diff
            // W 位元的減法自然 wrap，再以 signed 解讀 —— 這就是 signed_W(pm[s] − pm[0])
            assign d[s] = $signed(pm_pk[s*W +: W] - pm0);
        end
    endgenerate

    // 6 層的 tournament tree。tv 存值、ti 存索引。
    // 用 <= 讓平手時選左邊（索引較小的那個）。
    logic signed [W-1:0] tv [VM+1][NSTATES];
    logic [VM-1:0]       ti [VM+1][NSTATES];

    integer i, l, k;
    always_comb begin
        for (i = 0; i < NSTATES; i++) begin
            tv[0][i] = d[i];
            ti[0][i] = VM'(i);
        end
        for (l = 1; l <= VM; l++) begin
            for (k = 0; k < (NSTATES >> l); k++) begin
                if (tv[l-1][2*k] <= tv[l-1][2*k+1]) begin
                    tv[l][k] = tv[l-1][2*k];
                    ti[l][k] = ti[l-1][2*k];
                end else begin
                    tv[l][k] = tv[l-1][2*k+1];
                    ti[l][k] = ti[l-1][2*k+1];
                end
            end
        end
        best = ti[VM][0];
    end

endmodule
