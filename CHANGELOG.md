# Changelog

## 2026-11-21

- 修正 X 封存 ETA 的 CI 測試，接受日期與時間之間的一般空格及細空格，並保留對香港時間數值的驗證。

## 2026-11-20

- 移除 X／Twitter 指定日期回補按鈕及日期範圍指令入口，保留一鍵完整歷史封存。

- Instagram、X、TikTok 完成歷史封存後，Telegram 帳號選單會移除一鍵回補按鈕，並顯示已封存。
- 修正匯出將 Unicode 等價日文路徑及空白 caption.txt 誤報為缺失；Instagram 舊封存完成判斷改依掃描、媒體與說明狀態。

- Telegram 手動下載支援 Instagram、X、TikTok 貼文與直播共用進度通知，整批交付後自動刪除。

## 2026-11-19

- Telegram 手動下載 Instagram 連結時，入列通知不附返回按鈕；多連結共用進度訊息，整批處理完畢後自動刪除。

- Telegram 接受 TikTok LIVE 分享短連結與直播網址，可單次錄影並回傳給提出要求的使用者；同一帳號共用錄影，離線時回覆結果。

- TikTok 監看媒體附說明，IG 精選與 LIVE 多段錄影使用相簿，直播各段保留顯示比例及封面。

- IG 與 TikTok 新增訂閱預設監看新內容，帳號選單可申請歷史回補。

- Telegram 一般使用者固定接收媒體、停用每日摘要。

- 23:22–23:30 HKT 在正式 catalog 原 Chromium／VPN 工作階段被動觀察四個個人頁面。排定重試前 25 筆網站腳本貼文清單回應中，24 筆 HTTP 200、本文 0 bytes，1 筆含 19 個項目。23:30–23:32 四條 catalog 重試均為 HTTP 200、實讀 0 bytes。樣本未見明確 CAPTCHA；現有讀取防護仍啟用，未確定上游成因。
- TikTok 單帳號匯出沿用 catalog 的狀態／username 索引，在 SQL 篩選歷史名稱並保留資料列順序與非 ready 資料夾。NAS 記憶體快照四個帳號共 2,972 筆逐筆比對一致，中位讀取及 JSON 處理由 144 ms 降至 33 ms。13:53 HKT 零長度回應後，四條貼文串流均在 363 秒內有成功紀錄；故障後第 23 秒樣本有一條貼文串流失敗，第 83 秒樣本四條失敗計數已全部歸零。
- 正式 NAS 診斷映像在 13:40 HKT 啟動，13:56 已捕捉首筆自然貼文失敗：HTTP 200、application/json、宣告長度 0、Chromium 實讀 0 bytes、provider 收到 0 字元。空本文在瀏覽器可見的 HTTP 回應層已存在；目前無法識別是哪個上游節點產生。當次核對四條貼文均已成功輪詢過，容器 healthy、RestartCount=0。
- 貼文 HTTP 空回應診斷：只在 /api/post/item_list/ 讀取失敗或最終空回應時附加隨機識別碼、狀態、白名單 MIME、宣告與 Chromium 實讀長度、provider 字元數或讀取錯誤類型。缺少長度保留 null，正文及 URL 不加入診斷。正式基底 8281505aa598 的獨立診斷映像 404e0f0c833a 已通過斷網真 Chromium 空本文／JSON／截斷傳輸實測。
- 過夜日誌交叉核對：57 次空回應全部來自貼文，四個目標分別佔 12、13、16、16 次；最長異常亦涉及全部四個目標。兩筆 ERR_INSUFFICIENT_RESOURCES 相隔約兩秒，對應同一次後續瀏覽器失聯；31 次失聯中僅一次在前五分鐘有此錯誤。
- NAS catalog 映像 8281505aa598 在 13 小時 45 分鐘內有四段 unhealthy，均自行恢復。最長一段為 04:18–04:48 HKT，該段連同前兩分鐘的 15 次輪詢失敗全為 post HTTP 200 空白回應，樣本中貼文距上次成功最長 36 分 31 秒。其餘時段涉及導航或請求逾時、瀏覽器失聯及 JSON 解碼失敗。兩次 Chromium ERR_INSUFFICIENT_RESOURCES 的具體資源仍未確定。

## 2026-11-18

- 修正 TikTok catalog 的 SQLite 鎖競爭。正式 NAS 曾因慢讀交易使兩次 commit 失敗而退出。BUSY／LOCKED 現在 rollback 後可取消退避；頁面提交失敗保留原 cursor，手動工作、修復及重新整理保留重試預算。受控停止不會消耗業務重試，取消的 future 不會令清理再次失敗。
- 清除 browser worker 結束後仍持有 IPC pipe 的子程序；reader 與 login 共用 profile 排他鎖。heartbeat 寫入失敗會安全停止並回報非零狀態，診斷保留例外分類與位置。storageBlocked 納入健康檢查與去識別化觀測。
- Chromium HTTP cache 曾在 256 MiB 的 /tmp 內佔用約 221 MB。普通 transport 改用既有的兩個 32 MiB profile cache 掛載；獨立執行保留暫存快取。catalog 停止預算從 45 秒改為 2 分鐘，以容納既有 60 秒 ffprobe 等待與瀏覽器清理。
- 增加唯讀 Compose／CPU quota preflight、阻止 catalog 使用不相容的 --no-deps。排除約 19.9 GiB 的 NAS 匯入副本，實測既有 legacy builder 重用 apt、pip 及 Playwright 快取。
- 本機 Python 共 201 項（198 通過、3 跳過），Node 398 項通過。原容器 exited(0) 的停止來源仍未知。歷次故障注入、部署、資料核對與剩餘限制見 docs/tiktok-catalog-reliability.md。

## 2026-11-17

- 更新 todo.md：保留 viewer／追蹤關係監控需求，新增 TikTok／X 安全錯誤診斷、Docker 歷史事件、跨平台進度與資源觀測、Telegram 400 及 tunnel 待查項目，整理已完成調查與舊 bridge 停用結果；依使用者要求將原被忽略的 todo.md 納入版本控制。

- 14:56–14:57 HKT 即時唯讀健康核查：TikTok 最近一小時 10 筆查詢失敗、部分串流重複，當下 16 串流連敗皆為 0、pending=0；X 待辦 256→248、保存 8695→8703，查詢 failures=0；IG activeIssues=0 且有近期成功查詢，Telegram pollOk/telegramOk/deliveryReady=true、pending=0。現存核心容器 RestartCount 均為 0；X／Telegram 近期建立時間對應既有 ETA 修正部署，未見反覆崩潰證據。未改動服務。

- 修正 X 封存 ETA 隨查看時間漂移：完成時間以最新進度時間計算，沒有新進度時保持固定；預測時間已過或超過五分鐘未更新時顯示無法估算。新增固定／更新／陳舊進度及預測過期回歸測試，先確認兩項測試失敗再修正；398 項 Node 測試通過，程式審查通過。仍使用整段任務平均篇數耗時，不代表下載加速。 已同步 NAS（基底 bb7e581 加未提交修正），來源 SHA-256 a167af6e007c；Compose 驗證通過，僅重啟 ig-telegram／x-watch，X 恢復 running、pending 1197→1186，兩端既有修改保留。

- X 下載／完成時間唯讀診斷：NAS `bb7e581` 的 x-watch healthy，mikuru_hositani 封存進度 7694→7719／8951，待辦無重試紀錄、failed=0，共享並行上限 3。確認 ETA 使用自封存開始的平均篇數耗時，且以每次查看的 now 加上剩餘時間；固定進度重播時，60 秒後顯示完成時間亦延後 60 秒。按 manifest mtime 統計，截至約 14:02 HKT，最近／前一個半小時為 455／749 篇、550／928 件媒體、435／870 MB；這是保存產物統計，非網路頻寬量測。較早／較新各 50 篇媒體抽樣分別約 12／62 MB，篇數不等於下載工作量；尚不能歸因 CDN 限速或 NAS 磁碟。未修改程式或重啟服務。

- 依使用者要求停止 NAS 舊 x-archive-bridge，將容器 restart policy 由 unless-stopped 改為 no；13:49:17 HKT 已確認 exited、running=false、restart=no。保留容器及既有資料，未改動其他服務；日後以舊 Compose 重建仍可能套回原重啟設定。

- 完成全 NAS 41 個容器唯讀錯誤調查：19 個運行中僅舊 x-archive-bridge unhealthy，確認主機狀態目錄消失、容器仍持有 deleted lock，SQLite 無法開啟後 worker 結束但 HTTP 存活；另區分 TikTok browser、Telegram 400、IG 已解除錯誤、tunnel／停止訊號。使用者確認剩餘 TikTok repost 為來源端不可存取。未修復或重啟服務，詳見 docs/nas-container-errors-research-20261117.md。

- 完成 NAS TikTok catalog 唯讀穩定性調查：合併 2259 個跨平台每分鐘樣本，辨識 74 段應用健康異常及 74 次觀測恢復（非精確 Docker 紅燈次數），附完整時間表及比較。既有備份 13/16 串流為 browser transport 連敗；核實實際資源上限與範本不同、Docker 歷史事件僅餘 256 筆，未修改或重啟服務。詳見 docs/tiktok-stability-research-20261117.md。

## 2026-11-16

- 提交既有 NAS I/O 調整：Chromium 暫存快取改用有上限 tmpfs，TikTok VPN Docker 健康檢查改為 30 秒，新增校正後的唯讀 I/O 量測工具及對照紀錄；4 項量測工具測試與 Python 審查通過。全部剩餘修改提交前，396 項 Node、10 項 TikTok worker 測試通過，npm audit 0 漏洞；NAS 程式與設定雜湊一致、Compose config 通過。

- NAS 下載加速後短測：182.7 秒保存 124 件／33900974 bytes，對照修改前 20 分鐘 18 件／4707163 bytes；共享並行維持 3。IG／Telegram／X／TikTok catalog 皆 healthy，Telegram pending=0、X pending=[0,0,0]、TikTok pending=0／unresolved=1。樣本長度與負載不同，不宣稱固定加速倍數；詳見 docs/media-download-before-after.md。

- 下載加速修正已提交並部署 NAS `9e2904d`（RED `b10dbf8`）：本機 396 項 Node 測試、NAS 隔離無網路容器 52 項相關測試全通過；npm audit 0 漏洞，兩輪程式審查通過。NAS Git 快進同步，既有修改保留，Compose config 通過，僅重啟 ig-telegram／ig-watch；X／TikTok 透過共享背壓摘要取得修正。部署前 20 分鐘保存 18 件／4707163 bytes，30 秒磁碟寫入約 3155 KiB/s、write await 約 25.6 ms；部署後實測另記比較文件。

- 修復下載吞吐：背壓不再反覆使用舊 startup／idle checkpoint，保留持續 event-loop 壓力保護；IG 封存派工不等待逐件 1000 ms 保存計時器，批次結束仍等待耐久 checkpoint；待辦每約 5 秒再處理，維持原有 Instagram 查詢頻率。媒體與 caption 失敗保存 60 秒重試期限，保留 TikTok 持續下載機制及共享背壓。

- 完成媒體下載部署前後比較，詳見 docs/media-download-before-after.md：核對 NAS 部署前來源備份及 observer。TikTok 部署前約一小時 pending 固定 653，部署後約一小時 624→294，12:19:50 首次為 0；更正不能依並行 3→1 推論所有平台實際變慢。IG／X 缺少部署前下載計數，僅能確認機制差異，不能量化降速比例。

- 跨平台下載診斷：X 與 TikTok 內容封存同樣讀取共享背壓，當下並行上限為 1；X 工作迴圈預設 5 秒，TikTok 使用可持續補入工作的 coordinator，沒有 IG 同樣約五分鐘才再跑封存的排程。兩者未使用 IG catalog 的 ArchiveProgress 每件等待；NAS X 三個帳號 pending=0，TikTok pending=0、unresolved=1。IG 手動下載與 TikTok LIVE 錄影未接入此背壓；未量測其實際吞吐，不能推論完全不受共享 NAS 資源影響。

- 補查 Git 部署紀錄：41a1b44 的 docs/nas-performance-baseline.md 記載 5cbc047 已於 2026-11-16 10:24–10:28 HKT 上線。該提交把 IG 固定並行 3 改為背壓控制 1–3，並加入 ArchiveProgress 預設 1000 ms 的合併等待；catalog 每件 await 完成才繼續，並行 1 時無法有效合併。這是程式層級的減速因素，首次實際觸發仍無歷史切換紀錄。

- Instagram 慢速時間線：15 秒封存批次於 2026-11-14 23:41 香港時間的 ba4ac1f 加入（當時並行 3）；可降至並行 1 的預設背壓於 2026-11-16 10:08 的 5cbc047 加入。NAS 現存容器日誌從 11-16 18:13 起，18:15–18:20 已呈現約 5 分鐘完成 5 件；無法由現存資料確定首次降速或降至並行 1 的精確時間。

- Instagram 下載診斷：NAS 背壓狀態為 downloadConcurrency=1；歷史封存每輪下載預算 15 秒，輪詢約 5 分鐘。UTC 13:31–13:57 待辦由 1978 降至 1960（約 41 件／小時），最近圖片從開始至保存約 2.8–4.3 秒，包含網路、磁碟同步與狀態保存，尚未拆分耗時。確認為低背景處理吞吐；未更改執行設定。

- TikTok LIVE 影片改為 `🎥 TikTok LIVE recording` 加檔名，新增錄影採參考專案 `TK_帳號_YYYY.MM.DD_HH-mm-ss.mp4`（日本時間）命名；不再額外傳送錄影完成文字。
- 錄影開始通知以每段錄影保存 Telegram message ID；錄影停止且轉檔工作保存後自動刪除（轉檔失敗亦清理），支援重啟重試及先收到清理事件，避免誤刪下一段通知。
- LIVE 影片傳送實際顯示尺寸、長度與等比例 JPEG 縮圖／封面；保留原影片。
- 恢復收到串流資料時清除中斷警告，涵蓋同一段錄影重新連線。
- NAS 確認 maidcafe_ikiss 香港時間 18:31:01 開始的錄影長 581.932 秒（約 18:40:43 結束），18:43:47 同 room ID 再次錄影；原影片 640×1280。歷史事件送達後刪除，無法由現存資料還原當時全部通知文字或判斷中斷原因。
- 驗證：391 項 Node 測試、15 項 TikTok 傳送測試及 10 項 Python worker 測試。
- NAS 已部署至基底 `c3ddf2b` 加本次未提交修正；容器內程式雜湊與本機一致，`ig-telegram`／`tiktok-watch` 均 healthy，Compose config 通過、啟動日誌無錯誤。實際 18:31 錄影的容器內 probe 回傳 640×1280、582 秒，等比例 JPEG 產生成功（7127 bytes）；尚未目視驗證下一段新錄影在 Telegram 的實際顯示。
