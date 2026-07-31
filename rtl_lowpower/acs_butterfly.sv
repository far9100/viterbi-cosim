// acs_butterfly.sv —— radix-2 的 add-compare-select。
//
// butterfly j 吃 PM[j] 與 PM[j+32]，吐 PM[2j] 與 PM[2j+1]（docs/trellis_convention.md §2）。
//
// **只需要一個 branch metric 輸入。** 因為 (133,171) 這兩個多項式都是**奇數**
// （LSB = 1，都有最舊那個位元 u_{t-6} 的抽頭），所以 c(j+32, u) = ~c(j, u)；
// 又因為兩者的 MSB 也都是 1（都有當前輸入的抽頭），所以 c(j, 1) = ~c(j, 0)。令 X = c(j,0)：
//
//     c(j,   0) = X        c(j,   1) = ~X
//     c(j+32,0) = ~X       c(j+32,1) = X
//
// 而 bm[~X] = λ_max − bm[X]。於是：
//
//     PM[2j]   = min( PM[j] + bm[X],   PM[j+32] + (λ_max − bm[X]) )
//     PM[2j+1] = min( PM[j] + (λ_max − bm[X]), PM[j+32] + bm[X]   )
//
// （這兩條性質不是對所有卷積碼都成立，golden/trellis.py 每次建構時都當場驗證。）
//
// ---- Modulo（Hekstra）比較 ----
//
// 加法在 W 位元裡自然 wrap —— 那**就是** modulo normalization，不需要額外的正規化電路。
// 比較則要把 (sum_b − sum_a) 解讀為 W-bit **有號數**再取符號：
//
//     sel_a = ~diff[W-1]        // signed(diff) >= 0  =>  sum_a <= sum_b  =>  選 A
//
// 減法方向刻意是 b − a：平手（diff == 0）時 diff[W-1] = 0 => 選 A（survivor bit 0），
// **不需要額外的等於比較器**。這與 docs/trellis_convention.md §4 的凍結慣例一致
// （對應 np.argmin 回傳第一個最小值的語意）。Q=3 時整數平手非常常見，
// 方向選錯不會報錯，只會讓 C2 在上線後噴 mismatch。

module acs_butterfly #(
    parameter int W    = 10,
    parameter int BM_W = 5
) (
    input  logic [W-1:0]    pm_a,       // PM[j]
    input  logic [W-1:0]    pm_b,       // PM[j+32]
    input  logic [BM_W-1:0] bm_x,       // bm[X]，X = c(j, 0)
    input  logic [BM_W-1:0] lam,        // λ_max
    output logic [W-1:0]    pm_even,    // PM[2j]
    output logic [W-1:0]    pm_odd,     // PM[2j+1]
    output logic            surv_even,  // 進入 2j   的 survivor bit
    output logic            surv_odd    // 進入 2j+1 的 survivor bit
);

    logic [BM_W-1:0] bm_xc;
    assign bm_xc = lam - bm_x;          // bm[~X]

    // 明確做零延伸再相加。隱式延伸雖然結果一樣，但那正是寬度 bug 藏身的地方——
    // 讓 Verilator 的 WIDTHEXPAND 警告保持乾淨，之後真的有寬度錯誤時才看得見。
    logic [W-1:0] bm_x_e, bm_xc_e;
    assign bm_x_e  = W'(bm_x);
    assign bm_xc_e = W'(bm_xc);

    // 進入 2j（u=0）：前驅 j 的碼字是 X，前驅 j+32 的是 ~X
    logic [W-1:0] a0, b0, d0;
    assign a0 = pm_a + bm_x_e;          // 在 W 位元裡自然 wrap = modulo normalization
    assign b0 = pm_b + bm_xc_e;
    assign d0 = b0 - a0;
    assign surv_even = d0[W-1];         // 1 = 選 B（前驅 j+32）
    assign pm_even   = d0[W-1] ? b0 : a0;

    // 進入 2j+1（u=1）：前驅 j 的碼字是 ~X，前驅 j+32 的是 X
    logic [W-1:0] a1, b1, d1;
    assign a1 = pm_a + bm_xc_e;
    assign b1 = pm_b + bm_x_e;
    assign d1 = b1 - a1;
    assign surv_odd = d1[W-1];
    assign pm_odd   = d1[W-1] ? b1 : a1;

endmodule
