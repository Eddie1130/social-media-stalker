# TikTok catalog 可靠性修復（2026-11-18）

## 已確認原因與界線

- NAS Docker 24／Compose 2.20.1，x86_64、4 CPU、MemTotal 6056730624；Docker 明確警告沒有 CPU CFS quota／period。非零 `cpus` 會造成 NanoCPUs 建立失敗；目前 NAS catalog NanoCpus=0，RAM 限制 6056730624，不據此加大資源。
- 抵達時 catalog 已 exited(0)，FinishedAt=2026-11-17T12:44:31Z、RestartCount=0、OOMKilled=false，restart=unless-stopped。不能據此認定是 OOM 或 crash loop；停止來源仍未知，Docker 事件不保留完整歷史。
- 故障注入證實：browser worker 先退出但孫程序忽略 SIGTERM 時，舊程式只等待 leader，不會 SIGKILL 剩餘 group；孫程序持有 stdout，reader thread 使 close 永久等待。修正為關閉 pipe 前清除整組並 reap。此缺陷可重現，尚無足夠歷史記錄證明每次 transport failure 都由它造成。
- profile 留有 Singleton symlink；部署前 catalog 已停，沒有運行容器掛載此 volume，且全主機沒有相同 user-data-dir 的 Chromium，才備份目標並移除三個連結。沒有刪除連結目標、cookies 或歷史。新 `.catalog-owner.lock` 使用核心 flock，在 reader／login 之間互斥；程序退出由核心釋放，鎖檔本身不刪除。未知／跨 namespace 的 Chromium 舊鎖仍須人工核實，不自動猜測 owner 已死。
- 過去失敗日誌只含 RuntimeError／frame，無法分辨輸送、403、空回應、CAPTCHA。現在記錄既有 classifier 的 `failureCode`／`failureCategory`、子程序例外類型與來源位置，不記錄原例外內容、URL、cookies、payload。登入／CAPTCHA 保留原保護，不自動繞過。
- NAS 有約 20861444 KiB 的匯入重複目錄 `social-media-stalker/`，以及 macOS metadata；原 `.dockerignore` 未排除。新增排除後 legacy build context 約 1.464 MB。
- 既有映像為 legacy builder 層；本次 BuildKit 未命中 apt cache。apt 索引下載約 3 秒、138 MB 套件下載約 3 秒，解包卻逐件耗時；同期 NAS load 42.05（IO 41.65、CPU 0.40）、MemAvailable 約 2.7 GB。顯示本次受 I/O 阻塞，不能把歷史 2500 秒全部歸因網路或 OOM。切回相同 legacy builder 後 apt、pip、Playwright、WORKDIR 均顯示 Using cache。不要 prune cache 或使用 --no-cache。

- 受控 stop 曾超過 45 秒而 exit=137（OOM=false）。原 Compose 的 45 秒小於既有 ffprobe 的 60 秒等待上限，另需 browser reap／checkpoint，這是可由程式及 AST 回歸測試確認的停止預算缺陷。改為 2m；未放寬 healthcheck／query timeout。那次具體阻塞點仍未知，嚴重 kernel I/O 阻塞亦可能超出 2m。

- 本輪線上 `quick_check`／資料比對暴露直接 SQLite 故障：讀鎖延遲讓 poll 的 commit 在預設五秒等待後回報 `database is locked`，錯誤處理再次 commit 失敗，主程序 exit=1。22:24:49 的 exec_die=137 與 22:24:51 的 container die=1 對應；不是 OOM 證據。這是本次診斷觸發的可重現故障，不能推論所有歷史退出原因相同。
- 原錯誤處理也可能把已回滾頁面的新 cursor／baseline／profileHash 寫入錯誤紀錄。測試重現 items=0、cursor=20；現改為先 rollback、SQLite 例外交 owner、一般錯誤使用原 state。BUSY／LOCKED 以 1–30 秒可取消退避；非 busy DB 錯誤明確上拋。manual／repair／refresh 不消耗業務次數；完成 future 保留可重播，manual writer 未結束前 guard 不釋放。新增 storageBlocked 健康欄位，沒有掩蓋讀寫阻塞。

## 部署

先核對 Git／逐檔雜湊、備份並讀回驗證 SQLite、`.required`、完整 profile、設定及待辦；保留舊映像 tag。備份含私人資料，權限必須限制。不要還原較舊通知收據來回退程式。

```sh
cd /volume1/docker/social-media-stalker
export PATH=/usr/local/bin:/usr/bin:/bin:$PATH
git status --short
git rev-parse HEAD
./igctl preflight
./igctl config --quiet
./igctl config --hash tiktok-vpn
docker inspect social-media-stalker-tiktok-vpn-1 --format '{{index .Config.Labels "com.docker.compose.config-hash"}}'
```

`preflight` 是整個專案的唯讀設定／CPU 相容檢查，會拒絕任何已宣告的非零 quota；不是僅檢查選取服務。自訂環境例如 `./igctl preflight --env-file custom.env`，部署也須使用同一 `--env-file`。目前沒有新增環境變數。

VPN config hash 必須相同；若不同，先釐清差異，檢查所有共用 namespace 的 LIVE／resolver／catalog。錄影或上傳活動中不得重建 VPN；需要中斷時先取得使用者同意。Compose 2.20 沒有可靠 dry run，hash 相同仍需核對相依服務與映像。

僅程式改動，依賴未變時：

```sh
# 此 NAS 既有快取是 legacy builder；不要與 BuildKit 輪流切換。
DOCKER_BUILDKIT=0 ./igctl build tiktok-catalog
# 不需建置時略過上一行。此步是容器套用，與 image build 不同。
./igctl up -d --no-build tiktok-vpn tiktok-catalog
./igctl ps -a
```

若相依服務 hash 漂移（本次 ig-telegram 即如此），上面的普通 up 可能連帶重建相依服務。先保存 catalog inspect／logs，確認只停止 catalog，再執行：

```sh
./igctl stop tiktok-catalog
./igctl rm -f tiktok-catalog  # 不加 -v；只移除已停止的容器
./igctl up -d --no-build --no-recreate tiktok-vpn tiktok-catalog
```

`--no-recreate` 保留所有既有相依容器；因 catalog 已移除，仍會用新映像建立。若要修改 VPN 設定，此模式不會套用 VPN 變更，必須另排維護窗口。

不要使用 catalog `--no-deps`；launcher 會拒絕。不要全專案 force-recreate。正常 source COPY 在依賴層之後，無需重新下載 apt／Python／Chromium；確認 build output 的快取命中。依賴更新須刻意排程完整建置；gallery-dl／Playwright 版本已固定，Python base tag／apt／transitive dependencies 尚非完全不可變鎖定。

## 驗證及排障

```sh
./igctl logs --since 15m --tail 100 tiktok-catalog
docker inspect social-media-stalker-tiktok-catalog-1 --format 'state={{json .State}} restart={{.RestartCount}} image={{.Image}}'
docker stats --no-stream social-media-stalker-tiktok-catalog-1
./igctl exec -T tiktok-catalog python -c 'import sqlite3; s=sqlite3.connect("file:/app/state/tiktok/catalog/catalog.sqlite?mode=ro",uri=True); b=sqlite3.connect(":memory:"); s.backup(b,pages=64,sleep=.05); s.close(); print(b.execute("pragma quick_check").fetchall())'
./igctl restart tiktok-catalog
```

完整性檢查對線上 backup 快照執行，勿在正式 DB 長時間持有讀交易做 full scan；先確認有足夠 RAM 放入快照。

最後一行是有計畫的 catalog 重啟測試，先核對未在處理重要手動工作；不重啟 VPN／LIVE。隨後等待輪詢及退避週期，核對每條 stream 的 `lastSuccess` 前進、pending 被處理、manualRequired=false、無新增重複通知及其他服務正常。健康檢查仍保留原有功能失敗條件，沒有放寬。

失敗分類依序區分 build／Compose／start、Chromium 初始化／IPC、OOM／exit、health heartbeat、查詢／HTTP／驗證、SQLite／磁碟；403 不等於 CAPTCHA，200 空內容不等於成功。`unhealthy` 不會觸發 Docker restart policy；`unless-stopped` 也不會自動恢復被停止的容器。不要靠持續重啟掩蓋平台驗證或磁碟故障。

24 小時觀測應每分鐘保存去識別化摘要：容器 ID／image、RestartCount、State／OOM、health age、manualRequired、各串流 lastSuccess／consecutiveFailures／reason、pending／unresolved、媒體完成數與磁碟延遲。至少涵蓋一次正常重啟及完整退避週期；持續傳輸失敗、lastSuccess 長時間不前進、pending 無進展須檢查。不可把每分鐘快照宣稱為精確 Docker 故障次數，也不可在觀察不足 24 小時時宣稱穩定性驗收通過。

## 回復

本次備份：`data/backups/catalog-reliability-20261118/`，舊映像 tag：`social-media-stalker-tiktok-catalog:before-reliability-20261118`。停止 catalog 後還原 `source-before.tgz` 的程式（先檢查後續變更），以舊映像重新標記 `social-media-stalker-tiktok-catalog:latest`，用上面的 `up --no-build` 套用。**不要還原 state-profile.tgz** 作一般程式回退，避免丟失新增任務／通知收據。持久狀態還原僅在證實損壞、停止相關 writer 並逐項比對後進行。

## 本次實測

本機 398 項 Node、Python 共 201 項（198 通過、3 跳過）；macOS 對已退出群組的訊號權限限制，使 crash/restart 案例需在 Linux catalog image 執行，該案例在 NAS 通過。兩項本機跳過案例需 pinned gallery-dl；未冒稱本機已執行。

第一版 `2628d465278a` 於 21:53 HKT 建立；一度自動重啟 1 次，原因仍未確定。22:01 左右取得正式快照：16/16 串流 lastSuccess 晚於部署、連敗歸零、manualRequired=false，pending 1→0；SQLite quick_check=ok。原 ready 2970／unresolved 1 保留。原日誌沒有充分底層診斷，不能將那次重啟指定為 OOM、browser 或 heartbeat 所致。

受控停止於 22:06:03 exit=0、非 OOM，之後重建 `388966c2c603` 成功；下一次以舊 45 秒預算停止時 exit=137、非 OOM，已保留為失敗紀錄並修正預算。新補 heartbeat 失敗記錄／非零退出與 broken-log-pipe 保護；磁碟滿及管線故障測試通過。中間映像 `12a363ce4d5f` 的 Linux 6 項生命週期、7 項 recovery／heartbeat 測試通過；先前核心映像另有 scheduler 10 項、catalog 62 項與真實 Chromium 離線重啟測試通過。此後確認 SQLite 根因，再建置 `8281505aa598`；部署觀測另於完成後補記。

NAS 原 Git HEAD `bb7e581` 加本次明列來源檔；原 X／changelog 修改保留。VPN、LIVE、Telegram 容器 ID 不變。沒有變更通知派送邏輯；尚無人工 Telegram 端到端防重送驗收，不能宣稱完全排除重複通知。

catalog Docker events 已於 22:08 啟動；原 host sampler 因權限 readError 已停止，改用唯讀 Docker sampler（observe-root-24h.jsonl），PID／摘要／錯誤／結束碼在同一備份目錄。兩者用 timeout 86400 自行結束；sampler 只包含聚合健康與無帳號名稱的 stream 摘要，events 限定本專案 catalog。觀察尚未滿 24 小時。

不把離線測試等同正式登入、VPN 或 Telegram 端到端測試。

24 小時摘要必須能讀取 root 擁有的健康檔。一般 NAS 帳號執行 host Python 可能只得到 readError；使用現有映像及唯讀掛載：

```sh
umask 077
timeout 86400 docker run --rm --init --network none --log-driver none \
  -v "$PWD/scripts/collect-nas-performance.py:/observer.py:ro" \
  -v "$PWD/data/watch:/state:ro" -v "$PWD/data/control:/control:ro" \
  --entrypoint python social-media-stalker-tiktok-catalog:latest \
  /observer.py --root / --interval 60 > data/backups/catalog-reliability-20261118/observe-root-24h.jsonl
```

這只讀健康檔，不啟動第二份 bot／worker。執行前確認沒有同用途的觀測程序，啟動後必須核對 readError=false、樣本時間前進；觀測容器沒有 restart policy，24 小時後 timeout 會結束它。可用 nohup 包裝整段命令避免 SSH 中斷。


資料比對曾確認：訂閱完全相同、原 2971 筆資料零遺失、現 2972 筆、quick_check=ok、required=true。NAS 原有 X diff 與備份完全相同。更早是否已有漏頁無充分歷史證據，本次不盲目重設 cursor 或收據。

## SQLite 修正版驗證

`8281505aa598` 的 NAS 隔離測試：43 項 catalog 系列、62 項業務測試、真實 Chromium 啟動／停止／重啟／cookie 還原全部通過。13 項 SQLite 回歸包括 7 秒真實讀鎖（超過預設五秒等待）、錯誤提交不前進 cursor、既有 pending 保留、手動任務不消耗業務嘗試次數、不可恢復 DB 錯誤不吞。

正式服務做 50 秒只讀鎖故障注入：30 秒時 storageBlocked=true，鎖釋放後 healthy；`live-lock.before`／`live-lock.after` 的容器 ID、StartedAt、RestartCount 完全相同（RestartCount=0）。此測試沒有寫入資料或停止 VPN／LIVE／Telegram。詳情在備份目錄 live-lock.log／exit，沒有把任意空回應當成功。

`collect-nas-performance.py` 的去識別化白名單新增 storageBlocked，避免 24 小時摘要漏報本地儲存阻塞；不增加帳號／URL／憑證欄位。

## 本次修改檔案

| 檔案 | 變更 |
|---|---|
| `.dockerignore` | 排除 NAS 匯入副本及 macOS metadata |
| `Dockerfile.tiktok-catalog` | 包入共享 profile lease 模組，保留依賴 cache 層 |
| `compose.tiktok.yml` | catalog 停止預算 2m；healthcheck 納入 storageBlocked |
| `igctl` | 唯讀 CPU／Compose preflight，攔截 catalog up --no-deps |
| `tiktok/catalog_profile.py` | reader／login 共用 flock |
| `tiktok/catalog_browser.py` | profile 排他與清理例外後釋放 lease |
| `tiktok/catalog_regular_browser.py` | 普通 Chromium profile 排他與清理保護 |
| `tiktok/catalog_login.py` | 人工登入持有同一 lease |
| `tiktok/catalog_query.py` | 清除剩餘程序群組、pump 失敗取消在途查詢、傳遞診斷 |
| `tiktok/catalog_browser_worker.py` | IPC 回傳安全例外類型／位置 |
| `tiktok/catalog_errors.py` | SQLite busy 分類與不含訊息的診斷 |
| `tiktok/catalog_worker.py` | owner DB 退避、交易 state 保護、業務重試隔離、heartbeat 錯誤與儲存健康 |
| `tiktok/catalog_scheduler.py` | refresh DB 例外上拋；manual writer 完成前不釋放 guard |
| `scripts/collect-nas-performance.py` | 私密摘要保留 storageBlocked |
| `test/test_catalog_lifecycle.py` | 孤兒程序、worker crash／pump 取消、profile lease／cache 選路回歸 |
| `test/runtime_catalog_cache.py` | 真 Chromium hard cache 容量、80MiB 本機假流量與 cookie 重啟測試 |
| `test/test_catalog_sqlite.py` | 真 SQLite 鎖／提交失敗／cursor／pending／manual 預算與 writer 隔離 |
| `test/test_catalog_recovery.py` | 安全診斷、heartbeat 磁碟／日誌管線失敗 |
| `test/test_igctl_preflight.py` | CPU、env-file、no-deps、停止預算回歸 |
| `test/test_catalog_metrics.py` | storageBlocked 觀測欄位與隱私 |
| `test/test_tiktok_catalog.py` | 原有安全日誌新增分類欄位斷言 |
| `CLAUDE.md` | 維護規則與部署指南入口 |
| `CHANGELOG.md` | 本次原因、修正及實測結果 |
| `docs/tiktok-catalog-reliability.md` | 本報告、部署、觀測及回復 |
| `docs/nas-operations.md` | 連結更新後的 NAS 流程 |
| `docs/nas-io-tuning.md` | 修正 catalog 套用指令與相依 hash 檢查 |
| `docs/tiktok-integration.md` | profile 互斥、診斷與維護說明 |

本機原有 `.gitignore` 修改與 NAS 原有 X 修改不屬於本次變更，均保留。沒有修改私有環境檔、cookies 或訂閱設定，也沒有資料庫 schema／journal mode 遷移。

## HTTP cache 實體上限

正式量測 `/tmp` 已用約 228/256MB；可見檔案約 200MB，最大目錄為 browser scratch 內 `tiktok-catalog-cache-*/Default/Cache/Cache_Data`，後續量到約 221MB。`--disk-cache-dir` 的臨時 root 繞過已存在的 profile cache tmpfs，`--disk-cache-size=33554432` 沒有提供實體配置的硬上限。這是確認的資源配置缺口；未證明每次歷史 browser transport 故障皆由此造成。

當 profile 的 Default/Cache 與 Default/Code Cache 都是掛載點時，普通 transport 使用該 profile 作 cache root；此 NAS 的 Compose 為兩者各設 32MiB tmpfs，所以容量由掛載強制限制。沒有增大 RAM 或 `/tmp`，Cookies／Session／Local Storage 仍在原 profile volume；不刪除被掛載遮蔽的舊快取。沒有這些掛載的 standalone 工具沿用臨時目錄 fallback，不能宣稱任意 mount 都有相同容量。

新增 `test/runtime_catalog_cache.py`：只用無網路容器的 localhost 假資料及 ephemeral profile，舊映像已在實際 Chrome 起動路徑重現 cache 繞過上限（exit=1）。後測驗證 80MiB mock HTTP traffic、32MiB 硬掛載、`/tmp` 增量及 profile cookie 跨 restart 保存；沒有對 TikTok 解除讀取 guard 或 bypass 驗證。

## 貼文回應診斷（11 月 19 日）

診斷映像以正式基底 8281505aa598 建置，標籤為 social-media-stalker-tiktok-catalog:post-response-diag。套用此版時在 igctl 的 up／config 前加入 `-f data/backups/catalog-reliability-20261118/post-diag/compose.yml`；rollback.yml 固定原正式映像。先依上方步驟檢查相依設定及備份，僅替換 catalog。

在最終輪詢失敗日誌查看 browserDiagnostic.postResponse。stage=provider_empty 且 readBytes=0 表示瀏覽器完成讀取時已有零位元組；readBytes>0 時，請比對 providerChars（空白及 UTF-8 BOM 也可能被消去）。stage=read 表示已取得 headers 但本文讀取失敗。declaredBytes=null 表示沒有可用長度，壓縮也會令宣告長度與解碼後實讀長度不同。診斷僅反映瀏覽器看到的回應，無法據此歸責源站或 VPN；成功重試不產生最終失敗日誌。沒有新增環境變數。

## 匿名公開貼文查詢（2026-11-20）

TIKTOK_CATALOG_ANONYMOUS_POSTS 預設 1：post（含單篇查詢）使用同一 Chromium 的獨立、非持久匿名 context，不載入帳號 Cookie；Story／轉發／profile／like 仍使用原持久登入 context。匿名 context 在 browser worker 重啟後重建，SQLite 游標與工作不變。設為 0 並重建 catalog 容器即可回復登入貼文查詢；無需還原資料庫或 profile。匿名方式不保證能讀私密貼文，失敗仍保留進度，不自動嘗試登入以規避存取限制。

NAS 對單一公開帳號四個空 Cookie context 測試皆取得有效清單，正式 guard 下第一、二頁各 20 筆且無重複。這是短期測試，尚非 24 小時穩定性證明，也未證實所有歷史錯誤皆由登入造成。

## 貼文空本文復發時

以 `failureCode` 和診斷階段判斷故障。若 `postResponse` 同時記錄 `status=200`、`declaredBytes=0`、`readBytes=0`，表示貼文清單確實收到空本文。合法空清單仍應有可解析的回應結構。個人頁主文件 HTTP 403、頁面嵌入 JSON 解析錯誤和 `TIKTOK_BROWSER_START_FAILED` 都發生在清單取得之前，應各自排查。保留既有游標、首頁基線和通知收據。

noVNC 顯示的是 Chromium 的 TikTok 網頁。Catalog 為避免重複送出貼文清單請求，會攔截網頁自身的清單請求，該頁可因此顯示 `Something went wrong`。判斷 Catalog 是否收到貼文時，應核對 Catalog 送出的清單請求之 HTTP 狀態、本文大小與 `itemList` 筆數，以及該帳號的 `lastSuccess` 是否前進。

1. 核對 VPN 的最新出口、Catalog 心跳與各帳號的 `lastSuccess`。單次錯誤先讓既有退避排程重試。現行 Catalog 已攔截頁面順帶送出的貼文清單請求，空本文也不會在同一輪立即重送。
2. 多條貼文串流持續收到空本文時，可使用同一映像、同一帳號與相同匿名設定，從兩個隔離的 VPN 出口各發一次唯讀查詢。2026-11-21 的同步對照中，`al-tia.prod.surfshark.com`（出口 `172.216.14.22`）回傳 0 bytes，`kr-seo.prod.surfshark.com`（出口 `61.97.243.106`）回傳 20 筆有效項目。結果只代表當次的兩個出口。
3. 有有效的替代出口時，先確認 LIVE 沒有錄影，再套用 VPN 設定。等新 VPN 啟動並核對出口 IP，再確認 Catalog、LIVE 和 resolver 各自連到新 VPN 容器。保留原 Chromium profile 和 Cookie 匯入設定，以便分辨出口切換的效果。若 Chromium 因舊 hostname 的鎖無法啟動，先停止 Catalog 和手動登入容器，驗證沒有程序使用該 profile，備份並隔離已核實的殘留 Singleton 連結；保留 profile 內的 cookies 和其他資料。新版本正常關閉時會清理已核實屬於自己且已退出的 Chromium 鎖。
4. 按帳號核對 `lastSuccess` 是否前進，並確認後續正常輪詢也成功。若要對照請求頻率，固定出口、profile 與訂閱名單，並避開歷史補抓。若要對照訂閱數，維持原有輪詢設定。公開嵌入頁只作影片補查線索，單篇確認作者與發布時間後才能判定是否新發布。

2026-11-21 在同一首爾出口 `84.233.167.72` 的五帳號觀測中，降速與恢復原速各自最初約 15 分鐘分別成功 5 次和 14 次，兩段都沒有空本文。恢復原速後觀測逾一小時，合計成功 63 次，兩次空本文都在同一出口的下一次排程重試恢復，分別耗時約 57 秒和 55 秒。兩段等長樣本都沒有失敗，無法判定降速是否降低空回應機率。

降速對照用 `TIKTOK_CATALOG_POST_REQUEST_GAP_SECONDS=120`，從一次排程貼文查詢結束起，全帳號至少等兩分鐘才開始下一次。五個帳號各約每十分鐘或稍久輪詢一次。這個限制也涵蓋貼文分頁和重試。`TIKTOK_CATALOG_POST_POLL_TEST_SECONDS` 維持 `0`；將間隔設為 `0` 可恢復原有排程。
