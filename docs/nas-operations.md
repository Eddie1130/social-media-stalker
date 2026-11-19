# NAS 執行環境

正式服務位於 `ssh nas` 的 `/volume1/docker/social-media-stalker`。

## TikTok catalog 的 NAS 設定

NAS `.env` 使用 `TIKTOK_CATALOG_FREEZE_IDLE=0`，使帳號切換時保持腳本可執行；
每輪結束仍會將讀取頁面移至 `about:blank`，避免持續執行 TikTok 頁面。
Chromium CDP 啟動等待最多 60 秒，帳號頁面導航最多 120 秒，均有有限上限。
`compose.tiktok.yml` 將 catalog 的 `/tmp` 掛載為 256 MiB tmpfs，供暫存 cache
與 X11 sockets 使用；登入 profile 繼續保存在 named volume，不會因重啟而清除。

依使用者要求，NAS catalog 採最大資源額度：`TIKTOK_CATALOG_MEMORY_LIMIT=6056730624`
（目前主機 `/proc/meminfo` 的 MemTotal，約 5.64 GiB），CPU 配額為 0。
資源按需與 DSM／其他容器共享。硬體記憶體變更時須重新核對此值。
NAS 舊核心動態提高 RAM 限制時，應先提高 RAM+swap 總額，再提高 RAM；
`docker update --memory 0` 不會清除既有限制，而 swap `-1` 在此主機也未實際解除
原 cgroup 限制，因此必須檢查 cgroup 實際值，不能只看 Docker 設定欄位。

NAS 的 Compose 2.20 在只選 catalog 並使用 `--no-deps` 時，可能無法解析
`network_mode: service:tiktok-vpn`。更新 catalog 時使用
`./igctl up -d --no-build tiktok-vpn tiktok-catalog`，讓 Compose 納入既有 VPN；
不需強制重建或重新建立 VPN 容器。

只複製專案目錄不包含 Docker named volumes。遷移時也應保留 Telegram Local
Bot API、TikTok browser／catalog profiles；cookies JSON 不等於完整瀏覽器 profile。

gallery-dl 以函式庫使用時，需提供它的 `LoggerAdapter`，否則頁面解析失敗的
錯誤處理可能再拋出缺少 `traceback` 的 `AttributeError`。本專案使用不輸出
私人資料的 adapter，並只記錄來源位置、例外類型及限定格式的 Chromium 網路錯誤碼。

## Compose 專案名稱

`docker-compose.yml` 的預設專案名稱為 `social-media-stalker`，一般容器名稱為
`social-media-stalker-<服務名稱>-1`。請勿以 `COMPOSE_PROJECT_NAME` 或 `-p`
重新指定舊的 `ig-story-stalker` 名稱。

NAS 已從舊專案切換：既有映像以新名稱重新標記，三個 named volumes
（Telegram Local Bot API、TikTok browser profile、TikTok catalog profile）
於停止舊服務後複製到 `social-media-stalker_` 前綴的資料卷。
`data/`、`downloads/`、`logs/` 的 bind mount 路徑維持不變。
舊 `ig-story-stalker_` 資料卷保留作為切換當時的備份，不含新服務啟動後的變更。
不要直接啟動舊專案；若需復原，先停止新專案並評估資料差異，以免出現兩份 writer。

## CPU CFS 相容設定

此 NAS 的 Docker 回報不支援 CPU CFS quota／period。若啟動時出現
`NanoCPUs can not be set`，在 **NAS 的 `.env`** 設定：

```dotenv
X_CPU_LIMIT=0
TIKTOK_CATALOG_CPU_LIMIT=0
```

`0` 停用這兩個服務的 CPU 配額；原有記憶體限制仍保留。這是主機專用設定，
不要將 NAS `.env` 提交至 Git，也不必修改支援 CPU CFS 的主機預設值。
停用配額後，這兩個服務可以使用主機可用的 CPU，應留意 NAS 負載。

設定變更不需重建映像。在 NAS 專案目錄執行：

```sh
./igctl --profile archive-export --profile archive-tunnel config --quiet
./igctl --profile archive-export --profile archive-tunnel up -d --no-build
./igctl --profile archive-export --profile archive-tunnel ps -a
```

確認容器健康檢查與日誌；成功建立容器不代表平台登入、VPN 或 Telegram 均正常。

## 搬遷後 Telegram 無回應

健康檢查的 `pollOk` 只表示 API 輪詢成功，不保證使用者訊息已被處理。
若搬遷時未帶走原 Local Bot API 的 named volume，須留意新的待收
`update_id` 是否小於 `data/control/settings.json` 保存的 `offset`；
此情況會讓控制器略過訊息，即使容器仍顯示健康。

排查時先確認 Bot 身分、私人聊天授權、Webhook、回覆佇列及收訊位置。
需要查看待收更新時先停止唯一收訊控制器，再以不含 `offset` 的
`getUpdates` 檢查編號；不要使用負 offset 或丟棄待收訊息。
只有確認來源切換造成編號不一致後，才在控制器停止期間備份設定，
將 offset 調整至已檢查的待收編號，保留其餘訂閱、收據及狀態。
重新啟動後確認 offset 前進、回覆佇列清空，並由使用者實測 `/menu`。

搬遷應保留 Local Bot API 資料卷，並依 Telegram 官方流程完成舊實例的
交接。同一個 Bot 同時登入多套 Local Bot API 會讓更新接收不可靠；
不要只因舊服務容器名稱不同就認為它們不會衝突。

## TikTok catalog 搬遷後瀏覽器無法啟動

`TIKTOK_BROWSER_START_FAILED` 發生在一般 Chromium 啟動階段，須與 VPN、
TikTok HTTP 錯誤分開檢查。profile 複製後可能留下指向舊容器 hostname／PID
的 `SingletonLock`、`SingletonSocket`、`SingletonCookie` 符號連結。
一般 Chromium 會拒絕使用被判定由另一台主機占用的 profile。

先停止 catalog 與所有共用該 profile 的登入容器，確認沒有瀏覽器 writer，
以相同的一般 Chromium 模式擷取錯誤；headless 模式成功不足以排除此問題。
只有確認是失效的 singleton 鎖後，才備份並移除這三個鎖定連結。
若用臨時容器驗證同一 profile，一般 Chromium 也會建立指向臨時容器的鎖；
測試程序全部停止後須再次確認並清理失效鎖，才能讓正式容器接手。
保留 cookies、`.cookie-version`、`Default/` 及其餘登入資料；不要刪除整個 profile。
重新啟動後，確認 catalog 各帳號的 failures 歸零、lastSuccess 更新及容器健康，
而不只是確認 VPN 容器健康。

## Cookie 版本相同仍可能失去登入狀態

只搬移專案目錄，不會搬移 Docker named volume 裡的 Chromium profile。
另外，匯入的 session cookies 可能在瀏覽器關閉後消失；`.cookie-version`
相同僅代表來源檔案沒改變，不能證明瀏覽器仍持有登入 cookies。
此問題可造成個人資料及限時動態成功，貼文 API 卻回傳 HTTP 200 空內容。

啟動時會檢查瀏覽器實際 cookies：來源版本相同且沒有登入 cookie 時，
只補入來源中缺少的名稱，保留瀏覽器更新的裝置 tokens。若已有任何受支援
的登入 cookie，則保留人工登入的整組 session，避免混入舊帳號憑證。
來源檔案版本改變時仍依原流程重新匯入。Cookie 存在不等於伺服器接受登入；
部署驗證須確認各項目的 `lastSuccess` 晚於部署時間，且
`consecutiveFailures` 歸零，不可只依賴容器的健康燈。

## Telegram 按鈕延遲

NAS 上曾量到 7 KB 設定檔的單次 fsync 原子寫入約 137–1168 ms，
同時本地 Bot API `getMe` 暖機後約 3–5 ms。這不能代表每個需要連線
Telegram 的傳送方法也同樣快，但證明同步磁碟寫入會明顯阻塞控制器。

健康檔使用 15 秒 heartbeat，避免媒體派送迴圈每秒額外 fsync。
共用 API 排程只授予當下可用時段，不讓多個媒體工作預約數秒後的時段；
按鈕確認與選單回覆優先，同時保留每聊天約 1100 ms、全域 40 ms 的
排程間隔與 Telegram 回傳的 429 冷卻。這不是精確 HTTP 起送時間保證。
按鈕確認可安全重放，其刪除可併入下一筆選單回覆的 checkpoint；
一般訊息與選單編輯完成後仍立即保存狀態，不合併延後其耐久寫入。

`TELEGRAM_REPLY_SENT` 僅記錄方法、queueMs、elapsedMs，不包含訊息、
callback 資料或 token。queueMs 從控制器產生回覆起算，elapsedMs 包含
API 排程等待及回覆完成後的 checkpoint；兩者均不涵蓋使用者點擊至
Telegram 把更新交給控制器之前的網路時間，不能當成端到端延遲。

## 2026-11-18 catalog 維護補充

部署前執行 `./igctl preflight`；建置快取、相依服務 hash 漂移時的無中斷套用、profile 排他鎖及回復程序見 [catalog 可靠性紀錄](tiktok-catalog-reliability.md)。本次沒有修改 NAS 私有環境變數或放寬健康檢查。
