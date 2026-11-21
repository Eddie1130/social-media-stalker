# 待辦事項

## 功能

- [ ] 建立媒體 viewer。
- [ ] 監控 follower／following 變化。

## 穩定性調查（2026-11-17）

- [ ] TikTok catalog：補上安全錯誤分類碼、帳號／內容類型、查詢耗時、browser 子程序退出狀態及 generation，定位重複查詢失敗的原因；日誌不得包含憑證、私人 URL 或回應內容。
- [ ] X watch：保留 fatal 的安全例外類型、程式位置與檔案錯誤碼，避免只留下 X_OPERATION_FAILED；分開統計 HTTP 404／429／5xx、下載錯誤及程序退出。
- [ ] 持久化 Docker 健康切換、start／die／restart／oom 事件，保留容器 ID、服務及部署版本，區分部署與異常重啟。
- [ ] 同步記錄查詢新鮮度、下載佇列／完成數、Telegram 派送狀態及 NAS CPU／記憶體／磁碟等待，連續觀測 24–48 小時；有明確證據後才做單一變因測試。
- [ ] Telegram：針對 API 400 保存安全分類及對應工作識別，確認是否影響最終派送，不記錄訊息內容或收件者私人資料。
- [ ] 檢查其他專案 cloudflared tunnel 的 origin connection refused，確認已停止後端的路由是否仍需保留。

## Redis 效能評估（2026-11-21）

- [ ] 在 NAS 量測封存匯出預覽的檔案掃描耗時（p50／p95）及同帳號短時間內的重複預覽頻率。每次預覽目前都會重新收集檔案清單。見 [匯出預覽](export_service/server.py#L134)。
- [ ] 若掃描耗時明顯且重複預覽頻繁，先測試短效程序內快取，只存檔案數、總容量及缺失數等摘要，並比較命中率和預覽延遲。正式打包仍須重新建立快照。見 [匯出打包](export_service/server.py#L262)。
- [ ] 若多個程序需要共用預覽摘要，再評估 Redis。比較跨程序快取的延遲改善、記憶體用量及維運成本，並確認 Redis 無法連線時仍可即時掃描。
- [ ] 用現有瀏覽器查詢及媒體下載指標定位平台輪詢的耗時，並量測 SQLite 查詢及鎖等待後再決定是否需要調整資料庫。

此次評估依據程式碼，SSH 連線中斷，尚未取得 NAS 實測數據。

## 已確認事項

- [x] 完成 NAS 41 個容器的唯讀錯誤調查，詳見 [報告](docs/nas-container-errors-research-20261117.md)。
- [x] 停止舊 x-archive-bridge，設為 restart=no；保留容器及資料。日後重建舊 Compose 時仍須留意原有重啟設定。
- [x] 使用者以 Chrome 確認 maidcafe_ikiss 的 1 筆 repost 影片在 TikTok 端也無法存取；列為來源端問題，系統待補查標記尚未調整。
- [x] 14:56–14:57 HKT 核查：TikTok 最近一小時 10 筆查詢失敗涉及多個帳號，並非上述 repost；當下皆恢復、pending=0。X 待辦 256→248，IG 有近期成功查詢，Telegram pending=0；未見持續停滯或反覆崩潰證據。這是當次快照，不能取代持續觀測。

詳見 [TikTok 穩定性報告](docs/tiktok-stability-research-20261117.md)及[異常時間表](docs/tiktok-stability-incidents-20261117.csv)。

## 監控 NAS 上的專案容器

- [ ] 用 NAS 排程定期執行唯讀的 Compose 狀態檢查，將結果寫入 `ig-watchdog` 可讀取的狀態檔。Docker socket 留在主機端。
- [ ] 維護應常駐的服務清單。只有啟用時才納入 `archive-export` 與 `archive-tunnel`。排除臨時使用的 `tiktok-login`，並允許在維護期間暫停個別服務的告警。
- [ ] 區分容器退出、消失或反覆重啟，以及容器仍在運行但 Docker 回報 `unhealthy`。部署或短暫故障先給約兩分鐘緩衝，異常持續才透過現有 Telegram 告警路徑通知一次。先前已發出告警的服務恢復後，再通知一次。
- [ ] 對已有健康檢查的服務直接採用 Docker 健康狀態。對 Telegram Bot API、TikTok Browser Resolver 與啟用中的 `archive-tunnel`，先確認映像是否已有可用探測，再補上缺少的服務探測。
- [ ] 由 NAS 的獨立通知檢查 `ig-watchdog` 本身與排程是否仍在運作。各服務與 Docker 繼續負責重試及重啟。
- [ ] 驗證容器退出、持續 `unhealthy`、短暫重啟、故障恢復、維護暫停及選用服務未啟用時的告警行為。
