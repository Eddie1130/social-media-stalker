# NAS 穩定性與效能改善設計

日期：2026-11-15。狀態：規劃，尚未實作。範圍為 TikTok 瀏覽器失效、TikTok 更新延遲、Telegram 互動延遲、Instagram 歷史回補積壓。

## 已確認的基準與限制

- 本機／GitHub 基準 `7875df7`；NAS Git HEAD `4cefeee`，功能更新以工作目錄補丁部署，FETCH_HEAD 已有 `7875df7`。142 檔比對有六項差異，主要為尚未部署的 manual TikTok 路徑功能及 `.gitignore`，不能直接 pull 覆蓋。
- NAS：4 個邏輯 CPU、約 5.64 GiB RAM，核心不支援 CPU CFS quota。19:38 的 load 4.94，其中 I/O 等待 4.52；該次磁碟可用約 1.65 TB。這些是快照，不是全日平均。
- 今天保留的 TikTok 日誌有 40 次貼文 JSON 解析失敗、三次瀏覽器傳輸失敗相關重啟。空回應可能涉及 session、平台拒絕或瀏覽器故障，不能全部歸因於 NAS。
- Telegram 曾有約 8.6／11 秒的回覆排隊加處理時間；目前的紀錄不包含使用者點擊到控制器收到更新的時間。
- 先前測得 7 KB 原子寫入需 137–1168 ms；模擬 API 的單次回覆流程優化後仍需 1.2–1.4 秒。磁碟狀況會變動。
- Instagram 最大 catalog JSON 約 5,093,855 bytes；`CatalogWatcher.persist()` 每次重寫完整快照。媒體與文字完成後的重複 checkpoint 是具體可優化位置。
- TikTok 目前單一瀏覽器循序查詢所有到期項目，再以三工下載最多 50 筆，派工 15 秒。下載不會在查詢期間持續運作。大影片分段最久可達 1800 秒，不能把 15 秒當成整批或關機期限。

## 架構決策

### TikTok

保留同一個 catalog 容器及單一 SQLite writer。協調器持有資料庫與排程；瀏覽器改由一個子程序持有，IPC 一次只接受一個查詢；媒體工作池維持最多三工，僅操作檔案。瀏覽器等待不再阻塞下載派工及完成結果提交。

`Catalog.poll()` 拆為準備工作與套用結果，原本的身份、分頁、去重、訂閱 generation、baseline 與 outbox 規則都保留。手動下載、repair 也共用唯一瀏覽器佇列。瀏覽器子程序壞掉只重建它，不重啟協調器或清除 profile。

### Telegram

只有一個控制程序收取 getUpdates、修改 settings、持有 TelegramClient 限速器及呼叫 Bot API。媒體探索、磁碟操作、收據持久化移到單一 delivery 子程序，避免同一份收據由多個 writer 修改。子程序沒有 Bot token，不得自行呼叫 API。

使用有 requestId 的 IPC broker 及授權／generation 版本檢查。沿用 beforeRequest 的「實際傳送前保存 inflight」要求；子程序完成耐久 checkpoint 後才能開始 HTTP，傳送結果不確定時維持 uncertain，不自動重送。所有媒體 lane 與互動回覆共用一個 limiter；HTTP 請求不以單一上傳完成作為後續按鈕請求的鎖。

settings 改為唯一 owner 的非同步、序列化交易：保存成功後才發布新快照及 offset。已授權且格式有效的 callback 可先確認收到；確認不代表設定已完成，選單結果須等交易提交。所有其他正式 Bot API 呼叫來源須盤點，受管理模式不得另開獨立 limiter。

### Instagram 與 I/O

先保持既有 JSON schema。每檔只有一個非同步快照 writer；媒體／caption 完成進度採最多 10 筆或 1000 ms 的 group commit，寫入完成才向呼叫者確認。原始任務入列、offset、Telegram 已傳收據及 uncertain 標記不採延後確認。

下載檔必須先完整驗證並耐久發布。若檔案成功而進度尚未提交就當機，原佇列仍存在；重啟應驗證並重用檔案，不能丟棄任務或重新通知。單一 worker 失敗不得取消同批其他成功項目的 checkpoint。

先降低重寫與掃描成本，再做跨平台背壓。初期保留目前下載上限；壓力高時只降低歷史回補派工，不改變媒體品質、Story 查詢、直播錄影及使用者互動。不得以增加並行數當成唯一加速手段。

## 成效指標（驗收目標，尚非實測承諾）

| 指標 | 目標及測量條件 |
|---|---|
| Telegram 內部回覆排隊 | 正常負載 P95 < 300 ms；另列狀態提交、API 與磁碟時間 |
| 按鈕確認／選單 | 無 Telegram 限流且 API 正常時，收到 update 至確認 P95 < 1 秒，選單更新 P95 < 3 秒；手機端另由使用者測量 |
| TikTok 查詢與下載隔離 | 模擬查詢卡 120 秒，三個媒體工作仍能啟動、完成、提交，健康 heartbeat 繼續 |
| TikTok 新鮮度 | 先量查詢成本，容量允許時 Story P95 ≤ 180 秒、貼文／轉發 P95 ≤ 420 秒；backoff／登入限制獨立列出 |
| 瀏覽器恢復 | 可重現的失效在有限期限內局部恢復，測試與 24 小時觀察不再因此重啟整個 catalog |
| I/O | 同一 fixture 至少減少 50% 進度 checkpoint 次數；同負載磁碟寫入量下降，p95 磁碟等待與互動延遲不得惡化 |
| 歷史回補 | 正確區分新增／完成／失敗速率；停止新發現的測試條件下待辦必須淨下降 |
| 資料完整性 | 關機／斷線／重啟後沒有遺失任務、重複通知、錯誤 cursor 前進或未授權傳送 |

新鮮度的容量檢查使用 `U = Σ(query_cost / configured_interval)`，另外計入導航與重試成本。單瀏覽器 U 接近或超過 1 時不能承諾上述目標：先攤銷導航及身份解析，再提出明確的檢查頻率取捨，不偷偷延長間隔或多開登入實例。

## 跨階段約束

- 不更換資料庫產品、不加入 Redis／訊息中介、不增加第三方依賴，除非量測證明現有方案不足。
- 不清除 cookies、profile、歷史、offset、收據或待辦；不解除唯讀瀏覽器防護、不繞過 CAPTCHA、不把空回應視為空 feed。
- JSON Schema 第一輪維持相容；SQLite 保持單 writer，不以 `check_same_thread=False` 或降低 synchronous 換取表面速度。
- `.env*`、cookies 與 chat ID 名單保留 NAS 專用內容。不可啟動 Mac 第二份正式 Bot。
- 心跳與功能新鮮度分開呈現；積壓、退避、失敗各自顯示，不放寬綠燈條件掩蓋問題。
- 紀錄僅含安全錯誤分類、耗時、計數與匿名工作 ID；禁止 token、cookie、完整 URL、caption 或聊天內容。
- 一筆歷史影片沒有媒體網址不納入本輪必定修復目標；保留記錄，可在主修正後降低無效補查頻率。

## 參考依據

Node 官方說明同步工作會阻塞事件迴圈：https://nodejs.org/learn/asynchronous-work/dont-block-the-event-loop

Python SQLite 的連線執行緒約束：https://docs.python.org/3.12/library/sqlite3.html#sqlite3.connect

Telegram 官方限速指引：https://core.telegram.org/bots/faq#my-bot-is-hitting-limits-how-do-i-avoid-this
