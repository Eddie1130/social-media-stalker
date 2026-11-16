# NAS I/O 量測與 Chromium 快取

## 校正後量測

在 NAS 專案目錄執行（需讀取 root 程序及 Docker 日誌目錄的權限）：

```sh
sudo python3 scripts/measure-nas-io.py --interval 10 --samples 60
```

工具只讀取 `/proc` 計數與 Docker 檔案 metadata，不讀取日誌內容、環境變數或 cookies。
使用 monotonic 實際時間換算 KiB/s；PID 與 starttime 一起辨識，新程序第一筆不計入差值。
讀完程序資料再核對 starttime，跳過取樣期間被替換的 PID。
無法讀取的程序／目錄會回報數量。部署移除容器時，日誌目錄消失不會中止取樣。

- `disks`：各裝置實體／區塊層計數；不要把 sata、partition、md、dm 各層相加。RAID 成員也各自計算。
- `processCountersNotAdditive`：定位線索。包含已回收子程序，不能相加，也不代表特定磁碟的寫入；短命程序可能漏掉。
- `changedLogFiles`：日誌檔 inode、大小或 mtime 改變。`growthBytes=0` 仍可能有資料庫覆寫；不是實體寫入位元組數。
- `changedMetadataFiles`：Docker config.v2.json／hostconfig.json metadata 改變，便於識別日誌之外的管理寫入。
- `swapInPages`／`swapOutPages`：期間實際換頁；累積 swap 使用量本身不代表正在換頁。

避開建置、部署及大量匯出取基準。前後比較應包含完整輪詢週期，並配合下載量與服務健康狀態；短測不能當成固定節省比例。

## 快取變更

`compose.watch.yml` 的 ig-watch 與 `compose.tiktok.yml` 的 tiktok-catalog
將 Default/Cache、Code Cache、GPUCache、Dawn caches 及 profile 根目錄 shader caches 掛成有上限的 tmpfs。
IG 的 `/tmp` 亦改為 128 MiB tmpfs，避免 Chromium 的 shared-memory fallback 寫入容器可寫層。
TikTok 原有 `/tmp` 256 MiB tmpfs 保留。

Cookies、Local Storage、Session Storage、History 及整個 profile volume 保持持久化。
原磁碟快取只是被掛載遮蔽，沒有刪除。tmpfs 按實際使用量耗用 RAM，上限不預先保留記憶體；記憶體壓力下仍可能 swap，須一起監測。

NAS Compose 處理 `network_mode: service:tiktok-vpn` 時，不要以 `--no-deps` 單獨重建 tiktok-catalog；
使用 `./igctl up -d tiktok-catalog`，並核對相依容器是否被重建。此變更不需重新建置映像。

回復方式：移除本次新增的 tmpfs 項目後重新建立受影響服務。保留原先 TikTok `/tmp` 掛載。

## 2026-11-16 NAS 驗證紀錄

部署基底為 `c3ddf2b`，加上本次尚未提交的 Compose／量測工具變更。
本機與 NAS 檔案同步；NAS 原有 `__MACOSX/`、`social-media-stalker/` 未追蹤目錄保留。
僅重建 ig-watch、tiktok-catalog；Compose 相依解析另觸發 ig-telegram 重建。
三個容器最終均 healthy，TikTok 16 個串流失敗數為 0、manualRequired=false；
IG 日誌有成功完成 catalog 查詢及媒體封存。

| 短測指標 | 修改前約 61 秒 | 修改後約 122 秒 |
|---|---:|---:|
| sata1 寫入 KiB/s | 5591 | 3555 |
| sata1 寫入 IOPS | 254 | 202 |
| sata1 平均各區間 write await ms | 20.04 | 14.27 |
| sata2 寫入 KiB/s | 5591 | 3551 |
| sata2 平均各區間 write await ms | 29.89 | 30.57 |
| dockerd 程序計數 KiB/s（不可加總） | 703 | 710 |
| swap out pages | 0 | 106 |

這是不同時間窗的觀察值，不是同一工作量的對照實驗；IG 同時有媒體封存待辦。
不能宣稱整體減少約 36% 的寫入全部來自快取變更。dockerd 計數沒有明顯下降，
符合本次只移動 Chromium 快取、未修改 Docker 管理行為的範圍。

Docker 來源定位另外以 15 秒、每 100 ms 讀 `/proc/17099/task/*/syscall`
及對應 fd 路徑，部署後仍觀察到：

- 容器 `.tmp-config.v2.json`、`.tmp-hostconfig.json` 的 fsync。
- 其他專案 tiktok-recorder 的 `log.db`／`log.db-journal` fsync。
- 兩個既有 performance-observer 的日誌資料庫同步。

這些是阻塞 syscall 的取樣命中，不是呼叫次數或位元組占比；不能據此推算百分比。
兩個 VPN 容器 healthcheck interval 都是 5 秒，它們的設定 metadata 持續變動；
這是後續調整檢查頻率的候選原因，尚未以關閉檢查的對照試驗證實。
沒有更改其他專案、關閉 healthcheck、清除日誌或修改 Docker daemon 設定。

驗證：Compose config --quiet、量測工具 4 項 unittest、程式審查、實際 tmpfs 掛載與容器健康檢查。

## VPN 健康檢查頻率對照試驗

本專案的 tiktok-vpn 僅覆寫 Docker healthcheck interval 為 30 秒，
保留現有映像的 Test、5 秒 Timeout、10 秒 StartPeriod、3 次 Retries。
另一個專案的 surfshark-vpn 保持 5 秒，作為設定檔更新頻率的對照。
Docker 健康狀態對連續失敗的反應因此可能延後；沒有改動 Gluetun 內部連線監控、
防火牆、VPN 認證或復原設定。

NAS Docker 為 24.0.2，Compose 為 2.20.1-6047-g6817716。
該版 [Docker health.go](https://github.com/moby/moby/blob/v24.0.2/daemon/health.go)
在每次 probe 結束呼叫 CheckpointTo，提供頻繁檢查導致 metadata 寫入的實作依據。
[Gluetun 文件](https://github.com/qdm12/gluetun-wiki/blob/main/faq/healthcheck.md)
說明 Docker healthcheck 與內部監控分開運作。

實驗使用現有映像，不 pull、不 build；重建 VPN 及共用 namespace 的
resolver、watch、catalog，然後核對它們連到新 VPN 容器 ID。
部署期間排除在量測時間窗之外。診斷容器使用 `--log-driver none`，
輸出經 SSH 存到開發機，不另在 NAS 留存診斷日誌資料庫。

保留 15 分鐘修改前與 15 分鐘修改後的計數，並追蹤各容器網路接收量作為工作量線索；
網路量包含 API／HTML／媒體，不能當作精確媒體下載量。
另以 1 秒間隔讀設定檔 inode／mtime 60 秒，估計更新頻率；
它是觀察次數下限，不是 fsync 次數或實體寫入量。

兩個 performance-observer 使用相同腳本、相同 60 秒間隔，皆為 24 小時限時且不自動重啟。
完成主要對照後，停止較舊的 20261115 容器，保留容器及日誌，並保留 20261116 一份繼續觀察。
這項清理不混入主要 healthcheck 前後比較。

### 重建 VPN 時的 Chromium 舊鎖定

本次重建後，catalog 曾回報 `TIKTOK_BROWSER_START_FAILED`。
共用 VPN namespace 的 hostname 已改變，但持久 profile 的 SingletonLock
仍指向已移除的舊 VPN hostname；不是重新登入要求。
初次後測因此作廢，保留為 startup-invalid 紀錄，不納入效能比較。

恢復時先確認沒有 tiktok-login 或其他運行容器使用同一 profile volume，
停止 catalog、確認舊 VPN 不存在，再將三個 symlink 的目標備份至
`/tmp/stalker-healthcheck-20261116/stale-profile-links.json`，只移除已驗證的
SingletonLock、SingletonCookie、SingletonSocket symlink。沒有刪除 symlink 指向的目標，
也沒有修改 Cookies、Local Storage 或 scheduler 狀態。
重新啟動 catalog 後核對新 lock hostname，等待所有串流恢復成功，再重新取完整後測。
不要在瀏覽器或登入容器仍使用 profile 時刪除鎖檔。

### 完整對照結果

基準時間窗約 UTC 10:24:53–10:39:59（906 秒）；有效後測約 10:56:53–11:12:03（910 秒）。
吞吐與利用率以時間加權；write await 以各區間完成的寫入操作數加權。

| 指標 | 5 秒基準 | 30 秒後測 |
|---|---:|---:|
| dockerd 程序寫入計數 KiB/s（不可加總） | 536.71 | 424.59 |
| sata1 寫入 KiB/s | 3792.11 | 4194.26 |
| sata1 寫入 IOPS | 167.79 | 177.68 |
| sata1 write await ms | 32.90 | 57.00 |
| sata2 寫入 KiB/s | 3792.11 | 4194.25 |
| sata2 write await ms | 34.65 | 44.36 |
| swap out pages | 5414 | 8250 |
| 本專案 VPN 每份設定檔更新觀察次數／60 秒 | 8 | 2 |
| 未調整的另一個 VPN 同項觀察次數／60 秒 | 8 | 9 |

本專案設定檔更新觀察次數減少 75%，dockerd 寫入計數觀察值減少約 21%。
整機磁碟寫入及延遲沒有同步改善，不能宣稱全機效能已變快。
鄰近時間窗的 TikTok VPN eth0 接收速率約由 26.42 增至 43.19 MiB/min，
IG 約由 0.45 增至 0.90 MiB/min；兩個網路計數時間窗分別約 861 與 970 秒，
並非與磁碟取樣完全對齊，且包含 API／HTML／媒體與 VPN 封裝，僅作工作量線索。
因此不將整機磁碟差異歸因於健康檢查頻率。

觀察容器的分鐘紀錄顯示，基準期間本來也有零星串流錯誤；後測曾有單一 post 串流
`TIKTOK_NETWORK_FAILED`，之後正常重試恢復。它與舊 hostname 的啟動鎖定問題不同。
沒有清除 scheduler 失敗計數或改寫健康狀態來讓檢查通過。

主對照結束後，20261115 的重複觀察容器已停止（restart policy=no），
容器及 log.db 保留；20261116 的一份仍運行。這項清理不納入上表的前後比較。

原始計數、摘要與排除的啟動資料存於
`data/performance/healthcheck-20261116T1024Z/`（Git 忽略的診斷產物），明確區分有效與排除資料。

最終核對：VPN、TikTok watch/catalog、IG watch/Telegram 皆 healthy；resolver /health HTTP 200；
TikTok 16 個串流失敗數為 0，manualRequired=false。
四個 TikTok 服務映像 ID 與部署前相同，resolver/watch/catalog 的 NetworkMode 全部指向新 VPN ID。
Compose config 驗證通過；其他專案的 VPN 仍為原 5 秒設定。
