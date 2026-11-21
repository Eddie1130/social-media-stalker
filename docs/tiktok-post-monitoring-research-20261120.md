# TikTok 貼文穩定監控研究（2026-11-20 香港時間）

## 針對 @nao_kizuki 的結論

若目標創作者願意授權且應用獲准，優先驗證 TikTok Display API 作為**新公開影片的偵測來源**。相片貼文覆蓋與媒體封存各需獨立驗證。若無法取得創作者授權，這次查核的官方介面沒有提供適合本專案的低延遲、可完整分頁的第三方公開貼文清單。現有 NAS 瀏覽器監控應按盡力服務管理，清楚顯示資料何時停止更新。TikTok App 的個別貼文通知可作人工補查訊號。[Display API 指南](https://developers.tiktok.com/docs/en/display-api-get-started)、[List Videos](https://developers.tiktok.com/docs/en/tiktok-api-v2-video-list/)、[TikTok App 個別通知設定](https://support.tiktok.com/en/using-tiktok/followers-and-following/muting)

本次依專案紀錄選定 @nao_kizuki，@tiktok 僅為先前對照帳號。研究沿用已記錄的正式環境結果，未新增對目標的線上測試。未確認創作者是否願意授權、本專案是否已有核准的開發者應用，或目標相片貼文在 Display API 的實際覆蓋。[專案變更紀錄](../CHANGELOG.md)、[11 月 20 日匿名查詢觀察](tiktok-anonymous-observation-20261120.md)

## 現有 NAS 證據

- @nao_kizuki 的一次匿名瀏覽有成功回應及 19 筆項目，當時頁面 DOM 的影片連結數仍為 0。另一輪四個獨立匿名 context 取得有效清單，第四個 context 的兩頁各 20 筆、無重複且游標前進。@tiktok 那輪未觀察到清單回應，對照結果未能判定。這些快照支持「匿名曾可用」和「DOM 空白會漏訊」兩點。[專案變更紀錄](../CHANGELOG.md)
- 15:23 的正式觀察中，四個帳號的貼文串流都曾成功，之後四條都報錯。其餘 12 條 Story／轉發／profile 串流無錯。全服務近兩小時累計 35 次空回應與 1 次限流，容器無重啟或 OOM。空回應的 HTTP 狀態是 200，但宣告及實讀長度皆為 0，沒有可供驗證的清單。這確認失敗發生在資料取得階段，平台回空的原因仍未釐清。[匿名查詢部署及正式觀察](tiktok-anonymous-observation-20261120.md#再次變紅的證據1523-香港時間)
- 部署後資料庫快照驗證保留了 4 個目標、16 條串流和 2,972 筆既有項目。這項結果驗證歷史保存，貼文偵測延遲、漏報率和新貼文通知仍待端到端驗收。[資料完整性再驗證](tiktok-anonymous-observation-20261120.md#資料完整性再驗證)

## 來源選擇

| 來源 | 官方規格與適用性 |
| --- | --- |
| Display API | 應用需獲准使用相關產品與 scope，創作者以自己的帳號授權 `video.list`，登入監看者的帳號無法替創作者授權。List Videos 提供依發佈時間倒序、可分頁的公開影片，每頁最多 20 筆。Video Object 提供 ID、發佈時間、分享及嵌入連結等欄位，封面 URL 有 6 小時效期，欄位表沒有原檔下載或相片輪播資產清單。適合先驗證公開影片偵測與連結通知。相片、混合格式及完整封存分開驗收。[入門指南](https://developers.tiktok.com/docs/en/display-api-get-started)、[List Videos](https://developers.tiktok.com/docs/en/tiktok-api-v2-video-list/)、[Video Object](https://developers.tiktok.com/docs/en/tiktok-api-v2-video-object) |
| Research API | Query Videos 支援使用帳號名稱查公開影片資料。使用資格需按研究計畫申請及核准，官方說新影片加入搜尋索引可能需 48 小時。即使獲准，時效仍不適合分鐘級告警。[研究資格](https://developers.tiktok.com/products/research-api/)、[Query Videos](https://developers.tiktok.com/docs/en/research-api-specs-query-videos)、[索引延遲 FAQ](https://developers.tiktok.com/docs/en/research-api-faq/) |
| Content Posting API webhook | 可回報透過該 API 提交的內容何時公開，事件依 `publish_id` 關聯。適用於創作者透過合作發佈流程提交的貼文，涵蓋範圍由提交途徑決定。[Get Post Status](https://developers.tiktok.com/docs/en/content-posting-api-reference-get-video-status)、[Webhook 事件](https://developers.tiktok.com/docs/en/webhooks-events) |
| Data Portability API | 需創作者授權、應用經審核，適用於 EEA／英國 TikTok 使用者。支援一次性或持續的資料匯出，官方記載貼文匯出可提供 MP4／JPG 下載網址。若資格與授權均符合，可獨立評估作為封存來源，交付時間與輪播完整性仍須實測。[產品及資格](https://developers.tiktok.com/products/data-portability-api/)、[匯出欄位](https://developers.tiktok.com/docs/en/data-portability-data-types) |
| Creator Profile Embed／oEmbed | 嵌入卡片精選最多十支近期影片，oEmbed 回傳嵌入標記和基本資訊。可用於人工查看，無適合回補的完整分頁清單。[Embed Creator Profiles](https://developers.tiktok.com/docs/en/embed-creator-profiles/) |
| TikTok App 貼文通知 | 官方支援在個別帳號的個人頁面調整貼文推播。適合人手發現及核對貼文 URL，完整性應透過已知貼文清單另外驗證。[TikTok 個別通知設定](https://support.tiktok.com/en/using-tiktok/followers-and-following/muting) |

若取得授權，OAuth 使用回應的 `expires_in`／`refresh_expires_in` 排程更新，對每帳號的 refresh 加互斥並持久化最新 token；成功 refresh 會輪替 refresh token。權限撤銷應轉成需要重新授權的狀態。Display API 的限額及 429 規則只適用於正式 API，現有網頁管道的預算應按其實際失敗與退避行為評估。[OAuth Token 管理](https://developers.tiktok.com/docs/en/oauth-user-access-token-management/)、[API 限額](https://developers.tiktok.com/docs/en/tiktok-api-v2-rate-limit)

## 監控設計與驗收建議

1. **維持每帳號、每類型獨立健康狀態。** 現行貼文完整掃描後正常輪詢間隔為 300 秒，錯誤已有退避。先保留間隔，使用每次查詢的結構化失敗類型判斷空本文、限流、權限或服務故障；遇到平台要求驗證時停在可人工處理的狀態。對「健康但沒有貼文」採用帶正確帳號、資料結構和分頁終止條件的有效空清單；對空本文或失敗保留上次狀態。[排程、驗證及錯誤處理](../tiktok/catalog_worker.py#L440)、[現行間隔](../tiktok/catalog_worker.py#L29)
2. **衡量首頁掃描與補漏是否完成。** 現行 `lastSuccess` 會在單頁成功提交後更新，分頁掃到一半也會前進。建議另記錄最近一次從首頁掃到既有重疊區或清單末端的完成時間，並將「最近成功收到一頁」與「已補齊偵測缺口」分別納入狀態。續掃時使用服務回傳的游標與明確終止訊號，勿用單頁筆數或舊貼文時間單獨判斷；驗收包含置頂、第一頁重排、短頁及中途失敗。[頁面銜接、提交及回滾](../tiktok/catalog_worker.py#L636)、[List Videos 分頁規格](https://developers.tiktok.com/docs/en/tiktok-api-v2-video-list/)
3. **沿用已存在的資料與收據。** 延用現有目標身分核對及 `(target, kind, id)` 記錄去重，將清單提交與游標更新放在同一交易。若新增 API，先以唯讀影子比對證實新來源的帳號對應及貼文 ID 有交集，避免來源切換時歷史重送。分開量測公開至偵測、偵測至 Telegram、媒體至封存完成；已取得 ID 和連結但媒體缺失時保留該貼文待修復。驗收要覆蓋發送後程序重啟的情形，確認 outbox 積壓及實際重複數。[帳號核對及項目查重](../tiktok/catalog_worker.py#L440)、[現有資料驗證](tiktok-anonymous-observation-20261120.md#資料完整性再驗證)
4. **先跑 24 小時基線，再判斷穩定性。** 每分鐘唯讀觀察四個帳號各自的最後成功、完成掃描時間／分頁階段、空本文／429、pending／unresolved 與容器健康。建議先以「完整掃描超過 15 分鐘未前進則顯示延遲」為告警門檻，後續以至少 7 天觀察驗收。對延遲的初始目標可用公開至偵測 P95 ≤ 15 分鐘，另要求已知測試貼文零漏報、零重複通知，並列出各貼文類型的樣本數。這些是驗收提案，現有證據未達到可宣稱的穩定性結論。[現有唯讀觀察方式](tiktok-catalog-reliability.md#驗證及排障)
5. **建立可比對的真實發佈樣本。** 用自有或合作測試帳號建立有發佈與公開可見時間的公開影片、相片輪播等案例；對 @nao_kizuki 則以人工核對的公開貼文 URL 和 App 推播作觀察線索。記錄首次確認公開、首次入庫、首次通知和封存完成時間。沒有新增貼文的觀察窗可量到查詢可用率，偵測延遲及漏報則等待足夠樣本。發布到公開的時間和公開到偵測的時間分開量測，因為發佈過程可能包含審核。[TikTok 發佈狀態與公開事件](https://developers.tiktok.com/docs/en/content-posting-api-reference-get-video-status)

對目前的 @nao_kizuki，先以既有 NAS 歷史資料建立貼文查詢基線。創作者授權與應用核准成立後，再以影子讀取驗證 Display API 的影片覆蓋及延遲，驗收通過才切換偵測來源。本研究未更改程式或 NAS 設定。

## 不需 TikTok 帳號登入的第三方候選

| 候選 | 監控方式與限制 |
| --- | --- |
| RSS.app（網站） | 可用公開個人頁網址產生持續更新的 RSS。文件說明需為免登入可瀏覽的帳號，feed 顯示影片縮圖。適合接 RSS 閱讀器或通知流程，更新間隔及相片覆蓋須實測。[產品文件](https://help.rss.app/en/articles/8891118-how-to-create-rss-feeds-from-tiktok) |
| RSSHub（開源自架） | TikTok User 路由將公開創作者嵌入頁的影片清單轉為 RSS。這個來源與目前 catalog 的網頁貼文清單不同。程式只讀嵌入頁現有清單，沒有歷史分頁。TikTok 的嵌入產品只展示精選的最多十部近期影片。[路由原始碼](https://github.com/DIYgod/RSSHub/blob/master/lib/routes/tiktok/user.ts)、[TikTok 嵌入文件](https://developers.tiktok.com/docs/en/embed-creator-profiles/) |
| Apify Clockworks（託管 API） | 文件列出 Apify 帳號及 TikTok username 即可開始，支援排程執行與輸出資料。要接 Telegram 仍需依貼文 ID 做差異比對及通知。適合評估為結構化第二來源，需驗證成本、空回應行為及相片覆蓋。[產品與排程說明](https://apify.com/clockworks/tiktok-profile-scraper) |
| nqrwhal/tiktok-dlp（開源自架） | 提供定期監看、Discord 通知和封存，TikTok cookies 為選填。依賴 yt-dlp 等工具，值得參考監控和失敗重試設計，但專案已有同一 NAS 出口的 yt-dlp 清單查詢失敗紀錄。[開源專案](https://github.com/nqrwhal/tiktok-dlp)、[NAS 觀測紀錄](../CHANGELOG.md) |

建議先以 RSS.app 評估備援通知，再視是否需要結構化資料測試 Apify。如果要留在 NAS 自架，RSSHub 的嵌入頁可作第二個近期訊號。上述候選依公開文件和原始碼查核，尚未提交 @nao_kizuki 到第三方服務，也未量測實際更新延遲或漏報率。
