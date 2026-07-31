r"""test_ppa_parsers.py — `ppa/` 底下那些對外部工具輸出做 regex 的解析器的回歸測試。

## 為什麼這是全專案最需要測試的一塊

`ppa/` 有一千多行是**對 Yosys / OpenSTA / iverilog 的輸出做正規表達式比對**，
而且它們一條測試都沒有。這一層的失效模式與別處不同：

    解析錯了不會拋例外，也不會有錯誤訊息 —— 它會**安靜地產生一個看起來很正常的數字**。

這正是整個專案在防的那種東西，卻剛好發生在防線本身上。這些解析器自己的 docstring
就記了五個**已經出貨過**的 bug，每一個都曾經產生過「看起來像數字的錯數字」：

1. `vcd2saif`：`$timescale` 跨行寫（iverilog 的寫法），單行 regex 比對失敗後
   **靜默退回預設 "1 ns"**，而實際是 ps ⇒ SAIF 的 DURATION 差 1000 倍
   ⇒ 翻轉密度小 1000 倍 ⇒ 組合邏輯的 switching power 直接崩掉。
2. `synth.parse_stat`：段落標題用 `(\S+)` 比對，而最後一段是
   `=== design hierarchy ===`（含空白）⇒ 永遠比不到 ⇒ **總面積一直是 0**。
3. `synth.parse_stat`：模組名裡有單引號（`$paramod\minpm\W=s32'0000...`），
   `'[^']+'` 會在 `s32'` 那裡就停住。
4. `synth.parse_stat`：Yosys 的 stat 每行是「數量 面積 cell 名」，數量在**前**；
   第一版寫成「cell 名後面接數字」⇒ **DFF 數全是 0**。
5. `power.parse_power`：`report_power` 與 `report_power -instances` 的格式不同 ——
   前者最後一列有 `Total` 標籤，後者數字在前、實例名在後。

每一條都寫成回歸案例。fixture 是真實工具輸出的最小片段，不是憑空捏的格式。
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ppa.check_annotation as CA  # noqa: E402
import ppa.power as P  # noqa: E402
import ppa.synth as S  # noqa: E402
import ppa.vcd2saif as V  # noqa: E402


# --------------------------------------------------------------- vcd2saif
# iverilog 實際寫出來的樣子：$timescale 的值在**下一行**。
VCD_HEADER_MULTILINE = """$date
  Sat Jul 31 10:00:00 2026
$end
$version
  Icarus Verilog
$end
$timescale
  1ps
$end
$scope module tb_viterbi_file $end
$var wire 1 ! clk $end
$upscope $end
$enddefinitions $end
"""

VCD_HEADER_INLINE = """$timescale 1ns $end
$scope module tb_viterbi_file $end
$var wire 1 ! clk $end
$upscope $end
$enddefinitions $end
"""


def test_timescale_parsed_when_declaration_spans_lines():
    """**回歸 #1**：跨行的 `$timescale` 必須被讀到 1ps。

    這是那個 1000 倍 bug 的根。它不會報錯——只會讓 DURATION 大 1000 倍，
    而功耗數字看起來仍然像個數字。
    """
    ts = V._parse_header(VCD_HEADER_MULTILINE, {}, {})
    assert ts.replace(" ", "") == "1ps", f"跨行 timescale 解析成 {ts!r}"


def test_timescale_parsed_when_inline():
    """同一行寫法也要能讀（不同模擬器寫法不同）。"""
    ts = V._parse_header(VCD_HEADER_INLINE, {}, {})
    assert ts.replace(" ", "") == "1ns"


def test_timescale_never_silently_defaults_to_wrong_unit():
    """單位一定要來自檔案，不能是「比對失敗就用預設值」。

    兩份 header 的 timescale 不同；若解析器退回預設值，兩者會相同 ——
    那正是 bug #1 的症狀。
    """
    assert V._parse_header(VCD_HEADER_MULTILINE, {}, {}) \
        != V._parse_header(VCD_HEADER_INLINE, {}, {})


# --------------------------------------------------------------- synth.parse_stat
# Yosys 階層式 stat 的最小片段。刻意保留三個坑：
#   * 最後一段標題含空白（design hierarchy）
#   * 模組名含單引號（s32'000...）
#   * 每行是「數量 面積 cell 名」，數量在前
YOSYS_STAT = r"""
15. Printing statistics.

=== viterbi_top ===

        +----------Local Count, excluding submodules.
        |        +-Local Area, excluding submodules.
        |        |
       17        - wires
        5        - submodules
        1        -   $paramod\minpm\W=s32'00000000000000000000000000001000

   Chip area for module '\viterbi_top': 1234.5

=== $paramod\minpm\W=s32'00000000000000000000000000001000 ===

     3683 2.52E+04 cells
       50  400.400   sky130_fd_sc_hd__dfxtp_1
      150 1.07E+03   sky130_fd_sc_hd__nand2_1

   Chip area for module '$paramod\minpm\W=s32'00000000000000000000000000001000': 25200.0

=== design hierarchy ===

        +----------Count including submodules.
        |        +-Area including submodules.
        |        |
    14536 1.64E+05 viterbi_top
     3683 2.52E+04 $paramod\minpm\W=s32'00000000000000000000000000001000

    14536 1.64E+05 cells
       59 1.18E+03   sky130_fd_sc_hd__dfxtp_1
     2370 7.12E+04   sky130_fd_sc_hd__edfxtp_1
      772 6.76E+03   sky130_fd_sc_hd__xor2_1

   Chip area for top module '\viterbi_top': 163888.432000
     of which used for sequential elements: 72349.388800 (44.15%)
"""


@pytest.fixture
def stat(tmp_path):
    p = tmp_path / "stat.txt"
    p.write_text(YOSYS_STAT, encoding="utf-8")
    return S.parse_stat(str(p), "Q3_W8_D32", 3, 8, 32)


def test_total_area_comes_from_top_module_line(stat):
    """**回歸 #2**：總面積必須取自 `design hierarchy` 那一段的 top module 行。

    段落標題含空白，用 `(\\S+)` 比對會永遠比不到 —— 症狀是總面積一直是 0，
    而 0 不會讓任何流程失敗，只會讓面積與 d\\* 全錯。
    """
    assert stat["total_area_um2"] == pytest.approx(163888.432)


def test_total_area_is_not_the_per_module_area(stat):
    """top module 自己的 cell 面積（1234.5）不是總面積。

    `Chip area for module X` **不含**子模組；拿它當總數會少算一個數量級。
    """
    assert stat["total_area_um2"] != pytest.approx(1234.5)


def test_module_name_with_single_quote_is_parsed(stat):
    """**回歸 #3**：模組名裡有 `s32'` 這種單引號，不能讓 regex 提早收尾。

    minpm 的面積必須被認出來（25200），而不是被截成別的東西或漏掉。
    """
    names = list(stat["modules"]) + list(stat["blocks"])
    assert any("minpm" in str(n) for n in names), \
        f"minpm 這一段沒被解析出來：{names}"


def test_cell_and_dff_counts_use_count_first_ordering(stat):
    """**回歸 #4**：Yosys 每行是「數量 面積 cell 名」，數量在前。

    寫成「cell 名後面接數字」的話 DFF 數會全是 0 —— 而 DFF 數是
    「clock gating 省下的是回授 mux」那個結論的依據。
    """
    assert stat["total_cells"] == 14536, f"cell 數：{stat['total_cells']}"
    # DFF 數要把 dfxtp（59）與 edfxtp（2370）都算進去 —— 有 enable 的 FF 也是 FF，
    # 而「clock gating 把有 enable 的 FF 換成無 enable 的 FF + ICG」正是靠這兩類的
    # 消長看出來的。只認 dfxtp 會漏掉 2370 個。
    assert stat["total_dff"] == 2429, f"DFF 數：{stat['total_dff']}"


# --------------------------------------------------------------- power.parse_power
STA_TOTAL = """
=== ANNOTATION ===
saif          117
unannotated     3
=== POWER TOTAL ===
Group                  Internal  Switching   Leakage      Total
---------------------------------------------------------------
Sequential            1.00e-02   2.00e-03  1.00e-08   1.20e-02
Combinational         5.00e-03   1.00e-03  2.00e-08   6.00e-03
---------------------------------------------------------------
Total                 1.50e-02   3.00e-03  3.00e-08   1.80e-02
"""

STA_INSTANCES = """
=== POWER u_tb ===
 2.548474e-02 3.988741e-03 6.129220e-08 2.947354e-02 u_tb
=== POWER u_acs ===
 9.000000e-03 2.000000e-03 1.000000e-08 1.100000e-02 u_acs
"""


def test_annotation_percentage_uses_pin_counts():
    """annotation 覆蓋率 = 1 − unannotated/全部，單位是 pin。"""
    r = P.parse_power(STA_TOTAL)
    assert r["annot_pct"] == pytest.approx(100.0 * 117 / 120)


def test_report_power_total_format():
    """**回歸 #5a**：全設計格式的最後一列有 `Total` 標籤。"""
    r = P.parse_power(STA_TOTAL)
    assert r["total"]["total"] == pytest.approx(1.80e-02)
    assert r["total"]["internal"] == pytest.approx(1.50e-02)
    assert r["total"]["switching"] == pytest.approx(3.00e-03)


def test_report_power_instances_format():
    """**回歸 #5b**：`-instances` 格式沒有 `Total` 標籤，實例名在數字**後面**。

    兩種格式共用一支解析器，用同一條 regex 吃兩種排版正是它出過錯的地方。
    """
    r = P.parse_power(STA_INSTANCES)
    assert r["u_tb"] is not None, \
        f"u_tb 沒被解析出來（區塊全是 None 就是格式沒吃到）：{r}"
    assert r["u_tb"]["total"] == pytest.approx(2.947354e-02)
    assert r["u_tb"]["internal"] == pytest.approx(2.548474e-02)
    assert r["u_acs"]["total"] == pytest.approx(1.100000e-02)


# --------------------------------------------------------------- check_annotation
ANNOT_OK = """=== ACTIVITY ANNOTATION ===
saif          117
unannotated     0
Unannotated pins:
"""

ANNOT_PARTIAL = """=== ACTIVITY ANNOTATION ===
saif           90
propagated     10
unannotated    20
"""


def test_annotation_full_coverage():
    ann, tot = CA.parse(ANNOT_OK)
    assert (ann, tot) == (117, 117)


def test_annotation_partial_coverage_sums_all_sources():
    """annotated 是**所有非 unannotated 來源**的總和，不是只算 saif。"""
    ann, tot = CA.parse(ANNOT_PARTIAL)
    assert (ann, tot) == (100, 120)


@pytest.mark.parametrize("txt", [
    "",
    "OpenSTA 3.1.0\nnothing here\n",
    "=== ACTIVITY ANNOTATION ===\nsaif  117\n",       # 沒有 unannotated 那一行
])
def test_annotation_parse_failure_is_explicit_not_a_silent_pass(txt):
    """**解析不到時必須回 (None, None)，不能給一個看起來合理的數字。**

    覆蓋率沒被確認過的功耗數字不可採信。這一條擋的是「工具改版導致格式變了，
    而檢查器把它讀成 100% 通過」——那會讓一道硬性 gate 靜靜失效。
    """
    assert CA.parse(txt) == (None, None)
