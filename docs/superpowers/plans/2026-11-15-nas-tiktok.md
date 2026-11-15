# NAS TikTok Reliability and Scheduling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 瀏覽器故障可局部恢復；查詢等待時下載仍持續，降低 Story／貼文更新延遲。

**Architecture:** 一個 SQLite owner 協調器、一個持有 Playwright 的 browser 子程序、最多三個純檔案媒體 worker。所有 cursor／baseline／outbox 更新由協調器套用並提交。

**Tech Stack:** Python 3.12 subprocess／JSON IPC／concurrent.futures、既有 SQLite 與 Chromium。

**Spec:** `../specs/2026-11-15-nas-performance-design.md`。

## Global Constraints

遵守 Spec 全部約束。唯一 browser writer；不以多分頁／多實例硬解容量，不對 session 做無限制重建；empty body 不能代表 feed 結束。先完成 M1。

## Review Focus

- API HTTP 200 但空內容：cursor、baseline、lastSuccess 不前進。
- Chromium 在 park／pause／navigate／fetch 各階段斷線：只恢復 browser。
- CAPTCHA／登入失效：停止平台請求並顯示人工處理，下載已知媒體可繼續。
- IPC 逾時後收到舊回覆：requestId／epoch 不符必須忽略，不能重複入列。
- 下載中移除帳號、跨帳號同 origin、程序當機：不丟任務，不重複檔案 writer 或通知。

### T1：分類與局部恢復

**Files:** Create `tiktok/catalog_errors.py`, `test/test_catalog_recovery.py`; modify `tiktok/catalog_worker.py` 的 SessionProvider、`tiktok/catalog_browser.py`, `tiktok/catalog_provider.py`, `test/test_tiktok_catalog.py`。

**Interfaces:** `classify_failure(error, response_meta=None) -> Failure(category, safe_code, retryable)`；category 固定為 transport、empty_response、network、rate_limit、auth、captcha、parse_contract、storage。`SessionProvider.recover(failure)` 只關閉並清空自己的 browser 參照，保留 profile。

- [ ] 紅燈測試：idle park 失敗不再使 main 整體退出；close 本身失敗仍重設參照；cookie 檔及 marker 不受破壞。
- [ ] 紅燈測試：空 body、錯誤 JSON、合法空 feed、CAPTCHA 各有不同分類；所有失敗均保留 cursor／baseline；有效空 feed 才使用現有 checked_page 契約。
- [ ] 實作有限恢復：transport 每工作最多重建一次；empty response 同 session 最多額外一次重試，加入 1–3 秒 jitter；仍失敗回現有退避。429 尊重 retry_after；auth／CAPTCHA 不自動反覆重登。
- [ ] stdout/stderr 只輸出安全分類、來源 frame 與耗時，不能輸出原始 response、token 或 URL。三次連續失敗通知語意保持。
- [ ] 執行 `python3 -m unittest discover -s test -p test_catalog_recovery.py -v` 及 catalog 既有測試；在 NAS 用臨時 profile 驗證故障注入，不操作正式帳號寫入功能。

### T2：非阻塞協調器與唯一瀏覽器程序

**Files:** Create `tiktok/catalog_browser_worker.py`, `tiktok/catalog_query.py`, `tiktok/catalog_scheduler.py`, `test/test_catalog_scheduler.py`; modify `tiktok/catalog_worker.py`, `Dockerfile.tiktok-catalog`, `compose.tiktok.yml`, `test/test_tiktok_catalog.py`。

**Interfaces:** `QueryJob(request_id, epoch, name, kind, cursor, item_id, generation_fingerprint)`；`BrowserWorker.submit(job)`／`poll_results()` 非阻塞；`QueryResult` 對應 ID、epoch、結果或安全 Failure。單次 job 整體 timeout 初值 180 秒，可配置；navigation 仍最多 120 秒。

- [ ] 把 `Catalog.poll` 拆為 `prepare_poll(...) -> QueryJob|None` 與 `apply_poll_result(job,result,current_settings)`；入列、身份及分頁檢查仍先驗證再 transaction。manual_requests／repair 同樣拆分並走同一 browser queue。
- [ ] 紅燈測試：假 browser 掛 120 秒，三個下載仍完成並由 owner 提交；所有 DB 呼叫都在 owner；outbox 不因 browser crash 重送；舊 epoch 回覆被丟棄。
- [ ] 協調器每 ≤250ms 收結果、提交、派最多三個媒體工作；50 筆／15 秒保留為單次取候選的上限，不再限制整個輪巡只有一段時間能下載。候選使用 bounded queue／低水位補貨，不預載整個歷史。
- [ ] browser timeout 終止整個子程序群組、等待退出，確認 profile writer 消失後才重啟。保留 warm browser 及 cookies；子程序 stdout 是有界 JSON protocol，stderr 安全分類。
- [ ] 同 origin ID 的 post／repost／跨帳號仍互斥；失敗保留 retryAt；下載完成後以最新訂閱 generation 決定通知資格。舊基準保持靜默。
- [ ] 停止時不再派工；IPC 取消／下載中斷後留下原 pending 任務。超過容器寬限不能錯標 ready；現有長分段另由 I3 限制並保留恢復路徑。
- [ ] 執行 scheduler／catalog／layout 回歸及 SQLite integrity_check；先在隔離 fixture 驗證 SIGTERM、SIGKILL 與重啟，再部署唯一 catalog。

### T3：到期排程、容量與功能健康

**Files:** Modify `tiktok/catalog_scheduler.py`, `tiktok/catalog_provider.py`, `tiktok/catalog_worker.py`, `src/platform-status.mjs`, `test/test_catalog_scheduler.py`, `test/tiktok.test.mjs`, `.env.tiktok.example`, `docs/tiktok-integration.md`。

**Interfaces:** `select_query(now, streams, manual_jobs, repair_jobs, pressure) -> QueryJob|None`；`workflow_health()` 產出 queryAgeMs、dueLagMs、backoffUntil、browserRecoveries、oldestPendingAgeMs，維持既有欄位相容。

- [ ] 紅燈測試：同時到期的 Story 優於歷史頁；每輪最多連續兩筆手動工作，之後讓到期 Story 前進；多帳號公平；backoff 不被優先級繞過；pressure 只抑制歷史 discovery。
- [ ] 以最早到期時間選工作，次序為手動（有界）／到期 Story／正常貼文轉發／profile／歷史頁／repair。保留 Story 120s、post/repost 300s、profile 1800s 預設，不暗中延長。
- [ ] 最多合併同帳號三個工作以攤銷導航；其他 Story 已 overdue 時不能延後它來湊批。僅快取驗證過的 userId/secUid 等身份解析，TTL 300s；profile 查詢強制刷新，feed／cursor 不快取。
- [ ] 用 M1 算 U，分列成功／重試／導航成本；若單瀏覽器容量不足，先顯示不能達成的 freshness 目標並提出取捨，不開第二份 profile writer。
- [ ] 平台狀態區分 process alive、查詢失敗、正常 backoff、資料過舊與封存積壓；首次暫時錯誤不假稱完全正常，也不觸發容器重啟風暴。
- [ ] 四帳號／16 streams 與慢查詢 fixture 驗證排程；NAS 觀察 24 小時的 Story／post p95 age、catalog restart、archive drain，對照 Spec 目標。
