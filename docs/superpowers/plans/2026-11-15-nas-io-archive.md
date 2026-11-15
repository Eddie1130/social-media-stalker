# NAS I/O and Instagram Archive Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 減少大 JSON 重寫、磁碟同步與空掃描，讓歷史封存更快而不拖慢互動及新內容。

**Architecture:** 每檔單 writer 的非同步快照交易，僅對可重放的封存進度 group commit；原始任務與外部傳送收據立即耐久。先保持舊 schema，再根據量測做背壓。

**Tech Stack:** Node.js fs/promises、既有 JSON、Python ThreadPoolExecutor、既有 ffmpeg stream copy。

**Spec:** `../specs/2026-11-15-nas-performance-design.md`。

## Global Constraints

遵守 Spec 全部約束。只優化既有資料結構的寫入方式；不得降低 JSON／SQLite 的既有耐久保障，不能讓多個 writer 改同檔。M1 指標先完成。

## Review Focus

- 磁碟滿／rename 失敗：不發布新快照、不回報完成。
- 兩個媒體同時完成：group commit 不丟掉其中一份更新。
- 關機發生在檔案發布與 checkpoint 之間：仍能驗證及重用已下載檔。
- Story／手動任務持續到來：歷史回補公平前進，不壟斷查詢。
- 429、取消訂閱、uncertain：傳送收據不可混入批次延後確認。

### I1：非同步單 writer 與重複寫入消除

**Files:** Create `src/atomic-state-store.mjs`, `test/atomic-state-store.test.mjs`; modify `src/catalog-watch.mjs`, `test/catalog.test.mjs`。

**Interfaces:** `AtomicStateStore({file, initial, writeSnapshot})`; `current()` 回傳已提交快照；`transact(mutator): Promise<snapshot>` 序列執行；`flush(): Promise<void>`；`recover(): Promise<snapshot>` 在 owner 明確處理錯誤後重新載入最後已提交快照。`writeSnapshot` 使用 write→file sync→close→rename，舊 `atomic()` 不全域替換。

- [ ] 紅燈測試：兩筆同時交易都保存；fsync 失敗時 current 不變、store 進入 failed 並拒絕後續交易，recover 前不能越過失敗交易；rename 前當機舊檔可讀；同內容不新增 fsync；新建／遺失目錄不可被錯誤視為已保存。
- [ ] 用 fs/promises 實作交易與唯一 per-file writer，禁止 fire-and-forget；寫入失敗保持 dirty 並向 caller 傳遞錯誤，處理停止及暫存檔清理。
- [ ] CatalogWatcher 所有變更走 owner 交易；保留目前其他工作正在加入的 posts.latestScan 與 history cursor 分離欄位，不刪除未知但合法的相容欄位；刪除同一輪無變更的 persist，以及傳送成功後又只因 lastAttemptAt 重複保存的 checkpoint。`ingest`／`check`／`deliver` caller 全部 await，schema 與外部事件格式保持相容。
- [ ] 執行 `node --test test/atomic-state-store.test.mjs test/catalog.test.mjs test/multi-target.test.mjs`；慢 fsync fixture 下其他查詢 timer 仍前進，且執行緒外沒有 writer。

### I2：Instagram 完成進度 group commit

**Files:** Create `src/archive-progress.mjs`, `test/archive-progress.test.mjs`; modify `src/catalog-watch.mjs`, `src/story-archive.mjs`, `src/archive-batch.mjs`, `test/catalog.test.mjs`, `test/story-archive.test.mjs`。

**Interfaces:** `ArchiveProgress({store,maxItems:10,maxDelayMs:1000})`; `complete(key, patch): Promise<void>` 僅在該批耐久保存後 resolve；`flush()` 在 yield／stop／batch 結尾執行。`archiveBatch` 新增可測試的 `concurrency=3` 選項，預設保持相容。

- [ ] 紅燈測試：100 筆成功進度的狀態同步次數 ≤ 原方案 50%；其中一筆失敗仍保存其他完成項目；計時器及 item threshold 都觸發；stop 必須 flush 或留下可重放任務。
- [ ] 紅燈重啟測試：檔案已發布但 progress 未提交時，重新驗證完整檔後重用；壞檔／.part 不當成成功；outbox 與已傳收據保持原來的逐筆 checkpoint。
- [ ] 只將 archiveDone／caption savedHash 類進度接入 group commit；任務入列仍先保存再刪來源事件，Telegram 發送不得早於必要的封存 checkpoint。
- [ ] 執行 `node --test test/archive-progress.test.mjs test/archive-batch.test.mjs test/catalog.test.mjs test/story-archive.test.mjs`；用 5000 項 fixture 量寫入 bytes、fsync 數、elapsedMs，對照 M1。

### I3：掃描、快取與負載背壓

**Files:** Create `src/archive-pressure.mjs`, `test/archive-pressure.test.mjs`, `tiktok/catalog_pressure.py`, `test/test_catalog_pressure.py`; modify `src/watch-media.mjs`, `src/catalog-watch.mjs`, `src/telegram-control.mjs`, `src/tiktok-delivery.mjs`, `src/x-delivery.mjs`, `tiktok/catalog_worker.py`, `tiktok/catalog_media.py`, `.env.example`, `.env.tiktok.example`。

**Interfaces:** `PressureController.observe({checkpointP95Ms,eventLoopP95Ms,oldestInteractiveMs})`; `limits()`／Python `limits()` 回傳 `downloadConcurrency` 與 `allowHistoricalDiscovery`。共用壓力摘要固定由 `ig-telegram` parent 的 `createPressurePublisher({stateDir,controlMetrics,readServiceMetrics})` 寫入 `/app/state/io-pressure.json`，每 5 秒取樣各服務最近 15 秒的健康／耗時摘要；publisher 使用非同步寫入，不掃描媒體目錄；摘要為可重建 telemetry，不含正式工作狀態。IG/TikTok/X 各自 owner 讀取摘要並套用自己的上限，不能宣稱三個局部上限等於全域 semaphore。

- [ ] 紅燈測試：連續三次取樣 checkpoint p95>500ms 或 eventLoop p95>200ms／互動佇列>1000ms 時，背景下載降至一工並暫停歷史 discovery；六次取樣皆低於 250ms／100ms／500ms 才逐級恢復，避免抖動。
- [ ] 壓力摘要超過 30 秒未更新時採一工保守值，但仍每 60 秒允許一筆歷史工作以免永久飢餓；Story 查詢、直播與使用者操作不被暫停。門檻先作可配置初值，部署前用 M1 校準。
- [ ] 盤點四個 TikTok delivery lane 對同目錄的重複掃描，使用單次 inventory fan-out；佇列無變更時按安全的 mtime/version 快取並以 5 秒 reconciliation 保證外部新增不漏收。空事件不再造成 JSON 全量 persist。
- [ ] 保持最多三個下載工作，將大型影片分段另限為同一 catalog 中一個工作，保留原始影片與 stream copy，不降低品質；失敗／取消須釋放 permit。
- [ ] Python 健康計數至少每 15 秒或狀態變更時更新，避免每一個 poll 都 GROUP BY 全 items。先用 EXPLAIN QUERY PLAN 與 profile 確認 hot query；有證據才新增索引。
- [ ] 執行 `node --test test/archive-pressure.test.mjs test/x-delivery.test.mjs test/tiktok.test.mjs` 及 `python3 -m unittest discover -s test -p test_catalog_pressure.py -v`；JS/Python 使用相同壓力序列 fixture 驗證 limits 一致；對 5000 個事件資料夾確認無漏收、無同時處理同一 receipt、無重複傳送。
- [ ] 跑同負載 NAS 比較；只有 backlog net drain 改善且互動／新鮮度不惡化才採用較高上限。若依舊受硬體限制，報告量測結果再規劃資料布局。
