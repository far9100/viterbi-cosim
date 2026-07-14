"""vcd2saif.py — 把 VCD 串流轉成 SAIF（switching activity interchange format）。

## 為什麼需要這個檔

功耗必須由「真實通道資料驅動的 switching activity」算出（規格書 §7 的硬性要求），
這代表要模擬合成後的 gate-level netlist 並記錄每一條 net 的翻轉。問題在體積：

    一個 20-40 kGE 的 netlist，每個 cycle 有數千到數萬次 net 值變化，
    VCD 約 30-180 KB/cycle ⇒ 100k cycles = 3-18 GB，× 72 個 (組態 × SNR) 點 = 不可行。

SAIF 則是 O(#nets)，與跑多久無關：每條 net 只存 T0/T1/TX/TC 四個累積量，
一個點 2-10 MB，可以入庫當作功耗證據。

Icarus Verilog 只會寫 VCD、不會寫 SAIF，OpenSTA 又只吃 SAIF 或 VCD（讀 VCD 時仍要先落地）。
所以本檔以**串流**方式做轉換：從 stdin 逐行讀 VCD，常數記憶體，單次掃描，
搭配 FIFO 使用時 VCD 完全不落地：

    mkfifo /tmp/dump.vcd
    python3 ppa/vcd2saif.py --scope tb/dut --out act.saif < /tmp/dump.vcd &
    vvp gl.vvp +vcdfile=/tmp/dump.vcd

## SAIF 的四個累積量

    T0  該 net 停留在 0 的總時間
    T1  停留在 1 的總時間
    TX  停留在 X/Z 的總時間
    TC  翻轉次數（只計 0<->1；X->0 或 X->1 不算翻轉，那是初始化不是充放電）

OpenSTA 用 T1/(T0+T1+TX) 當作 duty（訊號為高的機率），TC/DURATION 當作翻轉密度。

## 命名的陷阱（這是整條功耗流程最容易死掉的地方）

Yosys 的 netlist 把多位元訊號宣告成 `wire [7:0] cnt;`，OpenSTA 讀進去會建立
`cnt[0]` … `cnt[7]` 這 8 條 net。但 VCD 把它 dump 成**一個** 8-bit 變數。
所以這裡必須把向量**展開成逐位元的 net**，名字對得上 OpenSTA 才會標註成功。
對不上的症狀是 annotation coverage 掉到 0%，而表面現象會偽裝成
「功耗竟然不隨輸入改變」——極難 debug。這就是 M0 要先用 counter 打通這條路的原因。
"""

import argparse
import re
import sys

# VCD 的值變化有三種形式：
#   純量  0!  1!  x!  z!          （值緊接著 id，中間無空白）
#   向量  b1010 !                 （b/B 前綴，二進位字串，空白，id）
#   實數  r3.14 !                 （本專案不會有，但仍需正確跳過）
_SCALAR_VALS = set("01xXzZ")

_VAR_RE = re.compile(
    r"\$var\s+\S+\s+(\d+)\s+(\S+)\s+(.+?)\s*\$end"
)


class Net:
    """一條單位元 net 的累積狀態。刻意用 __slots__：netlist 動輒數萬條 net。"""

    __slots__ = ("t0", "t1", "tx", "tc", "val", "last_t")

    def __init__(self):
        self.t0 = 0
        self.t1 = 0
        self.tx = 0
        self.tc = 0
        self.val = "x"      # 模擬開始前一律視為未知
        self.last_t = 0

    def change(self, t, new):
        """在時間 t 把值改成 new，先把 [last_t, t) 這段時間記到舊值的桶子裡。"""
        dt = t - self.last_t
        if dt:
            if self.val == "0":
                self.t0 += dt
            elif self.val == "1":
                self.t1 += dt
            else:
                self.tx += dt
        # 只有 0<->1 才算翻轉。X->0 / X->1 是初始化，沒有充放電，不該計入 TC。
        if (self.val == "0" and new == "1") or (self.val == "1" and new == "0"):
            self.tc += 1
        self.val = new
        self.last_t = t

    def flush(self, t_end):
        self.change(t_end, self.val)


def _parse_header(header, scope_nets, id_to_bits):
    """解析 VCD 的宣告區。回傳 timescale 字串。

    **不能用逐行比對**：VCD 的宣告可以跨行。iverilog 就是這樣寫 timescale 的：

        $timescale
          1ps
        $end

    第一版把 timescale 寫成單行 regex，比對失敗後**靜默退回預設值 "1 ns"**，
    但實際單位是 ps —— 於是 SAIF 的 DURATION 被當成大 1000 倍的時間，
    OpenSTA 算出的翻轉密度就小了 1000 倍，組合邏輯的 switching power 直接崩掉。
    功耗數字看起來仍然「像個數字」，不會有任何錯誤訊息。這正是煙霧測試要抓的東西。
    """
    timescale = "1ps"
    cur_scope = []

    # 以 $end 切開，保留順序（scope 的巢狀關係依賴順序）
    for chunk in header.split("$end"):
        chunk = chunk.strip()
        if not chunk or not chunk.startswith("$"):
            continue
        kw = chunk.split(None, 1)[0]

        if kw == "$scope":
            parts = chunk.split()
            if len(parts) >= 3:
                cur_scope.append(parts[2])

        elif kw == "$upscope":
            if cur_scope:
                cur_scope.pop()

        elif kw == "$timescale":
            body = chunk[len("$timescale"):].strip()
            if body:
                timescale = body

        elif kw == "$var":
            m = _VAR_RE.match(chunk + " $end")
            if not m:
                continue
            width = int(m.group(1))
            vid = m.group(2)
            ref = m.group(3).strip()
            base = ref.split()[0]

            # Verilog 的 **escaped identifier**：`\surv[9]` 的名字其實是 `surv[9]`，
            # 那個反斜線只是跳脫記號，不是名字的一部分。OpenSTA 讀 netlist 時存的是
            # `surv[9]`，而 Icarus 的 VCD 把反斜線也一起寫出來。
            #
            # 少了這一行，SAIF 會寫成 `\surv\[9\]`，OpenSTA 直接 **parse error**，
            # annotation 掉到 0% —— 而症狀會偽裝成「功耗竟然不隨輸入改變」。
            #
            # 為什麼 M0 的 counter 沒抓到：它是扁平設計，沒有 escaped identifier。
            # 這裡是 Yosys 把 `logic surv [NSTATES]`（**unpacked** array）
            # 拆成 \surv[0] … \surv[63] 才產生的。
            if base.startswith("\\"):
                base = base[1:]

            if vid in id_to_bits:
                # VCD 會把完全相同的訊號共用同一個 id（alias）。
                # 同一批 Net 物件要同時掛在兩個 scope 下——活動量相同，位置不同。
                bits = id_to_bits[vid]
            else:
                bits = [Net() for _ in range(width)]
                id_to_bits[vid] = bits

            lst = scope_nets.setdefault(tuple(cur_scope), [])
            if width == 1:
                lst.append((base, bits[0]))
            else:
                mm = re.search(r"\[(\d+):(\d+)\]", ref)
                if mm:
                    msb, lsb = int(mm.group(1)), int(mm.group(2))
                else:
                    msb, lsb = width - 1, 0
                step = -1 if msb >= lsb else 1
                # bits[0] 是 VCD 位元字串的最左邊 = msb
                for k, bit_idx in enumerate(range(msb, lsb + step, step)):
                    lst.append((f"{base}[{bit_idx}]", bits[k]))

    return timescale


def parse_and_accumulate(stream):
    """單次掃描 VCD，回傳 (scope_nets, id_to_bits, timescale, duration)。

    id_to_bits[vcd_id] 是一個 list，index 0 對應 MSB（與 VCD 的位元字串順序一致）。
    """
    scope_nets = {}
    id_to_bits = {}
    t = 0

    # --- 宣告區：整段讀進來再解析（它是有界的，不影響串流的常數記憶體特性）---
    header_parts = []
    for line in stream:
        header_parts.append(line)
        if "$enddefinitions" in line:
            break
    timescale = _parse_header("".join(header_parts), scope_nets, id_to_bits)

    # --- 值變化區：逐行串流 ---
    for line in stream:
        line = line.strip()
        if not line:
            continue

        # --- 值變化區 ---
        c = line[0]
        if c == "#":
            t = int(line[1:])
            continue
        if c in ("b", "B"):
            val, _, vid = line.partition(" ")
            vid = vid.strip()
            bits = id_to_bits.get(vid)
            if bits is None:
                continue
            s = val[1:]
            # VCD 的向量值是左側截斷的：不足寬度時要補到原寬度。
            # 補什麼要看最高位：0/1 補 '0'，x/z 補該字元（IEEE 1364 的規則）。
            w = len(bits)
            if len(s) < w:
                pad = s[0] if s and s[0] in "xXzZ" else "0"
                s = pad * (w - len(s)) + s
            elif len(s) > w:
                s = s[-w:]
            for k in range(w):
                ch = s[k]
                nv = ch if ch in "01" else "x"
                if bits[k].val != nv:
                    bits[k].change(t, nv)
            continue
        if c in ("r", "R"):
            continue   # 實數：本專案用不到
        if c in _SCALAR_VALS:
            vid = line[1:].strip()
            bits = id_to_bits.get(vid)
            if bits is None:
                continue
            nv = c if c in "01" else "x"
            if bits[0].val != nv:
                bits[0].change(t, nv)
            continue
        # $dumpvars / $end / $comment 之類：忽略
    return scope_nets, id_to_bits, timescale, t


def emit_saif(out, scope_nets, timescale, duration, escape_brackets):
    """輸出巢狀 INSTANCE 結構的 SAIF。

    OpenSTA 的 read_saif -scope 需要 SAIF 的 INSTANCE 路徑與設計的 root 對得上，
    所以這裡必須忠實重建 VCD 的 scope 階層，不能攤平。
    """
    def esc(name):
        # SAIF 對 [ ] 的處理各家不一。Synopsys 系的慣例是加反斜線跳脫。
        # 這個開關存在的理由：M0 的 counter 煙霧測試就是要用實測決定哪一種能被 OpenSTA 接受，
        # 而不是靠猜。
        if escape_brackets:
            return name.replace("[", "\\[").replace("]", "\\]")
        return name

    # 建立 scope 樹
    tree = {}
    for path, nets in scope_nets.items():
        node = tree
        for p in path:
            node = node.setdefault(p, {"__nets__": [], "__kids__": {}})["__kids__"]
        # 回到該 scope 的節點掛 nets
        node2 = tree
        for i, p in enumerate(path):
            entry = node2[p]
            node2 = entry["__kids__"]
        entry["__nets__"] = nets

    def write_instance(name, entry, indent):
        pad = "  " * indent
        out.write(f"{pad}(INSTANCE {name}\n")
        nets = entry["__nets__"]
        if nets:
            out.write(f"{pad}  (NET\n")
            for nname, net in nets:
                net.flush(duration)
                out.write(
                    f"{pad}    ({esc(nname)}\n"
                    f"{pad}      (T0 {net.t0}) (T1 {net.t1}) (TX {net.tx})\n"
                    f"{pad}      (TC {net.tc}) (IG 0)\n"
                    f"{pad}    )\n"
                )
            out.write(f"{pad}  )\n")
        for kid_name, kid in entry["__kids__"].items():
            write_instance(kid_name, kid, indent + 1)
        out.write(f"{pad})\n")

    # VCD 的 timescale 可能是 "1ps"、"1 ps"、"10ns" …。SAIF 的 DURATION 是以這個單位計的，
    # 單位搞錯就等於把整條翻轉密度乘上或除以 1000——而且不會有任何錯誤訊息，
    # 只會讓 switching power 靜靜地錯掉。
    m = re.match(r"(\d+)\s*([munpf]?s)", timescale.strip().replace(" ", ""))
    if not m:
        raise SystemExit(f"vcd2saif: 無法解析 VCD 的 timescale: {timescale!r}")
    ts_num, ts_unit = m.group(1), m.group(2)

    out.write("(SAIFILE\n")
    out.write('  (SAIFVERSION "2.0")\n')
    out.write('  (DIRECTION "backward")\n')
    out.write('  (DESIGN)\n')
    out.write('  (VENDOR "fec-cosim")\n')
    out.write('  (PROGRAM_NAME "vcd2saif.py")\n')
    out.write('  (VERSION "1.0")\n')
    out.write("  (DIVIDER / )\n")
    out.write(f"  (TIMESCALE {ts_num} {ts_unit})\n")
    out.write(f"  (DURATION {duration})\n")
    for name, entry in tree.items():
        write_instance(name, entry, 1)
    out.write(")\n")


def main():
    ap = argparse.ArgumentParser(description="串流把 VCD 轉成 SAIF")
    ap.add_argument("--out", required=True, help="輸出的 SAIF 路徑")
    ap.add_argument("--vcd", default="-",
                    help="輸入 VCD（預設 '-' = stdin，配合 FIFO 使用時 VCD 不落地）")
    ap.add_argument("--no-escape-brackets", action="store_true",
                    help="net 名稱中的 [ ] 不加反斜線跳脫")
    args = ap.parse_args()

    stream = sys.stdin if args.vcd == "-" else open(args.vcd, "r")
    try:
        scope_nets, id_to_bits, timescale, duration = parse_and_accumulate(stream)
    finally:
        if stream is not sys.stdin:
            stream.close()

    n_nets = sum(len(v) for v in scope_nets.values())
    with open(args.out, "w") as f:
        emit_saif(f, scope_nets, timescale, duration,
                  escape_brackets=not args.no_escape_brackets)

    total_tc = sum(n.tc for bits in id_to_bits.values() for n in bits)
    print(f"vcd2saif: {n_nets} nets, duration={duration} {timescale}, "
          f"total toggles={total_tc} -> {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
