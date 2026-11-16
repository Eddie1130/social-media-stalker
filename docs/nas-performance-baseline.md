# NAS 效能改善執行基準

執行分支：`perf/nas-throughput`；隔離基準 `604359f` 是 `7875df7` 加既有工作目錄與計畫的快照，並非宣稱 NAS 全部檔案相同。

## 部署前

- NAS HEAD `4cefeee`，catalog 映像 `9f9b5f84d3fa`，Telegram 映像 `c85327cf5dc2`。
- 已有四個授權使用者。部署保留原 NAS `.env*`、所有 users／generation、offset、收據及三個 named volume；不把 ID 或憑證放入本文件。
- NAS 既有相簿順序與 retry-blocking 改善比隔離快照較新：三方合併保留。TikTok manual 路徑功能仍依 NAS 舊行為，不混入這次部署。
- 從 NAS 讀取追蹤 source 作為部署前 manifest；正式套用前逐檔檢查原 hash，若其間被其他工作更改則停止套用並重新合併。
- 只讀基準每 60 秒取樣，原 `/tmp` 取樣曾被 catalog 重啟中斷；現使用獨立唯讀觀測容器，實際檔案位於 NAS `data/backups/nas-performance-20261115/observer.jsonl`，2026-11-16 已累積約 13 小時。這是觀測，不會呼叫 getUpdates 或發送訊息。舊版缺少的分段耗時不能偽造比較。

## 實作與測試

- 有界 JS／Python metrics，保留 N、histogram 分位數與安全 dimensions；不保留訊息內容或 URL。
- AsyncStateStore：單檔序列交易、保存成功才發布；mutator 驗證錯誤不鎖死 store，實際持久化錯誤才進 failed。
- 封存進度 group commit：最多 10 筆／1000 ms，正式傳送收據不延後確認。
- TikTok：一個 browser 子程序、一個 SQLite owner、最多三個持續媒體工作；IPC 等待時 cooperative pump，沒有第二個 DB writer。STOP 可取消掛起查詢。
- TikTok 完成時重讀最新 record，保留在途 generation／extraRecipients／caption 更新；checkpoint 失敗保留 completion，不永久卡 busy key。
- Telegram：唯一 poller／API limiter，單一 delivery child；在授權檢查與 webhook guard 通過後才啟動派送。
- 子程序保留非敏感 Local API endpoint，因此 2GB 上限不退回 50MB；原始媒體使用 source descriptor 串流，僅小縮圖 spool。
- 個人媒體與 summary 也有最終 eligibility、durable inflight 及 uncertain 保護。結果不確定不自動重送，仍保留供檢查。
- 正常時三工；持續 I/O 壓力下降為一工；恢復有遲滯。歷史探索被抑制時仍每 60 秒有進度機會，不暫停 Story／直播／互動。

## 驗收狀態

完整本機驗證與 NAS 部署結果於部署後補記。24 小時 soak 尚未完成前不得宣稱通過；需分開記錄程序健康、內容新鮮度及佇列進度。

## 已作的實作取捨

1. 保留 constructor／discovery 同步 checkpoint 以維持既有 callers 的耐久契約；先把最重的封存進度與 Bot settings 移到非同步。殘餘同步成本仍在 metrics 中。
2. TikTok 使用 cooperative owner loop，避免把現有分頁交易切成多 writer；browser IPC 等待時由同一 owner 處理媒體完成。若 future pump 變得耗時，需要由 metrics 再拆分。
3. transport 工作保留現有退避，下一筆重建 browser；空回應最多額外重試一次，不無限重建、不把空回應當成成功。
4. prepare 後若收件者設定在 HTTP 前改變，先保守重試而非丟棄內容；真正失去資格的工作由下一次 eligibility 檢查取消。

## 2026-11-16 部署結果

- 實作提交 `5cbc047`；本機 364 個 Node、145 個 Python 測試通過，npm audit 無已知漏洞。NAS 隔離環境 362 個 Node、4 個 X 整合案例、144 個 Python 測試通過；真實 Chromium 生命週期／重啟登入還原測試通過。
- 10:24–10:28 HKT 啟動新版。53 個部署檔案 hash 全部吻合 manifest；catalog 映像 `8b39507ce1b0`，Telegram 映像 `cd66d549d83b`。
- NAS 原始碼／私有設定、control/watch 狀態及 catalog profile 備份位於 `data/backups/nas-performance-20261116/`，舊映像保留 `before-perf-20261116` tag。初次狀態備份因直播 writer 仍活動而中止，停止該 writer 後重新完成，未使用不完整備份進行套用。
- 實際採用停止相關 writer、備份、啟動 Telegram publisher、再啟動 IG／X／TikTok consumers 的順序，避免混版寫入與缺少 pressure summary。VPN 沒有重建。舊 catalog 停止超過 grace period 被 Docker 終止，profile 備份於停止後執行。
- 驗收時本專案所有有 healthcheck 的服務皆 healthy；Telegram `pollOk/telegramOk/deliveryReady=true`、個人派送 pending=0，四個授權使用者與持續前進的 offset 保留。啟動後有短暫 400 重試，稍後自行消退，未清除收據或重設 offset。
- TikTok 待下載由 653 降至 638；20 次媒體下載成功約 70 MB、17 個工作完成，5/16 個內容串流已有新成功結果。其餘仍需下一輪觀測，不能把 heartbeat healthy 當成所有內容均已刷新。原有 unresolved=1 保留。
- 新版部署後的 24 小時唯讀觀測另存 `data/backups/nas-performance-20261116/observer.jsonl`。24 小時 soak 尚未完成，使用者實際點擊按鈕的體感延遲尚未重新驗收，不宣稱固定倍數加速。
