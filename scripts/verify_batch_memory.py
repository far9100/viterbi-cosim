"""verify_batch_memory.py — 驗算 B2 的 batch 回溯在**硬體上**真正需要的記憶體深度。

docs/memory_traceback_baseline.md §1 的表格寫「記憶體 64 x 2D」——那是演算法需要的
歷史長度，不是硬體需要的環狀緩衝深度。golden 保留完整歷史，所以看不出這個差別。

硬體上回溯進行中**寫入仍在繼續**：批次在 t_end 觸發、引擎跑 D 個 stage，
期間又寫進 D 筆，而它最舊要讀到 t_end-2D+1。本檔用窮舉把衝突找出來。

見 docs/errata.md 的 E-06。
"""
def conflicts(M, D):
    """記憶體 M 個 slot、深度 D。回傳 (是否有衝突, 第一個衝突的描述)。"""
    t_end = 10 * D            # 任取一個批次觸發點（夠大，避開開頭）
    # 引擎在 stage t_end+1 .. t_end+D 執行，每 stage 走 2 步
    for j in range(1, D + 1):
        w = t_end + j                       # 這個 stage 寫入的項目
        # 這個 stage 之後（含）還需要讀的項目：k = 2(j-1) .. 2D-1
        for k in range(2 * (j - 1), 2 * D):
            need = t_end - k
            if w % M == need % M:
                return True, (f"stage {w} 寫入 slot {w % M}，"
                              f"覆蓋掉還要讀的 stage {need}（步 k={k}）")
    return False, ""


for D in (32, 64):
    print(f"D={D}")
    for mult in (2, 3, 4):
        bad, why = conflicts(mult * D, D)
        print(f"  記憶體 {mult}D = {mult*D:3d}  ->  "
              + ("**衝突**：" + why if bad else "沒有衝突"))
