// counter.sv —— PPA 流程的煙霧測試 DUT。
//
// 這個 8-bit counter 存在的唯一目的，是在寫任何 Viterbi RTL 之前，先把整條
// 「Yosys 合成 -> gate-level 模擬 -> VCD -> SAIF -> OpenSTA 功耗標註」的路打通。
//
// 為什麼要先做這件事（計畫的 R2 風險）：這條流程是全專案唯一零複用的部分——
// RISC-V 專案的功耗是 vectorless 的（假設 activity=0.2），從未做過真實 activity 標註。
// 而它最典型的死法是「OpenSTA 的 annotation coverage 掉到 0%」，起因是
// Yosys 的 net 命名、Icarus 的 VCD 命名、OpenSTA 的 parser 三者對不上。
// 這種 bug 的症狀會偽裝成「功耗竟然不隨輸入改變」，在第 5 週遇到它就沒救了。
//
// 這個 DUT 刻意同時具備：
//   - 序向邏輯（8 個 DFF）        -> 測 dfflibmap 出來的 flop 能不能被標註
//   - 組合邏輯（遞增器的進位鏈）  -> 測 ABC 映射出來的內部 net 能不能被標註
// 後者才是關鍵：Viterbi 的 SNR 依賴性完全住在 ACS 的組合路徑上，
// 若組合 net 標註不到，功耗-SNR 曲線就會依構造變平，頭條結果直接報銷。
//
// 遵守給 Yosys 0.64 的 SV 限制（見 docs/ 的 M3 說明）：
//   - 不用 package / import，port 只用 packed vector 與純量
//   - 不在宣告時給初值，一律同步 active-high reset

module counter #(
    parameter int WIDTH = 8
) (
    input  logic             clk,
    input  logic             rst,   // 同步、active-high
    input  logic             en,
    output logic [WIDTH-1:0] cnt
);

    always_ff @(posedge clk) begin
        if (rst) begin
            cnt <= '0;
        end else if (en) begin
            cnt <= cnt + 1'b1;
        end
    end

endmodule
