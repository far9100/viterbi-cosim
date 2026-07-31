// ctrl.sv —— frame 的控制 FSM。
//
// 一個 frame 有 T = NINFO + 6 個 trellis stage（6 個 tail bits 把編碼器逼回狀態 0）。
//
// ---- 時序（決定 C2 怎麼對齊，很重要）----
//
//   cycle C   : in_valid 帶著 stage t 的 (r0, r1)。組合邏輯算 bm / pm_next / surv。
//               時脈邊緣：pm、surv_r、re 全部更新成「stage t 之後」的值。
//   cycle C+1 : stage_done 拉高。此時 pm_pk / surv_pk / re 都是「stage t 之後」的值，
//               best = argmin(pm)，dec_bit = RE[best] 的最高位 = u_{t-D+1}。
//
//               -> **C2 就在 stage_done 這個脈衝上比對，不是靠數 cycle。**
//                  這也是為什麼折疊架構（PAR<32）將來可以完全沿用同一套 testbench。
//
// 主迴圈從 t = D-1 起輸出（在那之前 RE 還沒填滿 D 個位元）。
// 最後一個 stage（t = T-1）之後進入 FLUSH，再吐 D-1 個位元。
// 總輸出 = (T − D + 1) + (D − 1) = T 個位元，正好是 dec[0 … T-1]。
//
// ---- 為什麼需要 S_LAST ----
//
// 第一版少了它，結果 flush_en 會在「主迴圈還欠最後一個位元」的那個 cycle 就拉高，
// 把 dec_bit 切到還沒載入的 flush_sr 上。S_LAST 就是那一個 cycle：
// stage_done 仍為高（主迴圈輸出 u_{T-D}），同時 flush_load 拉高，
// 讓 flush_sr 在這個 cycle 的邊緣載入 RE[0]。下一個 cycle 才進 S_FLUSH。

`include "viterbi_defs.svh"

module ctrl #(
    parameter int D     = 32,
    parameter int NINFO = 1024
) (
    input  logic clk,
    input  logic rst,              // 同步 active-high
    input  logic in_valid,
    output logic stage_en,
    output logic stage_done,       // C2 的比對點
    output logic flush_load,
    output logic flush_en,
    output logic out_valid,
    output logic frame_done
);

    localparam int T     = NINFO + VM;
    localparam int CNT_W = $clog2(T + 1);
    localparam int FCW   = $clog2(D + 1);

    localparam logic [1:0] S_RUN   = 2'd0;
    localparam logic [1:0] S_LAST  = 2'd1;
    localparam logic [1:0] S_FLUSH = 2'd2;
    localparam logic [1:0] S_DONE  = 2'd3;

    logic [1:0]       st;
    logic [CNT_W-1:0] t;           // 下一個要推進的 stage 編號
    logic [CNT_W-1:0] t_done;      // 剛完成的 stage 編號
    logic [FCW-1:0]   fcnt;

    assign stage_en = (st == S_RUN) && in_valid;
    assign flush_en = (st == S_FLUSH);
    assign out_valid = (stage_done && (t_done >= CNT_W'(D - 1))) || flush_en;

    always_ff @(posedge clk) begin
        if (rst) begin
            st         <= S_RUN;
            t          <= '0;
            t_done     <= '0;
            fcnt       <= '0;
            stage_done <= 1'b0;
            flush_load <= 1'b0;
            frame_done <= 1'b0;
        end else begin
            stage_done <= 1'b0;
            flush_load <= 1'b0;
            frame_done <= 1'b0;

            case (st)
                S_RUN: begin
                    if (in_valid) begin
                        stage_done <= 1'b1;
                        t_done     <= t;
                        if (t == CNT_W'(T - 1)) begin
                            st         <= S_LAST;
                            flush_load <= 1'b1;   // 在 S_LAST 那個 cycle 為高
                        end else begin
                            t <= t + CNT_W'(1);
                        end
                    end
                end

                // 這個 cycle：stage_done 仍為高（主迴圈輸出最後一個位元 u_{T-D}），
                // flush_load 為高（flush_sr 在本 cycle 的邊緣載入 RE[0]），flush_en 為低。
                S_LAST: begin
                    st   <= S_FLUSH;
                    fcnt <= '0;
                end

                S_FLUSH: begin
                    if (fcnt == FCW'(D - 2)) begin
                        st         <= S_DONE;
                        frame_done <= 1'b1;
                    end
                    fcnt <= fcnt + FCW'(1);
                end

                default: begin   // S_DONE：停住，等 reset 開下一個 frame
                    st <= S_DONE;
                end
            endcase
        end
    end

endmodule
