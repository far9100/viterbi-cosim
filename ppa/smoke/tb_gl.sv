// tb_gl.sv —— counter 的 gate-level testbench（Icarus）。
//
// 這支 TB 同時是「真正的 Viterbi gate-level TB」的原型，所以刻意把幾件事做對：
//
// 1. DUT 的實例名固定叫 `dut`。SAIF 的 INSTANCE 路徑會是 tb/dut/...，
//    OpenSTA 的 read_saif -scope tb/dut 必須對得上。scope 打錯的話 annotation 會是 0%，
//    而症狀會偽裝成「功耗不隨輸入改變」。
//
// 2. $dumpvars(0, tb.dut)：dump dut 底下的所有層級。
//    多 dump 是安全的（OpenSTA 會忽略 netlist 裡不存在的 net），
//    少 dump 才會致命（漏掉的 net 就是沒被標註的 net）。
//
// 3. VCD 檔名與 cycle 數由 plusargs 給，因為真正跑的時候 VCD 會導進 FIFO
//    （mkfifo /tmp/dump.vcd）讓它完全不落地——gate-level VCD 是 30-180 KB/cycle，
//    100k cycles 就是幾個 GB，× 72 個 (組態 × SNR) 點根本放不下。
//
// 4. 輸入的翻轉率必須是「真實的」。counter 這裡用 LFSR 驅動 en，
//    對應到 Viterbi 那邊就是「真實 AWGN 通道資料驅動」（規格書 §7 的硬性要求：
//    功耗不得用預設 toggle-rate 猜測）。

`timescale 1ns / 1ps

module tb;

    localparam int WIDTH = 8;

    logic             clk;
    logic             rst;
    logic             en;
    logic [WIDTH-1:0] cnt;

    // DUT 的實例名 `dut` 是與 SAIF scope 的契約，不要改。
    counter dut (
        .clk (clk),
        .rst (rst),
        .en  (en),
        .cnt (cnt)
    );

    // 100 MHz
    initial clk = 1'b0;
    always #5 clk = ~clk;

    // 用 LFSR 產生 en 的翻轉，避免 counter 每個 cycle 都遞增（那會讓低位元的
    // 翻轉率固定在 50%，是個不真實的特例）。
    logic [15:0] lfsr;

    integer      n_cycles;
    integer      i;
    reg [1023:0] vcdfile;

    initial begin
        if (!$value$plusargs("cycles=%d", n_cycles)) n_cycles = 2000;
        if (!$value$plusargs("vcdfile=%s", vcdfile)) vcdfile = "smoke.vcd";

        $dumpfile(vcdfile);
        $dumpvars(0, tb.dut);

        rst  = 1'b1;
        en   = 1'b0;
        lfsr = 16'hACE1;

        // 兩個 cycle 的 reset
        repeat (2) @(posedge clk);
        rst = 1'b0;

        for (i = 0; i < n_cycles; i = i + 1) begin
            @(posedge clk);
            // xorshift 型 LFSR：taps 16,14,13,11
            lfsr <= {lfsr[14:0],
                     lfsr[15] ^ lfsr[13] ^ lfsr[12] ^ lfsr[10]};
            en   <= lfsr[0];
        end

        @(posedge clk);
        $finish;
    end

endmodule
