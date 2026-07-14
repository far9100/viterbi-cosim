// tb_viterbi_file.sv —— 檔案驅動的 testbench（不經過 Python / VPI）。
//
// 服務兩件事：
//
//   G7（4-state 交叉檢查）
//       Verilator 是 2-state 的：未初始化的暫存器讀出來是 0 而不是 X。
//       一個 reset 不完整的 bug（某個暫存器忘了 reset）在 Verilator 上會「剛好」
//       是 0 而通過，在真實硬體與 Icarus 上卻是 X。只有 4-state 的模擬器叫得出來。
//
//       但 cocotb + Icarus 在這台機器上走不通：oss-cad-suite 的 vvp 自帶一整套 glibc
//       （RPATH 指向自己的 lib），而 cocotb 的 VPI 要 dlopen 系統的 libpython3.12，
//       後者需要 GLIBC_2.38——oss-cad-suite 的 libm 太舊。裝系統版 iverilog 需要 root。
//       繞法：**Icarus 這一側完全不要 Python**，用 $readmemh 讀檔案驅動。
//
//   M5 的 gate-level 模擬
//       合成後的 netlist 只能用 Icarus 跑（sky130 的 cell model 建在 UDP / specify 之上，
//       Verilator 不支援），而 cocotb 也接不上 gate-level netlist。
//       所以無論如何都需要一支檔案驅動的 TB。同一支檔案兩用。
//
// 用法（plusargs）：
//   +stim=<檔>   每行 "<r0> <r1>"（十六進位）
//   +dec=<檔>    每行一個期望的解碼位元
//   +frames=<n>  frame 數
//   +vcd=<檔>    （選用）dump 波形，M5 的功耗流程要用

`timescale 1ns / 1ps

module tb_viterbi_file;

    // 這些必須與被測的向量一致；由 -P 或 -G 在編譯時覆寫
    parameter int Q     = 4;
    parameter int W     = 10;
    parameter int D     = 32;
    parameter int NINFO = 256;

    localparam int T    = NINFO + 6;
    localparam int MAXS = 64 * 1024;    // 激勵的最大 stage 數
    localparam int MAXB = 64 * 1024;    // 期望位元的最大數量

    logic         clk = 1'b0;
    logic         rst;
    logic         in_valid;
    logic [Q-1:0] r0, r1;
    logic         out_valid, dec_bit, frame_done;

    // 實例名固定叫 dut：M5 的 SAIF scope 是 tb_viterbi_file/dut，兩邊要對得上
    viterbi_top #(.Q(Q), .W(W), .D(D), .NINFO(NINFO)) dut (
        .clk (clk), .rst (rst), .in_valid (in_valid), .r0 (r0), .r1 (r1),
        .out_valid (out_valid), .dec_bit (dec_bit), .frame_done (frame_done)
    );

    always #5 clk = ~clk;

    // 激勵與期望值
    integer stim_r0 [0:MAXS-1];
    integer stim_r1 [0:MAXS-1];
    integer exp_dec [0:MAXB-1];

    integer n_frames;
    integer errors;
    integer x_errors;
    integer n_checked;

    string  stim_file, dec_file, vcd_file;
    integer fd, code, i, f, t_i, cyc, got, dec_idx, out_cnt;

    initial begin
        errors    = 0;
        x_errors  = 0;
        n_checked = 0;

        if (!$value$plusargs("stim=%s", stim_file)) begin
            $display("ERROR: 缺少 +stim=<檔>"); $finish;
        end
        if (!$value$plusargs("dec=%s", dec_file)) begin
            $display("ERROR: 缺少 +dec=<檔>"); $finish;
        end
        if (!$value$plusargs("frames=%d", n_frames)) n_frames = 1;

        if ($value$plusargs("vcd=%s", vcd_file)) begin
            $dumpfile(vcd_file);
            $dumpvars(0, tb_viterbi_file.dut);
        end

        // 讀激勵（每行 "<r0> <r1>"）
        fd = $fopen(stim_file, "r");
        if (fd == 0) begin $display("ERROR: 開不了 %s", stim_file); $finish; end
        i = 0;
        while (!$feof(fd) && i < MAXS) begin
            code = $fscanf(fd, "%h %h\n", stim_r0[i], stim_r1[i]);
            if (code == 2) i = i + 1;
        end
        $fclose(fd);

        // 讀期望的解碼位元
        fd = $fopen(dec_file, "r");
        if (fd == 0) begin $display("ERROR: 開不了 %s", dec_file); $finish; end
        i = 0;
        while (!$feof(fd) && i < MAXB) begin
            code = $fscanf(fd, "%d\n", exp_dec[i]);
            if (code == 1) i = i + 1;
        end
        $fclose(fd);

        dec_idx = 0;

        for (f = 0; f < n_frames; f = f + 1) begin
            // ---- reset ----
            rst      = 1'b1;
            in_valid = 1'b0;
            r0       = '0;
            r1       = '0;
            repeat (3) @(posedge clk);
            rst = 1'b0;
            @(posedge clk);

            out_cnt = 0;

            // ---- 餵 T 個 stage，再等尾端沖出 ----
            for (cyc = 0; cyc < T + D + 4; cyc = cyc + 1) begin
                if (cyc < T) begin
                    t_i      = f * T + cyc;
                    in_valid = 1'b1;
                    r0       = Q'(stim_r0[t_i]);
                    r1       = Q'(stim_r1[t_i]);
                end else begin
                    in_valid = 1'b0;
                end

                @(posedge clk);
                #1;   // 讓輸出穩定下來再看

                if (out_valid === 1'b1) begin
                    // ---- G7 的核心：4-state 檢查 ----
                    // reset 不完整的話，未初始化的暫存器會是 X，而 X 會傳到 dec_bit。
                    // Verilator（2-state）看到的是 0，永遠抓不到；Icarus 看得到。
                    if (dec_bit === 1'bx || dec_bit === 1'bz) begin
                        x_errors = x_errors + 1;
                        if (x_errors <= 5)
                            $display("G7 FAIL: frame %0d 的第 %0d 個輸出是 X/Z —— reset 不完整",
                                     f, out_cnt);
                    end else if (out_cnt < NINFO) begin
                        got = dec_bit;
                        if (got !== exp_dec[dec_idx]) begin
                            errors = errors + 1;
                            if (errors <= 5)
                                $display("C2 FAIL: frame %0d bit %0d: RTL=%0d golden=%0d",
                                         f, out_cnt, got, exp_dec[dec_idx]);
                        end
                        n_checked = n_checked + 1;
                        dec_idx   = dec_idx + 1;
                    end
                    out_cnt = out_cnt + 1;
                end
            end

            if (out_cnt != T)
                $display("WARN: frame %0d 收到 %0d 個輸出，預期 %0d", f, out_cnt, T);
        end

        $display("");
        $display("=== 檔案驅動 TB（Q=%0d W=%0d D=%0d）", Q, W, D);
        $display("    frames      %0d", n_frames);
        $display("    比對的位元  %0d", n_checked);
        $display("    C2 錯誤     %0d", errors);
        $display("    X/Z 錯誤    %0d   <- G7：4-state 才看得到的東西", x_errors);
        if (errors == 0 && x_errors == 0 && n_checked > 0)
            $display("TB_RESULT PASS %0d %0d", n_frames, n_checked);
        else
            $display("TB_RESULT FAIL %0d %0d", errors, x_errors);
        $finish;
    end

endmodule
