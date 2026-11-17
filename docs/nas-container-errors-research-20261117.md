# NAS 全容器錯誤原因調查（2026-11-17）

## 範圍及結論

本次檢查 NAS 全部 **41 個現存容器**，逐一讀取狀態、退出碼、OOM 標記、重啟計數、健康檢查與近期日誌；對有具體疑點的服務補讀程式、持久異常狀態或最後歷史日誌。採樣為香港時間約 13:38–13:44，並非同一瞬間。沒有修改／重啟任何服務，也沒有建立缺失資料庫。

- 運行中 **19**：11 healthy、1 unhealthy、7 未設 healthcheck。
- 已停止 **22**：其中 5 個殘留 unhealthy，不能視為當下運行故障。
- **沒有證據顯示所有容器出錯都源自同一 NAS 問題。** 已確認來源包括缺失的掛載目錄、瀏覽器傳輸、API 拒絕、停止／部署期間的心跳過期、客戶端斷線與上游連線問題。
- 全部現存容器 OOMKilled=false；這不足以排除所有歷史記憶體問題，但不能僅憑 exit 137 歸因 OOM。

證據原檔留在 Git 忽略目錄 `data/research/container-errors-20261117/`，含私人日誌，不加入 Git。主要檔案：`snapshot.jsonl`（41 個容器）、`project-issues.txt`、`bridge-source.txt`、`x-bridge-detail.txt`、`stopped-detail.jsonl`。一般日誌限制最近 72 小時最多 1500 行；部分舊服務另補最後 100 行，所以「沒有觀察到錯誤」不代表歷史從未出錯。舊的完整專案日誌及 observer 證據沿用前一份 TikTok 調查。

## 1. 目前確實故障：舊 x-archive-bridge

**直接原因已確認，移除目錄的操作者／操作尚不明。**

- 11-15 14:23:46，worker 在 `bridge.py:85` 呼叫 sqlite3.connect 時發生 `OperationalError: unable to open database file`。
- 掛載設定的主機來源為 `/volume1/docker/x-archive-bridge/state`；本次 ls 確認主機路徑不存在。
- 容器 `/state` 為空，stat 的 nlink=0；PID 1 的 fd 3 指向 `/state/service.lock (deleted)`。唯讀開啟 `/state/queue.sqlite` 同樣失敗。
- 程式外層 except 保存 fatal_error 並結束 worker；HTTP server 不退出，也沒有重建 worker 的迴圈。
- `/healthz` 實測 HTTP **503**、ready=false；healthcheck 因而持續失敗。主程序仍存活，所以 RestartCount=0，不能靠該數字判斷封存 worker 正常。

證據鏈支持「狀態掛載目錄被移除／失效 → SQLite 無法開啟 → worker 結束 → HTTP 繼續運行但不再 ready」。不應直接重啟並產生空資料庫來掩蓋狀態遺失；先找原目錄或備份，再確認舊 bridge 是否仍有用途。本次未操作復原。

其 10-16 的歷史 401 拒絕是另一類驗證失敗，不能當作 11-15 SQLite 故障原因；11-15 前的 BrokenPipeError 也是獨立的回應連線中斷。

## 2. TikTok catalog：瀏覽器子程序錯誤，最底層原因仍未完全定位

前次已確認 241 筆查詢失敗，以及靜態備份 13/16 streams 為 `TIKTOK_BROWSER_TRANSPORT_FAILED`、連敗 6–8 次。237 筆失敗經子程序回傳錯誤路徑，4 筆經 query timeout 路徑；目前缺少每筆安全分類碼及 browser stderr，不能把它們全部歸為同一種根因。

共享 browser 失效會同時影響多個內容串流，逐串流退避又會延長恢復。NAS 現有操作文件記錄 FREEZE_IDLE=0，故不能在未驗證下聲稱目前 idle freeze 就是主因。尚需 browser 退出狀態、分類碼與同步主機資源時間序列來區分 Chromium/CDP、頁面、網路及 I/O。

本次健康快照 pending=0、unresolved=1。**使用者已用 Chrome 手動確認剩餘 maidcafe_ikiss repost 的影片也無法回應，故該筆依使用者驗證歸為 TikTok 來源端不可存取，不計為 NAS 下載故障。** 未修改其系統標記，也不能保證從未被辨識或已過期內容的完整性。

詳見 [TikTok 調查](tiktok-stability-research-20261117.md)。

## 3. X watch：一次程序級退出，但目前無法證實根因

- 11-17 10:39:10 記錄 `X_WATCH_FATAL / X_OPERATION_FAILED`；10:39:31 再次 STARTED，RestartCount=1。
- safeReason 將不符合限定大寫碼格式的例外一律縮成 X_OPERATION_FAILED，原始 exception 類型、stack 及 syscall 沒有保留。因此無法由該碼判定是平台拒絕、檔案 I/O、狀態寫入或程式錯誤。
- 主迴圈呼叫多個步驟，未處理的 cycle／停止清理例外可以傳到頂層；這是程式可能路徑，不能定位實際是哪一步。
- 目前 healthy；健康狀態的 4 個帳號 failures 皆為 0，帳號池 active=3、available=3。當次 `mikuru_hositani` 有 pending=1562，屬於待處理工作，不能僅憑待辦判定下載失敗，也不能沿用前次三帳號 pending=0 的結論。

需要保存下一次 fatal 的安全 exception 類別、位置及檔案錯誤碼；現有證據不能給確定根因。

## 4. Instagram：歷史查詢／下載及心跳錯誤均已解除

持久 issues.json 保留 **19 個 key**，全部 active=false。這是各 key 的最後狀態，不是 19 次完整歷史事故：同 key 可能已多次覆寫。

- 6 個 `NAS_DOWNLOAD_NETWORK_OR_IO_ERROR`、2 個 `NAS_DOWNLOAD_ABORTED_OR_TIMEOUT`：分類涵蓋下載網路、I/O、取消／timeout；沒有足夠底層證據區分網路或磁碟。最近兩個 timeout 狀態均在 11-16 23:13 解除。
- 4 個 `CATALOG_BOOTSTRAP_BROWSER_OR_NETWORK_ERROR`、1 個 GraphQL browser/network、1 個 server/GraphQL、2 個 target lookup browser/network：表示查詢鏈路曾失敗，不能直接等同登入失效或被封鎖。最新 target lookup 於 11-16 10:26:39–10:37:04 異常，鄰近已記錄的部署時間；時間相近不是唯一因果證明。
- 1 個 `STORY_FETCH_FATAL:exit=1`：子工作退出，底層原因未在此 key 保存。
- 各 1 個 watchdog heartbeat stale、worker progress deadline exceeded：直接判定為心跳／進度超時，無法只憑這些 key 證明 CPU、I/O 或 worker 卡死的原因。

本次 worker 摘要 failures=0、telegramOk/archiveOk/catalogOk=true。`BLOCK_UNKNOWN_INSTAGRAM_WRITE` 是既有網路防護的阻擋紀錄，不應單憑名稱當成整個下載服務故障。

## 5. Telegram 與 watchdog：API 400、部署期間心跳及通知重試

- ig-telegram 在 11-16 22:25:06、22:25:07 各一次 `PERSONAL_DELIVERY_RETRY / TELEGRAM_ERROR_400`；表示 Telegram 明確拒絕該請求。client 只保留 HTTP／API code，沒有 API description；不能確定是已刪除訊息、參數、媒體或其他 400 原因。
- 程式會保存待辦並退避重試；兩筆出現在控制服務 22:24:58 啟動後。與部署接近，但未保留 task 識別，不能逐筆證明之後送達的是原兩筆。
- watchdog 最新持久狀態：`CONTROL_HEARTBEAT_STALE` 11-16 10:16:52–10:24:00；`SUPERVISOR_STOPPED` 22:24:50–22:25:30，兩項均已解除。後者緊接控制／watch 重新啟動，符合短暫啟停的情境。
- 歷史日誌有 14 筆 CONTROL_FALLBACK_RETRY。程式在網路失敗或 API 未接受時都可能記這個事件；這批沒有 429 安全碼，不能聲稱已確認限速、封鎖 Bot 或收件者封鎖。
- WATCHDOG_ALERT_ROUTED kind=error 表示 watchdog 正在轉送其他元件警報，不代表 watchdog 自身崩潰。
- Local Bot API 兩個運行容器本次未發現對應明確 fatal；無 healthcheck，不能由 running 推論傳送百分之百成功。本次未主動傳送測試訊息或呼叫 getUpdates。

## 6. VPN 與 tunnel：有些是相容／效能警告，有些是請求失敗

**本專案 tiktok-vpn**：啟動時出現不認得 `block-outside-dns`，隨後同一秒已 `Initialization Sequence Completed`，之後取得出口 IP，目前 healthy。因此該行不是 VPN 啟動失敗證據。這個選項與 Windows DNS 防護相關，見 [OpenVPN 文件](https://openvpn.net/community-docs/community-articles/openvpn-2-4-manual/)。另一行 `cannot get version information / commit not found` 是取得版本資訊失敗，沒有證據顯示它阻斷隧道。

**本專案 archive-tunnel**：UDP receive buffer 只能由 208 增至 416 KiB、未達 7168 KiB，是系統 buffer 上限的效能警告。官方說明 buffer 可限制高速 QUIC 吞吐；這不等同 tunnel 退出，本容器仍 running。[quic-go 文件](https://quic-go.net/docs/quic/optimizations/)

**其他專案 cloudflared-tunnel**：最近 1500 行的錯誤包含：

- 多個 origin port 的 connection refused（3000、5174、3001、5678）：當時該目標沒有接受連線，屬於後端服務／路由端點不可用，不能歸為 TikTok 故障。
- QUIC `timeout: no recent network activity`、listener/datagram failure：支持曾有 tunnel 傳輸中斷；樣本內也有 6 筆 registered connection，顯示有重新建立連線。不能僅憑此判定是 ISP、VPN 或 Cloudflare 單一責任。
- 遠端取消 stream、request context canceled：支持請求被對端／請求生命週期取消，不等同容器崩潰。

不將上述日誌行數當成獨立事故數；部分同一錯誤會同時記在不同層。

## 7. 其他 browser resolver 與停止容器

- 舊 `tiktok-browser-resolver` 11-16 16:28 發生一次 BrokenPipeError，stack 位於回寫 HTTP JSON。直接原因是對端連線在回應前關閉；健康檢查 timeout 是可能情境，沒有完整請求紀錄可確認。容器目前 healthy。
- `spacemake-gui` 停止前先收到 SIGTERM，隨後等待 display/desktop/vnc/web 結束，約 10 秒後退出 137；與停止寬限後被強制結束相符，但缺 Docker kill 事件不能確認操作者。最後健康失敗為 noVNC port 6080 connection refused，並非證實 OOM。
- `n8n`：內建 Python runner 因缺 Python 3 無法啟動；另有 telemetry DNS EAI_AGAIN、feature flags timeout，以及 database connection timeout 後 recovered。最後明確收到 SIGTERM，再退出 137；不能把最後退出歸因於先前已恢復的 DB timeout。
- `ig-story-login`：最後是 `Detected unsettled top-level await`，指向 `await new Promise(() => {})`，exit=13，與 Node 對永不 resolve 的 top-level await 定義一致；是明確程式生命週期問題，非下載故障。[Node 文件](https://nodejs.org/download/release/v22.23.0/docs/api/esm.html)
- `easy-travel` exit=1，但最後 npm 日誌明載 signal SIGTERM；不能只憑 1 當成未捕捉程式例外。
- `openclaw` exit=1 的目前 FinishedAt 在 9 月，最後可讀應用日誌卻停在 4 月並為 SIGTERM；時間不吻合，無法定位 9 月退出原因。
- 其他 exit=137 只證明 SIGKILL 類終止，不證明 OOM；本次沒有完整歷史 kernel／Docker 事件可確認觸發者。[Docker 退出訊號](https://docs.docker.com/reference/cli/docker/container/ls/)、[停止寬限處理](https://docs.docker.com/reference/cli/docker/container/restart)
- 舊 IG watch/watchdog 已 exit=0，與切換新專案的既有紀錄相符；不能因保留 unhealthy 就當作新服務也故障。

## 全部容器逐項覆蓋

下表的「未見明確錯誤」只限本次保留的日誌樣本；「無檢查」表示不能評估應用健康。

| 容器 | 狀態／健康 | ExitCode | 本次判讀 |
|---|---|---:|---|
| social-media-stalker-tiktok-watch-1 | running / healthy | 0 | 本次樣本未見明確錯誤 |
| social-media-stalker-ig-telegram-1 | running / healthy | 0 | 兩筆 API 400 重試；缺具體 description |
| social-media-stalker-tiktok-catalog-1 | running / healthy | 0 | browser 子程序錯誤／timeout；詳第 2 節 |
| social-media-stalker-tiktok-browser-resolver-1 | running / 無檢查 | 0 | 本次樣本未見明確錯誤 |
| social-media-stalker-tiktok-vpn-1 | running / healthy | 0 | 選項相容／版本資訊錯誤；VPN 已連線 |
| social-media-stalker-ig-watch-1 | running / healthy | 0 | 19 個歷史 issue key 全解除；詳第 4 節 |
| social-media-stalker-performance-observer-20261116 | exited / 無檢查 | 124 | 24 小時觀測器；exit 124 符合 timeout 到期 |
| social-media-stalker-x-watch-1 | running / healthy | 0 | 一次 fatal；安全碼不足以定位根因 |
| social-media-stalker-performance-observer-20261115 | exited / 無檢查 | 143 | exit 143 符合 SIGTERM；誰停止未保留 |
| social-media-stalker-archive-tunnel-1 | running / 無檢查 | 0 | UDP buffer 效能警告，未退出 |
| social-media-stalker-ig-check | exited / 無檢查 | 0 | 一次性檢查 exit 0，既有日誌 SESSION_OK |
| social-media-stalker-archive-export-1 | running / healthy | 0 | 本次樣本未見明確錯誤 |
| social-media-stalker-ig-watchdog-1 | running / healthy | 0 | 心跳／停止警報及 fallback 重試，已解除 |
| social-media-stalker-telegram-bot-api-1 | running / 無檢查 | 0 | 本次樣本未見明確錯誤 |
| kmb-api-api-1 | running / healthy | 0 | 本次樣本未見明確錯誤 |
| spacemake-gui | exited / unhealthy | 137 | SIGTERM 後未及完成停止；noVNC 拒絕連線 |
| tiktok-browser-resolver | running / healthy | 0 | 一次 HTTP 回應 BrokenPipe；目前 healthy |
| tiktok-recorder | running / 無檢查 | 0 | 本次樣本未見明確錯誤 |
| x-archive-bridge | running / unhealthy | 0 | 狀態目錄已刪除，SQLite 開啟失敗，worker 結束 |
| tiktok-vpn-tiktok-post-monitor-1 | exited / 無檢查 | 0 | 未見明確錯誤；停止原因未確認 |
| ig-story-login | exited / 無檢查 | 13 | 未完成 top-level await，Node exit 13 |
| ig-story-browser-ig-watch-1 | exited / unhealthy | 0 | 舊服務 exit 0，保留歷史 unhealthy |
| ig-story-browser-ig-watchdog-1 | exited / unhealthy | 0 | 舊服務 exit 0，保留歷史 unhealthy |
| telegram-bot-api | running / 無檢查 | 0 | 本次樣本未見明確錯誤 |
| hummingbot | exited / 無檢查 | 143 | exit 143，符合 SIGTERM；觸發者未知 |
| polprobe | exited / 無檢查 | 137 | SIGKILL 類退出；無證據確認 OOM 或操作來源 |
| spacemake-tg | exited / 無檢查 | 0 | 未見明確錯誤；停止原因未確認 |
| spacemake-tunnel | exited / 無檢查 | 0 | 未見明確錯誤；停止原因未確認 |
| spacemake-browser-proxy | exited / 無檢查 | 137 | SIGKILL 類退出；無證據確認 OOM 或操作來源 |
| apple-pickup-watcher | exited / 無檢查 | 137 | SIGKILL 類退出；無證據確認 OOM 或操作來源 |
| surfshark-vpn | running / healthy | 0 | 本次樣本未見明確錯誤 |
| adguardhome | exited / 無檢查 | 0 | 未見明確錯誤；停止原因未確認 |
| gourmet-hunter | exited / 無檢查 | 0 | 未見明確錯誤；停止原因未確認 |
| n8n | exited / 無檢查 | 137 | 缺 Python runner、DNS／DB 暫時錯誤；最後 SIGTERM |
| openclaw | exited / unhealthy | 1 | 目前退出與日誌時間不吻合，根因未確認 |
| ios-pwa | exited / 無檢查 | 0 | 未見明確錯誤；停止原因未確認 |
| savings-tracker | exited / 無檢查 | 137 | SIGKILL 類退出；無證據確認 OOM 或操作來源 |
| easy-travel | exited / 無檢查 | 1 | 最後 npm 記錄 SIGTERM |
| card-calculator | running / 無檢查 | 0 | 本次樣本未見明確錯誤 |
| cloudflared-tunnel | running / 無檢查 | 0 | origin 拒絕連線、QUIC 中斷／遠端取消 |
| jellyfin | exited / unhealthy | 0 | exit 0；最後保存檢查曾成功，殘留 unhealthy 不代表現行故障 |

## 調查優先順序

1. 先確認舊 X bridge 是否仍需使用；若需要，找回原狀態目錄及 queue 備份後才規劃復原。
2. 對 TikTok browser 及 X fatal 保存安全分類、退出狀態與來源位置，解決目前不能歸因的證據缺口。
3. 核對 tunnel 中已停止／不存在的 origin 路由是否仍需要，避免持續向不可用後端送流量。
4. 持久化 Docker health/lifecycle 事件及主機資源指標，區分部署、平台、程式與 NAS 壓力；本次不直接修復或更改任何服務。
