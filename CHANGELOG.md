# Changelog

## 2026-11-21

### Telegram 媒體通知

- 統一 Instagram Story、Instagram Post、X 貼文／回覆／轉發／引用及 TikTok 貼文／轉發的通知開頭。依序顯示帳號、方括號類型與可用的媒體 ID、JST 發佈時間，再接內容。轉發時間缺失時顯示「發佈時間未知」，並在內容區保留原作者與原文時間。

### Telegram 封存匯出

- 在同一則訊息顯示估算、確認、排隊與打包進度，以及完成後的下載連結。估算期間隱藏按鈕，打包期間按實際處理速度更新預計剩餘時間。

### 文件

- 將 NAS 容器故障與健康狀態告警方案記錄在 `todo.md`，包含監控範圍、告警緩衝、恢復通知與驗證案例。

- 盤點 Compose 服務的健康檢查。常駐服務中，`telegram-bot-api`、`tiktok-browser-resolver` 和選用的 `archive-tunnel` 未在 Compose 明訂探測。`tiktok-login` 是按需啟用的登入工具，不需常駐。現有 Docker 健康狀態與跨服務告警是兩項不同的能力。

- 核對 `ig-watchdog` 的職責。它檢查 Instagram 主監控與 Telegram 控制服務的心跳，轉送已排入佇列的警報，並在 Telegram 控制服務失聯時直接發送備援通知。Instagram worker 卡住時由主監控觸發容器重啟。

- 核對 NAS 上 `@nao_kizuki_` 的例行檢查。23:03 HKT 成功取得精選清單，23:08 完成精選內容與貼文檢查。當時貼文沒有下一頁、待查精選與待下載媒體均為 0，沒有查詢失敗。「例行檢查新內容」會在取得精選清單後、完成精選內容檢查前顯示。

- 釐清 Telegram 監控狀態。Instagram 初次貼文與精選搜尋完成後，例行掃描若仍有下一頁貼文或待查精選，且沒有待下載媒體，會顯示「首次搜尋已完成，例行檢查新內容」。例行掃描清單清空後，會顯示「已完成，持續監控新內容」。

- 評估 Redis 的效能用途。封存匯出預覽每次都重新收集檔案清單，適合先量測 NAS 掃描耗時和同帳號的重複預覽頻率。若快取命中有實際效益，優先試用短效程序內快取；有多程序共用需求時再評估 Redis。此次只做程式碼評估，未取得 NAS 效能數據。

- 在 README 新增 Mermaid 架構圖與資料流說明，呈現 Telegram 指令、平台擷取、本機封存與通知配送的關係。

### NAS 正式部署

- 將正式服務切回 NAS 的 `8d37f68`，停止本機監控、Bot、封存及除錯容器。保留 NAS 設定、資料卷與部署前的檔案備份。
- NAS 原有 Instagram 登入失效。備份原有 profile 並遷移本機已驗證的 profile 後，NAS 已成功查詢限時動態、貼文、精選清單和精選內容。
- NAS 的東京 VPN 出口可取得 TikTok 限時動態和個人資料，但四個帳號的貼文與轉發均回傳空本文。已備份 VPN 設定與 Catalog SQLite，將出口切換到首爾，並提早重試八條受影響的串流，保留既有游標與封存進度。四個帳號均已在首爾出口成功查詢貼文與轉發，Catalog 不再有連續失敗。

### 本機 Instagram 診斷

- 偵測到 Instagram HTTP 400 `checkpoint_required` 時，第一次出現就排入 Telegram 告警，並持久化暫停共用登入的查詢。完成手動驗證後可解除暫停。

- 使用者完成 Instagram 自拍驗證後，已關閉並移除本機暫用 noVNC 容器。確認該容器已退出後，移開其遺留的 Chromium profile 鎖並重啟監控。20:39 HKT 實測 `@t_comjp` 的限時動態、貼文和精選查詢均成功，`ig-watch` 與 `ig-watchdog` 均為 `healthy`。

- 在本機 noVNC 開啟 Instagram 後，畫面導向 `/accounts/suspended/`，顯示需要上傳自拍以驗證帳號身分。

- 20:03 HKT，`@t_comjp` 的限時動態查詢收到 Instagram HTTP 400 `checkpoint_required`，回應只有 `message` 和 `status`，無法確認驗證類型。同輪精選查詢遇到登入初始化頁面重新導向。Docker 仍回報 `healthy`，兩項首次失敗仍待重試。較早四次監控重啟均由 worker 進度逾時觸發，時間與 Mac 睡眠期間的喚醒重合。診斷期間未重啟服務或更動登入資料。

### TikTok Catalog 穩定性修正

- 減少 Chromium 對貼文清單的重複請求。已攔截 TikTok 頁面順帶發出的清單請求，每次排程只放行 Catalog 主動發出的查詢。貼文使用獨立的匿名瀏覽器工作階段，其他內容可繼續使用原有登入工作階段，切換時無須重啟 Chromium。
- 將 HTTP 200、本文 0 bytes 記為 `TIKTOK_EMPTY_RESPONSE`，區分有效的空清單、個人頁 HTTP 403 和解析失敗。空本文時保留貼文游標與上次成功時間，交由排程從約一分鐘開始退避重試，取得有效清單後恢復原速。另修正 Chromium 關閉及重建時的 profile 鎖清理，只清理確認屬於已退出程序的鎖。
- 用相同映像與匿名設定同步對照兩個 VPN 出口，其中一個回 0 bytes，首爾出口回傳 20 筆貼文。固定首爾出口與五個帳號的短期降速對照仍不足以判定頻率的影響。本機已恢復每帳號約五分鐘一次的貼文輪詢，NAS 正式服務維持停止。
- 恢復原速後，截至 18:11 HKT，五個帳號共成功輪詢貼文 97 次。兩次空本文分別在約 57 秒與 55 秒後自動恢復，期間沒有換出口。隔離 Chromium 測試另重現四次連續空本文，重啟 Chromium 與重開 SQLite 後仍保留進度，有效回應恢復後成功封存測試貼文，沒有重複排入通知。
- 這段觀測支持本機 Catalog 在目前設定下基本穩定，長期運行期間的新貼文封存與通知仍待實際發布驗證。`@ilife__wakaba` 的 LIVE 查房仍未取得房間 ID。

- 最終檢查截至 20:08 HKT。本機原速連續運行約 3 小時 33 分鐘，五個帳號各成功輪詢貼文 42 次，合計 210 次。四次 HTTP 200 空本文均在同一 VPN 出口於 55–66 秒內自動恢復；一次個人頁解析錯誤及一次限流訊號亦各於下一次排程恢復。Catalog 與 VPN 皆健康、重啟 0 次，20 條 Catalog 串流的連續失敗計數均為 0。

- 截至 18:05:54 HKT，原速監控超過 90 分鐘，五帳號各完成 18 次成功貼文輪詢，合計 90 次；兩次空本文均在約一分鐘內恢復。另核對 23 分鐘內的 47 份全串流心跳，每帳號成功更新貼文與轉發各 4–5 次、限時動態 11 次及個人資料 1 次，期間未觀察到連續失敗或需手動處理的狀態。

- 使用本機運行映像在無外網容器內實測 Chromium、瀏覽器子程序與 Catalog。測試伺服器回傳四次 HTTP 200、0 bytes，第二次失敗後重啟瀏覽器子程序並重開 SQLite。共收到七次貼文查詢，四次退避期間未提前重送。有效清單恢復後成功封存測試貼文，下一輪未重複排入通知。來源回應及媒體下載均使用測試資料。

- 以暫存 SQLite 模擬四次連續貼文空本文。原速設定下依序退避 60、120、240、480 秒，第二次失敗後重開 SQLite 仍保留失敗次數、游標與既有資料。模擬有效回應後成功封存新貼文，下一輪資料相同時未產生重複通知；測試只寫入本機暫存通知佇列。

- 比對兩次貼文空本文與同期的成功時間。@maidcafe_ikiss 在 @mikurun33 失敗後約 0.8 秒、在 @ilife__wakaba 失敗後約 23 秒均成功輪詢，兩次都早於原失敗帳號的重試。觀測到同一出口仍能正常回應其他帳號，未見整批貼文串流同時停擺。

- @ilife__wakaba 在空本文重試恢復後，17:41:46 HKT 的下一輪正常貼文輪詢也成功。17:42 的 Catalog 心跳顯示五帳號的貼文、轉發、限時動態及個人資料共 20 條串流均無連續失敗。新增每 30 秒記錄全串流心跳的本機觀測。

- 將同一首爾出口的五帳號降速與原速各取最初 14 分 56 秒比對，分別觀測到 5 次和 14 次貼文成功，兩段均無空本文。新增維持相同訂閱名單並避開歷史補抓的頻率對照步驟。

- 恢復原速後截至 17:38:54 HKT，五帳號累計 63 次成功貼文輪詢及兩次 HTTP 200、0 bytes。第二次發生於 @ilife__wakaba，17:35:51 失敗，17:36:46 重試成功（55 秒）。兩次皆在同一 VPN 出口恢復，當下各帳號無待重試的貼文錯誤。

- 恢復原速後，@mikurun33 於 17:16:13 HKT 首次收到 HTTP 200、0 bytes，保留前次成功紀錄並排程重試；17:17:10 成功恢復，約 57 秒。VPN 無重連或出口變更。

- 同一 LIVE worker、同一 VPN 的未開播對照：@akachanm 取得房間 ID，後續狀態查詢明確回未開播；@ilife__wakaba 仍在帳號查房時未取得房間 ID。後者的直播狀態保持未確認。

- 核對上游 Michele0303/tiktok-live-recorder。`main`／`develop` 的帳號查房從 TikRec 取得簽署後，仍向 TikTok 房間 API 讀取 `roomId`；本機已實測該流程回 `19881007`。上游未合併的 PR #464 提議以需要獨立授權的 Euler Stream 查房作備援，PR #482 處理非 JSON 回應。上游 issue #469 另記錄已知房間 ID 可用於手動錄影。未發現上游對該錯誤碼的明確定義或可直接驗證的自動查房修正。

- 依使用者指示，16:35 HKT 恢復本機 Catalog 原有貼文輪詢頻率（全帳號間隔設回 `0`），保留五帳號及首爾出口 `84.233.167.72`。先前降速只有短期樣本，未用來判定空本文根因。

- 修正 LIVE 手動分享連結備援：依帳號查不到房間時，可使用連結攜帶的唯一數字房間 ID，但必須向 TikTok 核實房主及開播狀態才錄影。補上房主相符及不符的測試。16:41 HKT 已套用本機 LIVE worker；本機和 NAS AMD64 候選映像 `af24dba42ac8` 各通過 13 項離線測試。NAS 正式服務仍停。同出口實測 @ilife__wakaba 的原生 LIVE API 各種正常請求形式仍回 `user_not_found`，Chromium 的直播頁房間請求曾回 403；Catalog 的公開個人頁有同名帳號，但未提供房間 ID。

- 16:20:31 HKT 本機啟動貼文降速對照（全帳號共用 120 秒間隔）。保留五個訂閱、Chromium profile、首爾出口 `84.233.167.72`，比對確認 VPN／LIVE／Telegram 容器沒有重建。切換前五帳號觀測到 23 次成功及 2 次空本文，含新帳號的歷史補抓。切換後首輪 Chromium 實測五帳號均 HTTP 200，各 8–20 筆，網路請求相隔 126.49–145.04 秒。125 項本機離線測試通過。NAS 已同步程式並驗證 AMD64 候選映像 `a8c50597c196`，五項重點測試通過，NAS 服務維持停止、預設間隔為 0。

- 為同出口及同訂閱數的貼文降速對照新增選用的全帳號間隔。啟用時，前一筆排程貼文查詢完成後才開始計算間隔；等待期間仍可排程其他串流，並限制貼文解析的即時重送。

- 本機 @ilife__wakaba 的 LIVE 異常定位於房間查詢。原生及備援請求均曾收到 HTTP 200、平台代碼 `19881007`／`user_not_found`，未取得房間 ID；既有 Chromium resolver 健康，但實測該直播頁未觀察到進房請求或串流，因此回 502。Catalog 已取得同名的帳號資料，LIVE 其餘四帳號仍在監看。現有資訊無法確認該帳號當時是否開播。

- 16:10:54 HKT，@ilife__wakaba 在歷史下載佇列清空後，貼文 API 又回 HTTP 200、實讀 0 bytes。與 16:05 @akachanm 的失敗皆發生在出口 `84.233.167.72`。貼文空本文與 LIVE 房間查詢是不同的故障，後續分開觀測。

- 16:09 HKT 核對 @ilife__wakaba 歷史補抓完成：68 則貼文、130 則轉發、1 筆個人資料，224 個檔案均已存在且非空，合計約 2.09 GiB。各串流已完成基線、回到首頁游標，無待下載及待通知項目；原本四帳號同期持續更新。

- 15:59 HKT 新增第五個訂閱 @ilife__wakaba 並觸發歷史補抓。在首爾出口 `84.233.167.72` 下，既有四帳號在喚醒後前兩小時合計 97 次成功貼文輪詢，無空本文。補抓期間確認新帳號 68 則舊貼文已封存，另抽驗三個正式封存影片可讀。16:05:27 @akachanm 的貼文 API 首次在新出口回 0 bytes，16:06:29 排程重試恢復；期間無 VPN 變更。帳號數及歷史補抓同時變動，單次空本文不足以判定原因。

- 以闔蓋為界分段核對：休眠前首爾出口 `61.97.243.106` 共 434 次成功貼文輪詢、1 次空本文及 3 次個人頁解析失敗。喚醒後首爾出口 `84.233.167.72` 首小時 49 次成功、無貼文失敗；同一分鐘內曾觀測到四帳號各成功一次。兩段均沿用約五分鐘的個別帳號輪詢間隔。

- Mac 於 10:56 HKT 闔蓋休眠，14:01 完整喚醒。期間採樣不連續，Catalog 曾短暫標為 unhealthy；喚醒後四條貼文串流於 14:02 恢復，Catalog 與 VPN 容器均未重啟。OpenVPN 在休眠期間重新連線，14:02 核實首爾出口已從 `61.97.243.106` 換為 `84.233.167.72`。被動擷取下一輪四筆貼文 API 皆為 HTTP 200，實讀 176,387–524,419 bytes、各有 8–20 筆貼文。已安排貼文觀測接續至 11 月 22 日 14:02，分別核對兩段出口。

- 本機新增唯讀容器日誌觀測，精確記錄貼文空本文與解析失敗。10:20 HKT 個人頁解析失敗後，同一帳號的下一次貼文輪詢恢復；截至 10:26 累計 411 次成功貼文輪詢、一筆空本文與三筆個人頁解析失敗。

- 約 8 小時 21 分鐘後首度再遇貼文清單空本文。@maidcafe_ikiss 於 10:07:37 HKT 的 HTTP 200 宣告及實讀皆為 0 bytes，Catalog 保留上次成功時間並記為失敗。10:08 的排程重試回傳 429,122 bytes、20 筆貼文。另以同一 Chromium 被動觀察，四個帳號頁面自身的貼文清單請求遭本機規則攔截，noVNC 可顯示 `Something went wrong`，而 Catalog 的獨立清單請求仍可成功。

- 修正 X 封存 ETA 的 CI 測試，接受日期與時間之間的一般空格及細空格，並保留對香港時間數值的驗證。

- 本機 Catalog 與 Telegram 容器讀到相同的訂閱設定，四個帳號的貼文、限時動態、轉發與個人資料通知皆已啟用。兩個容器的健康檢查均通過。

- 08:48 HKT 再遇一次個人頁嵌入 JSON 解析失敗（@nao_kizuki 的貼文輪詢），未進入貼文清單請求。08:48:45 的排程重試已成功，失敗計數歸零。Chrome profile 主程序於 08:49:02 啟動，時間晚於此錯誤，無法由這筆紀錄判定由定期重開造成。

- 06:19–08:21 HKT 的 123 筆全串流快照顯示，四帳號的貼文、限時動態、轉發和個人資料皆持續更新，未取樣到串流失敗、心跳停滯或儲存阻塞。自新版部署起累計 312 次成功貼文輪詢，沒有空本文樣本。

- 重新核對本機 Catalog 與現行 VPN 容器共用網路，Gluetun 保存的出口仍為 `61.97.243.106`。同步出口對照的紀錄補上實際設定的 OpenVPN 主機與出口 IP，避免只靠 IP 地理標籤辨識。

- 六小時本機觀測：首爾出口下四帳號合計 286 次成功貼文輪詢，當時容器日誌沒有空本文或網路失敗。Catalog／VPN 均健康、重啟數為 0，尚無自然發布的封存樣本。

- 降速對照基線：同一首爾出口、四帳號、251 次成功貼文輪詢。各帳號成功間隔中位數約 300 秒，整體約 48 次成功輪詢／小時，任一 60 秒內最多 3 次。統計取自成功輪詢時間戳；瀏覽器 HTTP 請求總量須從網路紀錄另行核對。

- 本機 Catalog 正式資料庫的唯讀記憶體快照通過 SQLite `quick_check`。資料庫保留 744 筆已封存貼文，當時無待下載或待通知項目。

- 以部署映像、真 Chromium 和隔離的 loopback HTTP 樣本驗證貼文空本文復原。首個 HTTP 200 回 0 bytes，診斷經瀏覽器子程序傳到 Catalog，保留原游標並退避 60 秒。退避期間沒有第二次請求，下一輪取得有效空清單後清除失敗並恢復五分鐘排程，未產生通知。

- 在隔離暫存目錄驗證 Catalog 到 Telegram 的交付格式。實際部署映像產生的新貼文事件和影片檔由本機 Telegram 容器同版的交付模組處理，模擬兩位訂閱者各收到一次影片，重新載入同一事件後零重送。未使用正式資料或連線發送訊息。

- 本機觀測追加唯讀 Catalog 健康檔取樣與 Docker 生命週期事件，涵蓋四帳號的 16 條串流、心跳新鮮度、儲存阻塞與人工介入旗標。健康檔取樣自約 06:20 HKT 開始，原有貼文觀測繼續覆蓋部署後的完整視窗。

- 核對本機貼文測試輪詢開關為 `0`。可靠性指南補充其同時影響個別帳號排程與重試，後續若須驗證降速，應單獨調整全體貼文清單請求的間隔。

- 四小時線上觀測：截至 05:48 HKT，首爾出口下四個帳號共記錄 191 次成功貼文輪詢，未觀察到貼文 API 空本文。個人頁曾有一次 JSON 解析失敗並自行恢復，其後四個帳號的失敗計數均為 0，Catalog 容器重啟數為 0。

- NAS 已準備 AMD64 候選映像 `verified-local-20261121`（`d70db0a05ea7`）。磁碟環境下舊批次測試在 15 秒內只完成 24/50 項，改用 Catalog 原有 tmpfs 模式後，NAS 122 項離線測試及兩組真 Chromium 測試全部通過。NAS 正式服務仍停，`latest` 維持 `870cbc038a53`。

- 在本機 Git 忽略的 `data/catalog-local/compose.yml` 保存 noVNC、空 cookies 與既有 Chromium profile 的重建設定。Compose 等價檢查確認僅兩個 bind 來源從暫存目錄移到本機資料目錄；24 小時觀測期間未切換正在運行的容器。

- 三小時線上觀測：同一首爾出口下新版共 143 次成功貼文輪詢，無貼文 API 空本文，帳號的最長成功間隔 370 秒。Catalog 與 VPN 健康、重啟數為 0，暫無新貼文封存樣本。

- 修正本機穩定性觀測的計時基準。初始觀測比 01:46:47 版部署早約 62 分鐘啟動，已安排唯讀程序在原觀測結束後接續，目標覆蓋部署後完整 24 小時。

- 在 Catalog 可靠性指南補上已實測的空本文診斷、隔離出口對照、VPN 切換與同一 Chromium profile 恢復流程，以及只在持續復發時才採用的限速對照。

- 新版兩小時驗證：約 95 次成功貼文查詢，無貼文清單 HTTP 200 空本文。@maidcafe_ikiss 03:47:00 有一次個人頁嵌入 JSON 解析失敗，未進入貼文 API，03:47:48 依舊有排程自行恢復。線上仍未見新發布封存樣本。

- 首爾出口下以暫存資料庫驗證一筆已發布公開影片的完整 Catalog 封存。前兩個 CDN 候選回 403，現有備援經 302 後下載成功。ffprobe 確認約 19.4 MB HEVC、88.43 秒，第二次封存重用同一檔案且無新 HTTP 請求。未改正式庫或發送 Telegram。

- 首小時驗證：新版於首爾出口運行約 62 分鐘，共 49 次成功貼文查詢、無新貼文空回應；各帳號最長成功間隔 324–347 秒。另有一次 Story 解析錯誤及一次轉發回應被拒；本段沒有新貼文入庫。

- 02:35 HKT 首爾出口下新版已觀測 40 次成功貼文查詢，約 49 分鐘內貼文無空回應。期間另有一筆 Story 解析失敗，不計入貼文空回應；觀測仍在進行。

- 以本機實際部署映像在無網路 Linux 容器完成 123 項 Catalog 測試，全部通過。真 Chromium 的 profile 重啟、匿名／登入隔離，以及空本文／正常 JSON／截斷傳輸的三組離線驗證均通過；Node 全套 406 項通過。

- 02:23 HKT 本機完整串流比對：四個帳號的貼文、Story、轉發和個人資料共 16 條串流，皆在 01:46 部署後成功更新，當時所有失敗計數為 0，游標均回首頁。本段沒有新的待封存資料和通知 outbox。

- 02:13 HKT 首爾出口下，01:46 上線版本已觀測到 23 次成功貼文輪詢，四帳號連續失敗為 0。該窗沒有新貼文封存紀錄，暫不能以真實新發布驗證下載與送達。

- 01:46 HKT 新版部署後四帳號各完成兩輪貼文查詢，部署後日誌未見失敗。較早 01:36 的唯讀快照曾記錄 @nao_kizuki 一次暫時空回應，隨排程自行恢復；首爾期間尚非零錯誤，未啟動降速對照。

- 01:46 HKT Chromium 關閉修正版上線後，四個帳號首輪均成功更新 lastSuccess，沒有空回應；沿用首爾 VPN，不執行降速或減少帳號的實驗。

- 首爾出口恢復後觀測到至少 21 次成功貼文輪詢。01:46 HKT 本機套用 Chromium 正常關閉修正，同一 VPN／profile，四帳號暫無失敗，noVNC 握手成功。若空回應復發，優先固定出口及帳號數，比對全體貼文請求限速，再考慮縮減帳號。

- Catalog 關閉時先讓 browser worker 正常關閉 Chromium，再回收殘留程序群組；只在子程序退出、profile lease 仍持有且原鎖身分吻合時清理自己建立的 Singleton 連結。123 項測試中 120 通過、3 跳過，離線真 Chromium 強制退出後使用不同 hostname 重啟同一 profile 成功。

- 首爾出口已就緒後重新使用原 profile。修復舊 SingletonLock 後四個帳號皆完成貼文重試並清零，保留原 SQLite、cookies 匯入策略及 noVNC；這輪首次恢復無需建立新 profile，仍待多輪觀測。

- 同版 Chromium、全新匿名 profile、同帳號同期出口對照：設定 `al-tia.prod.surfshark.com` 的出口 `172.216.14.22` 回 HTTP 200、0 bytes，設定 `kr-seo.prod.surfshark.com` 的出口 `61.97.243.106` 回傳 20 筆貼文。正式本機切到首爾後 Chromium 被舊 VPN hostname 的 SingletonLock 擋住；確認 volume 無使用者並持有離線 lease 後備份三個殘留連結，同一 profile 正常重開。

- 01:06 HKT 本機部署貼文清單預載去重，保留同一 VPN 與 profile。首筆輪詢 @mikurun33 在 01:11:21 仍回 HTTP 200、實讀 0 bytes；同段 HAR 顯示 31 個貼文請求在本機被攔截、只有一次貼文 GET 取得 HTTP 回應。嵌入頁觀測移到同 VPN 的獨立唯讀容器。

- Catalog 在所有頁面導覽中攔截貼文清單預載；專門輪詢每次只放行自己的明確 GET。Chromium 隔離測試確認上游只收到一次 GET、正常 Cookie 仍存在、內部識別標記已移除。121 項測試中 118 通過、3 跳過。

- 嵌入頁單篇交叉驗證：@mikurun33 的 13 條影片均已在 Catalog 封存或首頁基線；@nao_kizuki 的 13 條有 10 條在首頁基線，另核實一條未收錄影片的作者與 ID 相符，但發布日期為 2025-05-23。確認嵌入頁能在貼文清單受阻時取得個別影片，也確認首次出現的連結不能直接視為新發布。

- 啟動同一 VPN 的公開嵌入頁唯讀對照，每 20 分鐘比對四個帳號，記錄影片／相片連結數、新出現連結及 Catalog 後續收錄時間，不修改正式資料或通知。首次四個帳號均取得影片連結；測試仍未確認更新時效或相片覆蓋。

- 00:51 HKT 只更新本機 Catalog 映像，沿用 VPN 和 profile，取消貼文空回應立即重送；部署後首輪四帳號仍收到零位元組。唯讀探測同一 VPN 的公開嵌入頁：四帳號皆 HTTP 200、可辨識 8–13 條影片連結，但未找到相片連結，且與已封存最新 10 筆的重疊為 0–8。未設為正式替代來源。

- 貼文定期輪詢收到空本文後直接使用既有持久化退避，取消同一輪 1–3 秒內第二次查詢。保留其他查詢與手動單篇原有有限重試、貼文成功間隔和游標。Catalog 測試 121 項，118 通過、3 跳過。

- @mikurun33 在 00:42:29 成功後，00:48:03 下一輪正常貼文查詢又回傳 HTTP 200、實讀 0 bytes。同一出口曾恢復單次查詢，但 10 分鐘安靜期與背景請求攔截未能維持穩定。

- 同一薩格勒布 VPN 容器下，修正版安靜期擷取到 44 筆在 Chromium 被攔截的貼文請求，沒有貼文端點 HTTP 回應，31 筆帳號頁成功。錯峰後三帳號仍回空，@mikurun33 於 00:42:29 成功提交，同輪 HAR 實讀 483,312 bytes。開始延長唯讀觀測以驗證持續性。

- 第一輪固定出口的四個排定重試全部仍回空。00:28 HKT 本機套用貼文背景請求攔截修正版，沿用同一 VPN 容器、出口和 profile，重啟 Catalog Chromium，noVNC 可連線。重新排定 10 分鐘安靜期及四帳號 75 秒錯峰對照。120 項 Catalog 測試共 117 通過、3 跳過，另以隔離 Chromium 實測攔截和放行行為。NAS 已同步來源，容器維持停機。

- Catalog 的 Chromium 在 Story、轉發、個人資料與單篇查詢期間攔截頁面順帶發出的貼文清單請求。專門貼文輪詢保留既有流程。新增請求路由及匿名／登入切換回歸測試。

- 固定出口錯峰對照發現：即使貼文排程尚未恢復，Chromium 已記錄 31 筆貼文清單請求。其他內容查詢導覽帳號頁時也可能由 TikTok 頁面發起貼文請求，因此暫緩貼文排程未形成真正的端點安靜期。首筆錯峰重試仍回空。

- 本機貼文空回應再次影響四個帳號。保持薩格勒布出口及 Chromium profile，執行一次性固定出口對照：貼文暫停約 10 分鐘後按 75 秒錯峰重試，保存 SQLite 狀態變化。程式和正常輪詢設定維持原值。

- 本機 Catalog 從手動檢視恢復。VPN 由首爾切換至薩格勒布，新建 Chromium profile 並維持空 cookies 匯入；驗證出口、Chromium、noVNC 和四個帳號心跳後重新排程貼文失敗項目。

## 2026-11-20

- 對齊第二輪 HAR 的貼文與相鄰請求。三筆 Story 與頁面 eligibility 查詢均和貼文請求在數十毫秒內發起，playlist 也多次近乎同時；未找到所有空回應之前都出現的單一會話請求。HAR 暫缺同一端點的非空成功樣本，未確認相鄰請求與空回應有因果關係。

- 第二輪手動 Chromium HAR 在 Catalog 暫停期間捕捉到 6 筆由網頁腳本發起的貼文 API 請求，全部 HTTP 200、宣告 0 bytes、Chromium 實讀 0 bytes。五筆 TikTok 主文件均為 HTTP 200，證實本輪貼文空回應可在手動瀏覽重現。

- 比對本機手動 Chromium HAR 與 Catalog 日誌：手動擷取含 15 筆貼文清單 HTTP 200，但 HAR 的內容長度是擷取器固定填入的 0，無法確認手動回應本文。較早的 Catalog 貼文失敗則確認宣告 0 bytes、實讀 0 bytes、解碼為 0 字元。手動 HAR 另記錄一筆帳號頁 HTTP 403。

- 本機暫停 Catalog 查詢程序時也暫停了 Playwright 的網路請求放行。解除舊控制連線並保留 Chromium 後，瀏覽器可載入一般 HTTPS。手動擷取 HAR 記錄到 TikTok 主文件 HTTP 403，Catalog 繼續暫停。

- 本機首爾出口 23:35:58 HKT 生效後，23:42:50 第一筆貼文 HTTP 200 空回應復發，間隔 6 分 52 秒。複查時四條貼文及一條 Story 有失敗狀態，Catalog 心跳和 noVNC 握手正常，未見新 403。

- 本機貼文空回應後採用手動恢復流程：VPN 從薩格勒布切換至首爾並驗證新出口。原 profile 重建時 Chromium 啟動失敗，保留原 profile，改用全新 volume 及空 cookie 匯入重試；noVNC 已接到新 Chromium。

- 23:33 HKT 複查本機 Catalog：薩格勒布出口 23:12:57 生效，現行容器第一筆貼文空回應在 23:28:52，距出口切換約 16 分鐘。四條貼文均連敗 3 次，Story、轉發與個人資料目前無失敗紀錄；此次日誌未見新 403。

- 本機以暫時 Compose override 將 noVNC 接至 Catalog 自己的 Xvfb，使手動觀察與實際排程共用同一個 Chromium 視窗。已驗證 noVNC HTTP、Chromium CDP 和 VNC RFB 握手，保留 Catalog 專用空 cookies 匯入設定。

- 手動 Chromium 在 VPN 重啟後顯示 `ERR_CONNECTION_CLOSED`。確認 VPN healthy 後只重建 noVNC 容器，以同容器的獨立 Chromium 測試一般 HTTPS、TikTok 登入頁及公開個人頁，均取得 HTTP 200。持久 profile 的視窗仍待逐頁確認。

- 本機 VPN 改至 `al-tia.prod.surfshark.com` 後複查。OpenVPN 已連線、VPN healthy、noVNC HTTP 200。手動 Chromium 容器內的一般 HTTPS 和 TikTok 首頁、登入頁及公開個人頁均回傳 HTTP 200；Gluetun IP 資料來源標示出口為 Zagreb。

- 清除本機 Catalog Chromium 的 TikTok cookies，經暫時 Compose override 停用舊 cookies 匯入後立即重試。原先 Story、轉發及多數個人資料的網路錯誤已清除；後續四條匿名貼文查詢另回報 `TIKTOK_EMPTY_RESPONSE`。LIVE 使用原有 cookie 掛載。

- 以唯讀 Chromium CDP 事件監看本機 Catalog 實際重試 @akachanm 個人資料。首爾 VPN 下 TikTok 主文件回傳 HTTP 403，Chromium 隨後回報 `ERR_HTTP_RESPONSE_CODE_FAILURE`；此案例確認為頁面導覽 HTTP 拒絕，非貼文 API 空回應。

- 本機 Telegram 再次無回覆時，暫停輪詢後使用無游標的 getUpdates 檢查，確認兩筆擁有者更新都低於已儲存的游標。保留設定備份，將游標對齊最早待收更新並重啟本機 Bot。

- 結束手動 Chromium 並以首爾 VPN 恢復本機 Catalog。將 Instagram、X、watchdog、封存匯出及 tunnel 暫時全切換至本機 Docker，確認 NAS 兩個相關專案無運行中容器。本機 IG 與 X worker healthy，但本機設定尚無這兩個平台的訂閱；Catalog 心跳正常、四個 TikTok 訂閱已載入，部分內容查詢仍有失敗紀錄。

- 本機 noVNC 斷線時 VPN 仍 healthy，手動 Chromium 容器已退出。原容器重啟再次失敗；確認 profile 無占用後備份殘留鎖並重建手動容器，驗證 noVNC 和容器內 TikTok 首頁的 HTTP 回應均為 200。

- 確認 GitHub Actions 最近四次 CI 均在 X 封存 ETA 測試失敗。Runner 在日期與時間之間輸出 U+2009 細空格，測試只接受一般空格。本機同一測試檔 19 項通過。

- 本機 TikTok VPN 改用 Surfshark 首爾 OpenVPN TCP。重新建立 VPN、解析器、LIVE 與手動 Chromium；Chromium 容器確認使用首爾出口，Catalog 在手動檢視期間暫停。

- 本機 TikTok Catalog 的 Story、轉發及個人資料查詢在 Chromium 導覽公開個人頁時出現 `ERR_HTTP_RESPONSE_CODE_FAILURE`，對外顯示 `TIKTOK_NETWORK_FAILED`。同一容器內未帶 cookies 的 HTTP 探測對 TikTok 首頁及公開個人頁均取得 HTTP 200 與非空內容。VPN 與 LIVE healthy，瀏覽器導覽失敗的確切 HTTP 狀態仍未取得。

- 追查切換至本機後 Telegram Bot 未回覆：確認兩端使用同一 Bot，本機輪詢心跳正常且無 webhook，但本機更新游標高於 NAS 停機游標，授權清單亦不同。已備份並將本機游標對齊 NAS 停機值，重啟本機 Bot，待新私聊指令驗證。

- 將 TikTok 執行環境切換至本機 Docker。停止 NAS 正式 TikTok 服務、共用 Telegram 相依服務及獨立錄影專案；本機啟動 VPN、解析器、LIVE、Catalog 和 Telegram 相依服務，使用本機設定及新瀏覽器 profiles。四個帳號已進入 LIVE 監看，Catalog 初期部分 Story 查詢遇到 `TIKTOK_NETWORK_FAILED`。

- 比對部署中的 TikTok 容器設定。舊本機 Catalog 為 ARM64、2 CPU、1536 MiB、開啟閒置凍結；NAS 為 AMD64、不限 CPU、約 5.64 GiB、停用閒置凍結。兩端 LIVE 映像 ID 亦不同。NAS 另有獨立 Compose 專案的 recorder，其參數與正式 LIVE worker 重疊兩個帳號，兩專案使用不同 VPN 容器；尚未確認是否影響查詢。

- 比對本機與 NAS 的 TikTok 服務。已核對的兩個 Dockerfile、Compose 設定，以及 NAS 容器內六個 LIVE／Catalog 模組與本機檔案指紋一致。兩邊的清單有相同四個帳號。本機除錯 worker 已停止，NAS LIVE healthy，Catalog 心跳正常但四條貼文及四條轉發查詢有失敗紀錄。

- 關閉 TikTok 貼文清單的每小時低頻測試，恢復正常輪詢、分頁與失敗重試排程。

- 21:51 HKT 唯讀複查 TikTok：VPN 與 LIVE worker healthy，四個目標均在檢查或監看，狀態快照未顯示錄影。@maidcafe_ikiss 的近期解析仍曾遇到 room enter HTTP 403 且未取得串流網址。Catalog unhealthy，近期貼文與轉發查詢回報 TIKTOK_EMPTY_RESPONSE，部分貼文回應為 HTTP 200、本文 0 bytes。

- 20:52 HKT 依使用者要求重連 TikTok VPN，核實公網出口 IP 已更換。依實際命名空間檢查，VPN 重啟後三個相依服務仍留在舊網路，重新啟動 LIVE worker、解析器及 catalog 後已全部確認接上新網路。VPN healthy。

- 追查 @maidcafe_ikiss LIVE 告警：NAS resolver 在 20:34–20:49 HKT 的最近十筆查詢均無串流候選，其中五次觀測到 room enter HTTP 403。這確認串流來源取得失敗，未確認 403 的上游原因或是否為 CAPTCHA。

- 唯讀核對 @maidcafe_ikiss 的 LIVE 告警：tiktok-watch 容器 healthy、重啟 0 次，帳號狀態為「檢查／錄影異常，重試中」。告警沒有底層錯誤分類，未確認直播狀態、是否漏錄或與 catalog CAPTCHA 有關。

- 19:42 HKT 複查 Telegram CAPTCHA 告警：四條 Story、四條轉發、三條個人資料目前為 `TIKTOK_CAPTCHA_REQUIRED`，@nao_kizuki 個人資料仍無失敗。四條匿名貼文維持 `TIKTOK_EMPTY_RESPONSE`，尚無證據將較早的空回應歸因於這波 CAPTCHA。

- 19:38 HKT 複查 TikTok 每小時輪詢測試：四個目標各完成三次測試輪詢，最後成功均仍停在部署前，最新錯誤皆為 `TIKTOK_EMPTY_RESPONSE`。catalog unhealthy、重啟 0 次，下一輪排在 20:06–20:12。

- NAS 啟用 TikTok 貼文清單低頻測試。每帳號輪詢、分頁續查及失敗重試至少相隔 3,600 秒，停用同一次貼文清單查詢的立即重試。Story、轉發、個人資料及手動單篇下載沿用原排程。Compose 可設 `TIKTOK_CATALOG_POST_POLL_TEST_SECONDS=0` 恢復原排程。NAS 映像 `870cbc038a53`，只替換 catalog 容器。TikTok 測試 91 項通過。

- 16:59:57 HKT 唯讀複查：四條貼文串流在 16:50–16:53 曾成功，隨後均再次出現空回應，連敗 1–3 次；catalog healthy、重啟 0 次。

- NAS 貼文恢復追蹤：16:46 HKT 四條貼文串流均已清零且無容器重啟。@nao_kizuki 與另一條串流在第 9 次空回應後約 32 分鐘、即各自排定重試時間恢復。另兩條最後一筆失敗至已確認成功相隔約 47 分鐘，首次成功時間因最新成功欄位會覆寫而未能確定。無證據顯示 32 分鐘是上游解除限制的固定時間。

- 唯讀比對 TikTok 貼文連續失敗與部署。11/19 23:22–23:32 已有密集空本文，早於匿名部署。11/20 10:56 啟動的同一映像未重啟，14:05–14:08 四條貼文相繼回空，16:35 兩條自行恢復；@nao_kizuki 最後成功 14:02:28，已連敗 9 次，16:14:46 仍回空。四條串流均為首頁游標、無回補，指數退避在近期變更前已存在。匿名切換對失敗率的影響仍未有同時對照證據。

- 補查 TikTok 免登入監看候選，記錄 RSS.app、RSSHub、Apify Clockworks 與 tiktok-dlp 的資料來源、通知及封存限制。見 [TikTok 貼文監看研究](docs/tiktok-post-monitoring-research-20261120.md)。

- 調查 TikTok 公開貼文監看。Display API 需要目標帳號授權，Research API 新影片索引最長可延遲 48 小時。以 `@nao_kizuki` 的既有 NAS 觀測為基礎，記錄匿名來源的限制、回補方式與驗收指標。見 [TikTok 貼文監看研究](docs/tiktok-post-monitoring-research-20261120.md)。

- NAS 的 TikTok LIVE 瀏覽器解析健康端點正常，實測 `@tiktok` 透過瀏覽器網路請求取得 1 個串流候選網址。此次驗證涵蓋解析，未測試播放或錄影。

- 移除 X／Twitter 指定日期回補按鈕及日期範圍指令入口，保留一鍵完整歷史封存。

- 修正匯出將 Unicode 等價日文路徑及空白 caption.txt 誤報為缺失；Instagram 舊封存完成判斷改依掃描、媒體與說明狀態。

- 調查 NAS 匯出缺失：Instagram 28 項媒體為 NFC／NFD 等價路徑誤報，4 項為原始說明空白且雜湊相符的 caption.txt 誤報；歷史按鈕另受 monitorOnly 與缺少 historyAt 影響。

- 匿名公開貼文已部署並完成受控重啟與 Cookie 隔離測試；後續仍有 HTTP 200 零位元組及限流，容器運行正常但貼文取得尚不可靠。測試、備份、版本與限制見 docs/tiktok-anonymous-observation-20261120.md。

- NAS 匿名擴大測試 @nao_kizuki：三個獨立空 Cookie context（原生、正式 guard、原生重測）皆由網頁取得有效清單，catalog provider 各取得 20 筆。第四個獨立匿名 context 加正式 guard，第一／二頁各 20 筆、交集 0、游標推進。未使用登入 Cookie、未寫正式資料庫；先前逾時未重現，仍未證實登入狀態為唯一原因或長期穩定。

- NAS 隔離對照：以相同 catalog provider、guard 與 post_response 流程測試匿名及複製現有登入 Cookie 的暫存 Chromium，兩者皆 TimeoutError；原工作階段未修改。此測試未記錄逾時細部階段，不能證明 Cookie 為唯一原因，亦不能與先前網頁原生清單成功等同。

- NAS 獨立匿名 Chromium（初始 Cookie 0）測試 @nao_kizuki：網頁原生 post/item_list 回應 HTTP 200、statusCode 0、19 筆；未見 Something went wrong，DOM 影片連結仍為 0。@tiktok 未觀察到清單回應，結果不確定。僅證實匿名瀏覽器單次清單取得成功，未改正式 catalog。

- Instagram、X、TikTok 完成歷史封存後，Telegram 帳號選單會移除一鍵回補按鈕，並在訊息顯示已封存。

- NAS 同一 VPN 出口匿名測試：yt-dlp 2026.10.26 查詢故障帳號與公開對照均回報 unable to extract；先前 tt-dlp 首頁查詢亦未成功。未更換正式工具。

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
