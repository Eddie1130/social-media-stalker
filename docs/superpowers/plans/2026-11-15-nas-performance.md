# NAS Performance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修正四類已量測的穩定性與效能問題，保留既有媒體與通知語意。

**Architecture:** 先建立共同量測，再減少 Instagram 大 JSON 重寫，隔離 TikTok 瀏覽器／下載排程與 Telegram 媒體／互動處理。使用既有容器、單 writer 與明確 IPC，不增加正式 Bot 實例。

**Tech Stack:** Node.js 22+、Python 3.12 容器、SQLite、Playwright／Chromium、Docker Compose。

**Spec:** `../specs/2026-11-15-nas-performance-design.md`，執行前必讀。

## Global Constraints

遵守 Spec「跨階段約束」全部內容；主服務只在 NAS。所有實作先離線測試及 review，再針對性同步；不直接覆蓋 NAS 六項已知差異。此文件本次僅作規劃，沒有授權同時執行多個正式 writer。

## Review Focus

- 新增／移除訂閱與在途工作競爭：以送出時的授權與 generation 為準。
- 慢磁碟與 Telegram 429：性能統計必須保留異常樣本及退避原因。
- 子程序當機：資料仍可恢復，不藉由刪除任務解鎖。
- 斷電／checkpoint 失敗：未提交結果不能對外宣稱成功。
- 更新失敗：保留 forward state，rollback 不使用過期快照覆蓋新收據。

## 執行順序

1. M0/M1：鎖定實際部署與建立量測。
2. [I/O 子計畫](2026-11-15-nas-io-archive.md) I1/I2：先處理最大、最直接的磁碟寫入來源。
3. [TikTok 子計畫](2026-11-15-nas-tiktok.md) T1/T2/T3：局部恢復、查詢／下載分離、新鮮度排程。
4. [Telegram 子計畫](2026-11-15-nas-telegram.md) G1/G2/G3：狀態交易、媒體隔離、互動優先。
5. I3：用同負載結果調整背壓；最後 M2 做全系統 NAS 驗收。

每項獨立測試、review、部署與回滾；不把三個架構變動一次上線。Telegram 與 TikTok 子計畫也可獨立交付，但壓力控制必須最後根據成效設定。

### M0：確認版本與部署邊界

**Files:** Create `docs/nas-performance-baseline.md`; inspect `docs/nas-operations.md`、NAS `.env`、Git 與容器資料卷。

**Interfaces:** 產出 release manifest：commit、實際檔案 hash、映像 ID、環境變數「名稱」與三類 named volume 名稱；不包含憑證內容。

- [ ] 重新確認本機未提交變更（規劃期間另有 `src/catalog-watch.mjs`／`test/catalog.test.mjs`／`docs/instagram-operations.md` 的 latestScan 修改），不覆蓋他人進行中的工作。比對 `7875df7` 與 NAS 六項內容差異，記錄 manual 路徑相容性及是否屬本次變更；不要把未部署的功能暗中混進效能修改。
- [ ] 備份 source、設定、SQLite（backup API 或停止 writer）、收據與映像；保留完整 profile，檢查空間及檔案權限。
- [ ] 確認每份資料的唯一 writer；以失敗注入驗證重啟後沒有第二個 Bot poller／browser profile writer。
- [ ] 記錄目前三項健康：process heartbeat、平台 freshness、queue progress；不把 pending 當成下載錯誤。

### M1：可比較的量測與壓力 fixture

**Files:** Create `src/performance-metrics.mjs`, `tiktok/catalog_metrics.py`, `scripts/collect-nas-performance.py`, `test/performance-metrics.test.mjs`, `test/test_catalog_metrics.py`; modify `src/telegram-control.mjs`, `src/telegram-client.mjs`, `tiktok/catalog_worker.py` 的觀測邊界。

**Interfaces:** JS `record(name, durationMs, dimensions={})`；Python `record(name, duration_ms, dimensions=None)`；`snapshot()` 回傳 bounded counters／histograms。只允許固定 metric 名稱與 allowlist dimensions，collector 每 60 秒輸出 aggregate；各服務把當期摘要接入既有 15 秒健康輸出供 I3 取樣，不逐項額外 fsync。

- [ ] 紅燈測試：時鐘倒退不產生負耗時；容量固定；含憑證的 dimension 被拒絕；p95 以同一固定分桶規則計算。
- [ ] 實作 ingress→ack／menu、event loop lag、settings commit、API slot／HTTP、browser query／navigation／restart、media bytes／download／fsync、queue added／completed／failed／oldest age。
- [ ] Collector 只讀 `/proc` 與健康摘要；不可額外 getUpdates 或合成正式 Telegram 訊息。不可把不可讀 kernel log 當成沒有 OOM。
- [ ] 執行 `node --test test/performance-metrics.test.mjs` 與 `python3 -m unittest discover -s test -p test_catalog_metrics.py -v`；以 4 帳號／16 streams、5000 media fixture、2 秒 fsync、120 秒掛起查詢、429、worker crash 建立後續測試共同資料。
- [ ] 正常負載與實際回補負載各保留至少 30 分鐘 baseline；小樣本標示 N，不假稱手機端延遲已量到。

### M2：逐項部署與 24 小時驗收

**Files:** Modify `docs/nas-operations.md`, `docs/nas-performance-baseline.md`；各子計畫的測試報告。

**Interfaces:** 每階段結果包括 manifest、query rate、archive rate、freshness、latency 分位數、I/O、restart／error counts，以及是否達標。

- [ ] 每項完成後做相應 Python／JS reviewer gate；提交前 `npm audit`，若 Python 依賴變更另做 pip audit；檢查 diff 不含憑證。
- [ ] 依 affected service 部署。catalog 使用 `./igctl up -d --no-build tiktok-vpn tiktok-catalog`，不使用已知會破壞 network_mode 的 `--no-deps`；Bot 避開在途傳送再重啟。
- [ ] 部署後核對 source hash、image ID、授權名單、offset、資料卷及已傳收據；只看到 healthy 不算驗收。
- [ ] 同負載比較 M1 指標，正常與 backlog 兩組分開；每一階段先觀察 30–60 分鐘，完整方案再觀察 24 小時及一次受控重啟。
- [ ] 超過 baseline 2 倍的 p95 延遲持續 10 分鐘、出現漏任務／重複通知、持續 SQLITE_BUSY 或重啟迴圈時停止擴大部署；保存故障現場與新狀態。
- [ ] rollback 僅切回相容程式／映像，不回灌部署前 offset、收據或資料庫。退出時間超過寬限的工作應保留可恢復狀態；舊新 writer 絕不並存。

## 額外效能機會的取捨

優先做：重複 checkpoint 合併、進度索引／增量計數、空佇列跳過掃描、按檔案 mtime/version 快取穩定設定、單一分段工作、可量測的背壓。這些由 I/O 子計畫負責。

暫不做：更多 Chromium、提高所有並行數、減少媒體品質、關閉 fsync、移除 VPN、調高所有 timeout、直接改用大型資料庫服務。SSD／快取及資料布局調整列為後續可選項：先確認實際硬體、掛載類型及 I/O 數據，不在本輪假設或購買硬體。
