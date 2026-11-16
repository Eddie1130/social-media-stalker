# 媒體下載部署前後比較（2026-11-16）

比較基準：NAS 10:24–10:28 HKT 部署的 `5cbc047`。已核對 NAS `source-before.tar` 的舊原始碼，不只依 Git 父提交推論。正式環境沒有回滾或重播下載。

| 類型 | 部署前 | 部署後 | 判讀 |
|---|---|---|---|
| IG 貼文／精選 | 固定 3 工；15 秒批次；每件同步保存狀態 | 背壓控制 1–3 工，目前 1；15 秒批次保留；每件 await 合併保存，預設等 1000 ms | 降低並行且新增逐件計時等待，存在降低吞吐的機制；沒有部署前逐件耗時，不能量化實際下降百分比 |
| IG Stories | 固定 3 工；15 秒批次 | 背壓控制 1–3 工；同樣 15 秒批次 | 受並行降低影響，沒有 catalog 的 1000 ms 合併等待 |
| X 背景封存 | 固定 3 工；15 秒批次；工作迴圈預設 5 秒 | 背壓控制 1–3 工，目前 1；其餘限制保留 | 並行容量下降；目前 pending=0，缺少部署前下載耗時，不能證明實際慢幾倍 |
| TikTok 內容封存 | 完成各串流查詢後才 drain；固定 3 工、15 秒派工窗口；每輪等 5 秒 | coordinator 持續補入工作；瀏覽器 IPC 等待也 pump；1–3 工，目前 1；每輪等 0.25 秒 | 實際佇列從停滯恢復並清空；不能只按並行數宣稱變慢 |
| IG 手動下載／TikTok LIVE 錄影 | 既有下載／錄影路徑 | 該提交未修改這些核心路徑 | 沒有新增上述背壓及 IG 合併等待；未作吞吐對照，仍可能受共用資源影響 |

IG 約五分鐘才重新執行帳號封存的排程在此提交前已存在，不是本次新加入。

## NAS 實際觀測

資料來源：`data/backups/nas-performance-20261115/observer.jsonl` 與 `20261116/observer.jsonl`。兩份 observer 在部署後重疊；以時間戳辨識，沒有將兩份計數相加。

- TikTok 部署前 09:20:45–10:19:45：60 筆觀測全部 pending=653，淨積壓沒有下降。末端健康快照已約 350 秒未更新，因此只能確認觀測到停滯，不能斷言整段沒有任何單件下載。
- TikTok 部署後 10:30:45–11:29:48：pending 624→294，約一小時淨減少 330 件；同一程序媒體成功計數 31→330（299 次），媒體 bytes 129845615→1367143743（增加 1237298128 bytes，約 1.15 GiB）；queue_completed 29→363。工作、媒體檔與淨佇列變化的單位不同，不應混用。
- TikTok 12:19:50 首次觀測 pending=0；最新查詢仍 pending=0、unresolved=1。
- IG 最新已量測時間窗 21:31–21:57：pending 1978→1960，約 41 件／小時；最近圖片開始至保存約 2.8–4.3 秒。部署前 observer 沒有 IG 封存件數或分段耗時，無法直接計算前後速度比。
- X 最新三個帳號 pending 皆為 0；observer 舊欄位不包含 X 媒體成功數及 bytes，無法直接量化前後吞吐。

這是實際生產觀測加程式差異，不是同一批媒體、同一負載的受控 A/B 實驗。可確認 TikTok 積壓改善、IG 新增減速因素及 X 並行容量下降；不可推導所有平台都變慢三倍。

## 下載加速修正與 NAS 驗證（9e2904d）

2026-11-16 HKT 22:25 左右部署；RED 提交 `b10dbf8`，GREEN 提交 `9e2904d`。

- 背壓發布者只消費新 checkpoint 觀測，避免啟動／idle 慢速值永久阻止恢復；event-loop 觀測保留 30 秒有效期，持續延遲與互動積壓仍可降速。
- IG catalog 下載工作不再逐件 await 1000 ms 合併計時器；完成訊號仍在耐久 checkpoint 後發布，批次返回前 flush。
- 有待辦的 IG 帳號約 5 秒後繼續封存，封存輪次跳過 catalog discovery；原 Story／catalog 查詢頻率保留。媒體及 caption 失敗保存 60 秒重試期限，重啟仍遵守。
- TikTok coordinator 保留；共享摘要恢復三工，X／TikTok 不需重啟。僅重啟 ig-telegram、ig-watch。

| 指標 | 修改前 | 修改後 |
|---|---:|---:|
| IG 封存觀測時間 | 20 分鐘 | 182.7 秒，包含第一輪查詢等待 |
| 保存媒體件數 | 18 | 124 |
| 保存 bytes | 4707163 | 33900974 |
| 當下並行上限 | 1 | 3 |
| sata1 write KiB/s | 3155.4（30 秒取樣） | 6327.6（182.7 秒取樣） |
| sata1 write await ms | 25.6 | 13.9 |
| sata2 write await ms | 25.6 | 24.8 |

後測時間 UTC 14:25:38 起約 183 秒；結尾 pendingArchive=1833 是最近完成批次的狀態，包含仍在途下載，不以它倒推精確完成件數。以上件數來自 CATALOG_MEDIA_SAVED。短期、不同工作量與不同取樣長度，不能保證固定加速倍數；更多下載自然增加寫入量，也不能將 write await 差異全歸因於此次修正。

後測無 WATCH_FATAL／WATCH_TARGET_FAILED／CATALOG_ARCHIVE_RETRY；Telegram pollOk、telegramOk、deliveryReady 皆 true、pending=0；X 三帳號 pending=0；TikTok 容器內確認 pending=0、unresolved=1、manualRequired=false。主機取樣程序無權讀取 TikTok health，原始 after.json 的 ttPending=null，另用容器內讀取補驗證，沒有把 null 當成 0。

IG／Telegram／X／TikTok catalog 最終均 healthy，Compose config 通過。本機 396 項 Node 測試及 NAS 隔離無網路容器 52 項相關回歸測試全過；npm audit 0 漏洞；兩輪程式審查完成。未模擬使用者點擊或額外發送測試訊息，不能由健康狀態推論互動端到端延遲。

NAS Git 已快進至 `9e2904d`，四個來源檔與本機 SHA-256 一致，兩端既有未提交修改保留。修改前狀態 patch 及 before.json／after.json 存於 NAS `/tmp/stalker-download-speed-20261116/`，屬短期診斷資料。
