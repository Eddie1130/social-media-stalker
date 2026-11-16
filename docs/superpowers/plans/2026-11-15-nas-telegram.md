# NAS Telegram Responsiveness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 媒體磁碟工作與大檔上傳不再阻塞按鈕處理，同時保留唯一 poller、共用限速與收據耐久性。

**Architecture:** 控制程序獨占 settings 與 TelegramClient；delivery 子程序獨占各媒體收據。透過有版本與 requestId 的 IPC broker 呼叫同一 API client；先驗證並保存 inflight，再開始 HTTP。

**Tech Stack:** Node.js 22 child_process IPC、fs/promises、現有 Telegram Local Bot API 與 JSON receipts。

**Spec:** `../specs/2026-11-15-nas-performance-design.md`。

## Global Constraints

遵守 Spec 全部約束。M1 及 I1 的 AtomicStateStore 完成後再執行；不建立第二個 getUpdates poller、不給 delivery 子程序 Bot token、不拆成互不共享的限速器。offset／授權／收據保存語意維持或提高。

## Review Focus

- 快速連點與 settings 非同步交易：不可讓舊 snapshot 覆蓋新 update 或 offset。
- 在授權取消／generation 改變時已排隊的傳送：真正送出前重新確認。
- worker 在 HTTP 前後死亡：區分未開始與結果不確定，不盲目重傳。
- 429／長上傳／STOP：所有 lane 共用 cooldown，按鈕不等整個影片傳完。
- 複製中的 IPC payload：不洩露 token、任意方法、任意 file 路徑或原始訊息到 log。

### G1：非同步 settings 與早期 callback 確認

**Files:** Create `src/telegram-state-store.mjs`, `test/telegram-state-store.test.mjs`; modify `src/telegram-control.mjs`, `src/telegram-menu.mjs`, `src/telegram-replies.mjs`, `test/telegram-latency.test.mjs`, `test/telegram-control.test.mjs`。

**Interfaces:** `SettingsStore` 包裝 I1 AtomicStateStore，`current()`、`transact(mutator)`、`flush()`；`authorizeUpdate(settings,update)` 共用私人聊天、ID、格式驗證；回覆刪除與 offset 更新使用交易而不是持有舊物件跨 await。

- [ ] 紅燈測試：兩筆更新與一筆回覆完成交錯，offset 單調且三份變更都保留；fsync 失敗不發布新設定或前進 offset；陌生 ID 不會收到提早 ack。
- [ ] 已授權有效 callback 收到後即可排確認，確認語意僅為收到；設定交易提交成功後才排選單結果。durable update 回放不重複套用操作，ack 重放安全，失敗及過期 ack 保持既有處理。
- [ ] 所有 settings 寫入（含 export reports、waiting prompt、reply retry）走 store；不在每筆回覆 clone 及改寫過期整份 snapshot。poll 仍須等本批 update 耐久後才能用新 offset 下一次 getUpdates。
- [ ] slow fsync fixture 下 ack／其他讀取 timer 前進；settings 寫入失敗顯示錯誤，不能先回成功選單。執行 `node --test test/telegram-state-store.test.mjs test/telegram-control.test.mjs test/telegram-latency.test.mjs test/archive-export.test.mjs`。

### G2：媒體 worker 與中央 API broker

**Files:** Create `src/telegram-delivery-worker.mjs`, `src/telegram-delivery-broker.mjs`, `test/telegram-worker.test.mjs`, `test/telegram-broker.test.mjs`; modify `src/telegram-control.mjs`, `src/telegram-client.mjs`, `src/telegram-delivery.mjs`, `src/manual-delivery.mjs`, `src/x-delivery.mjs`, `src/tiktok-delivery.mjs`, `Dockerfile.telegram`。

**Interfaces:** Worker 收 `settingsSnapshot(revision,value)`；broker protocol 為 `request(requestId,revision,method,body,fileDescriptors,eligibility)` → `prepare(grantId)` → `prepared(grantId)` → `result`。Worker 使用 `BrokerClient.call(...)` 保持現有 client.call 介面；beforeRequest 在 worker 執行並耐久保存，parent 收 prepared 後重驗授權再 HTTP。取消必須回明確未送出，不能猜測結果。

- [ ] 紅燈測試：worker 同步阻塞 2 秒／10 個 media 排隊／一支影片上傳 60 秒時，控制器仍收到 update 並可發 ack；只有 parent fetch 真的被呼叫；child env 無 token。
- [ ] 明列 method allowlist、body 大小上限、有效 requestId、回覆 schema、media descriptor 及既有路徑驗證。禁止把 function／Blob 穿 IPC；可從已驗證 local path 重新建構 upload，測試大檔不整份塞入 IPC／RAM。
- [ ] 單一 worker 擁有 IG／X／TikTok／manual 所有 receipt writer，內部保留 lanes；parent 保有共用 priority limiter 與 cooldown。不要把長 HTTP await 放進 broker 全域 mutex。
- [ ] 舊 revision 若仍符合最新 recipient／generation 可送，否則取消；worker 的 eligibility 判斷與 parent 最新設定都必須通過，直接回覆與其他通知也要保留原授權規則。
- [ ] 注入死亡：prepare 前無 HTTP；inflight 已保存但尚未送出若無可靠證據仍保守 uncertain；HTTP 後回覆遺失不重送；parent 死亡時 worker 停止並等待單一新 parent 接管。result 與 request replay 依 requestId 去重。
- [ ] 盤點 managed 模式其他直接 Bot API 路徑（watch-media、watchdog、Python LIVE）。有正式傳送者則改走既有 outbox／中央 broker，保留 standalone 模式；不能只隔離 controller 後宣稱全 Bot 共用限速。
- [ ] 執行 worker／broker 測試與 `manual-download`／`x-delivery`／`tiktok`／`telegram-control` 測試；review 後在 NAS 無在途上傳時單獨重啟 ig-telegram。

### G3：實際發送限速、背壓與持續驗收

**Files:** Modify `src/telegram-client.mjs`, `src/telegram-delivery-broker.mjs`, `src/telegram-control.mjs`, `test/telegram-latency.test.mjs`, `test/telegram-broker.test.mjs`, `docs/nas-operations.md`。

**Interfaces:** `TelegramClient.call` 沿用現有介面；broker 在 prepared 後再次取得實際 send slot，並記錄 plannedSlotMs／actualRequestMs。只有實際開始 HTTP 才更新對應聊天／全域發送時間，cooldown 同步適用所有 lane。

- [ ] 紅燈測試：beforeRequest fsync 花 2 秒時，不因舊的預約時間過期而把兩個同聊天 HTTP 擠在一起；priority 不繞過 chat1100ms／global40ms／429；取消 permit 不漏放或永久占用。
- [ ] 等待 prepare 的媒體不占用未來數秒時段；prepared 可能落後新互動，重新競爭 slot。send 檢查與時間記錄在同一 parent event loop turn 完成；授權變更再檢查。
- [ ] 使用者操作優先，但媒體 aging 後有公平機會；限制 pending IPC 數為 32，滿載時拒絕新背景派工且保留 durable queue，不丟任務。舊 menu edit 在實際送出前可判定 superseded，不能覆蓋新畫面。
- [ ] rate 等待使用可取消 timer，避免快速連點保留舊 timer／abort listener；STOP 取消未開始的 HTTP，在途結果仍循 uncertain 規則保存。
- [ ] 將 queue／state commit／slot／HTTP／checkpoint 分段量測，記錄 N 與 p50/p95/max；無使用者實測不能宣稱手機端達標。取得使用者操作或明確授權後才進行正式互動測試。
- [ ] NAS 正常與 backlog 負載各觀察 30–60 分鐘，驗證 Spec 目標及 24 小時 429／重複通知／worker restart 沒有增加；純網路慢與內部排隊分開報告。
