# NAS TikTok catalog 穩定性事實調查（2026-11-17）

本次為唯讀調查，未修改程式、設定、資料庫或重啟服務。調查時本機與 NAS HEAD 均為 `bb7e581`；NAS 原有未追蹤檔案保留。所有時間使用香港時間 UTC+8。

## 可以回答與不能回答的問題

可從既有跨平台觀測資料辨識：TikTok catalog **74 段應用健康異常、74 次觀測恢復**。其中 73 段起訖均落在觀測期內，恢復時間中位數 **2.00 分鐘**、平均 **6.52 分鐘**、最長 **155.02 分鐘**。另一段在觀測開始時已異常，至少持續 **816.20 分鐘（13 小時 36 分）**，不計入上述恢復時間統計。

**這不是 Docker unhealthy 紅燈切換的精確次數，也不是全部歷史故障次數。** 每分鐘快照無法重建全部 Docker 健康檢查、啟動狀態、連續失敗門檻或秒級切換；恢復僅代表下一個樣本已不符合本報告異常條件，不代表有人工修復、重啟或所有內容都已更新。

## 證據與統計方法

- 原始來源：NAS 的 `social-media-stalker-performance-observer-20261115`、`social-media-stalker-performance-observer-20261116` 容器日誌。
- 覆蓋 **2026-11-15 20:51:33.770 至 2026-11-17 10:29:09.343**，約 37 小時 38 分，合併後 **2,259 筆**。重疊期間統一使用後一個 observer，不將兩份紀錄相加；最大樣本間隔 62.365 秒。
- 以連續異常樣本合成一段；第一個正常樣本視為觀測恢復。時間約有一個取樣間隔的邊界誤差，短於取樣間隔的異常可能遺漏。
- TikTok：健康檔 `ageMs > 120000`、`phase=stopped`、`manualRequired=true` 或任一 stream 回報 `failures > 0`。
- IG：`ageMs > 120000`、回報 failures 非零或 telegramOk=false。X：`ageMs > 120000` 或 phase 非 running。Telegram：`ageMs > 120000`、pollOk=false 或 telegramOk=false。
- 這是利用現有欄位的跨平台比較；各平台欄位意義不同。X 快照不含所有 target failures，IG 快照不含 supervisor 的全部判定，不能把表格解讀為等價的完整 Docker SLA。
- TikTok `health()` 在尚未 alerted 且連敗少於 3 次時，會把對外 failures 顯示為 0。故本表讀取的是公開健康欄位，並非把全部第一次內部重試一律當故障。已 alerted 的串流仍可回報 1 或 2；不能簡單改為 >=3 來還原 Docker 燈號。
- 可核算摘要與合併樣本存於本機 Git 忽略目錄 `data/research/tiktok-stability-20261117/`。完整起訖表見 [CSV](tiktok-stability-incidents-20261117.csv)。私人原始日誌另存本機 `/tmp/stalker-stability-evidence/`，未加入 Git 或公開文件。

## 同一觀測期間的比較

| 服務 | 異常區間 | 觀測恢復 | 異常樣本／總樣本 | 異常樣本比例 | 完整區間恢復中位／平均／最長（分鐘） |
|---|---:|---:|---:|---:|---|
| TikTok catalog | 74 | 74 | 1292 / 2259 | 57.19% | 2.00 / 6.52 / 155.02；排除起點未知的首段 |
| Instagram watch | 2 | 2 | 20 / 2259 | 0.89% | 9.52 / 9.52 / 10.03 |
| X watch | 3 | 2 | 47 / 2259 | 2.08% | 6.00 / 6.00 / 11.00；最後一段未在樣本內恢復 |
| Telegram control | 3 | 3 | 13 / 2259 | 0.58% | 3.00 / 4.33 / 9.00 |

樣本比例不是精確停機百分比，也不能推論所有帳號、下載及通知在異常期間都停止。各區間可能跨越部署或人工操作。

為避免早期長時間異常主導比較，另看 **11-16 10:27:45 至 11-17 10:29:09** 的 1,443 筆樣本：TikTok 異常樣本比例仍為 **32.99%**；IG 0.76%、X 2.49%、Telegram 0.07%。這仍是期間觀測，不能隔離其間各次部署的因果效果。

若採更嚴格的「stream failures >=3，或停止／心跳過期／需人工」替代條件，TikTok 為 **16 段、16 次恢復、259 個異常樣本**；恢復中位 6.00、平均 16.19、最長 147.02 分鐘。這是敏感度分析，不是實際紅燈次數。

## 代表性時間線

- 11-15 20:51 至 11-16 10:27：觀測開始時已異常；至少 13 小時 36 分。第一筆的內容最後成功時間已老化約 2.25–2.71 小時。待下載初始為 653，部署前已有長時間停滯；不是單純一兩分鐘抖動。
- 11-16 10:24–10:28：既有部署紀錄記載 `5cbc047` 上線，改為獨立 browser 子程序及 cooperative owner loop。首段異常在此附近解除，但該樣本仍有部分串流最後成功時間老化約 16 小時，證明健康恢復不等於全部串流刷新。待辦後續下降至 0。
- 11-16 13:56:53–16:31:54：完整可觀測最長異常段，約 155 分鐘；其間包含既有維護活動，不能全部歸為無人為因素的故障。
- 11-17 04:09:03–04:43:03：約 34 分鐘。
- 11-17 10:15:08–10:23:09：最後一段約 8 分鐘；樣本結束時正常。
- X 在 11-17 09:55 起心跳過期，觀測至 10:29 尚未恢復；另有 10:39:10 `X_WATCH_FATAL / X_OPERATION_FAILED`，10:39:31 再次 `X_WATCH_STARTED`。21 秒是 fatal 至啟動日誌的時間，不能當整段服務恢復耗時。

## 為甚麼不穩：已證實與尚待驗證

### 1. 已有瀏覽器傳輸層廣泛失效的直接證據

靜態備份 `catalog.sqlite.before-transport-retry-20261116-082237`：16 條 streams 中，**13 條** reason=`TIKTOK_BROWSER_TRANSPORT_FAILED`；8 條連敗 6 次、1 條 7 次、4 條 8 次；其餘 3 條無失敗。這支持該時點為跨串流的瀏覽器傳輸問題，而不是只有一個帳號或內容類型出錯。

本機與 NAS 容器內 `catalog_worker.py`、`catalog_query.py`、`catalog_browser_worker.py` SHA-256 一致。程式共用一個 browser 子程序及持久 profile；transport 失效會關閉 browser，下一筆查詢重建。各 stream 的退避為 60、120、240、480、960、1920 秒，之後上限維持 1920 秒（公式雖有 3600 秒外層上限，指數截斷於 6），另可受 retryAfter 延長。因此底層問題消失後，也不一定立即再試；多串流共用失效元件會放大異常範圍。

**尚不能證明** transport 失效的最底層是 Chromium 崩潰、CDP 連線、頁面關閉、idle freeze/resume、NAS 壓力或其他原因。上述程式路徑是機制證據，不是每次事故的根因證明。

### 2. 目前日誌不足以分類全部失敗

目前 catalog 容器日誌涵蓋 **11-16 18:43:44 至 11-17 13:17:21** 的失敗事件，共 **241 筆**：post 122、story 70、repost 36、profile 13。全部 exception=RuntimeError、networkError=null；237 筆經 `catalog_query.py:67` 的 browser 回傳錯誤路徑，4 筆經 `:69` 查詢 timeout 路徑。

這證明多數失敗是 browser 子程序回傳錯誤，少數是查詢 timeout；**無法**把 237 筆全部認定為 transport、CAPTCHA、限速或驗證失效。日誌未保留分類安全碼，子程序 stderr 被丟棄；SQLite stream reason 只留最新狀態，通知 outbox 查詢時為空，也不是事故歷史表。`networkError=null` 不能排除網路問題，因為原始錯誤可能已被安全分類碼取代。

### 3. 健康規則會放大部分功能故障的顯示範圍

4 個帳號 × 4 種內容共 16 條串流，任一對外 failures 非零即可令 catalog 健康檢查失敗；不必等全部內容查詢停止。Docker 每 30 秒檢查、連續 3 次失敗才轉 unhealthy，回復亦受下一次檢查影響。

IG supervisor、X、TikTok LIVE、VPN 及匯出服務檢查不同條件，不能只用 UI 顏色推論其可靠性完全可比。catalog 當下 unresolved=1 但 healthy，亦說明「待補查」與紅燈不是同一指標。

### 4. NAS 資源壓力為候選因素，未完成因果驗證

既有 `docs/nas-performance-baseline.md` 有高磁碟繁忙度及寫入等待紀錄，catalog 又依賴 Chromium、頁面導覽及持久 profile，可能比輕量 worker 更受影響。但本次未建立每次失敗與磁碟、CPU、記憶體的同步時間序列，不能判定 NAS I/O 是所有異常的原因。

實際 inspect：catalog memory limit=**6,056,730,624 bytes（約 5.64 GiB）**、NanoCpus=0、OOMKilled=false；與 Compose 範本預設 1536 MiB／2 CPU 不同。不能把範本預設當成實際上限，更不能聲稱已證實 OOM。OOMKilled=false 也無法排除已刪除舊容器或 browser 子程序的歷史問題。

## 容器層比較與證據限制

11-17 約 13:24–13:33 的唯讀快照：本專案運行中的 11 個正式服務皆 running；其中 8 個有健康檢查且全為 healthy，3 個未設健康檢查。catalog 當前 16 streams failures=0、pending=0、unresolved=1、manualRequired=false。

| 容器 | 當下狀態 | 現存容器 Docker RestartCount |
|---|---|---:|
| tiktok-catalog | healthy | 0 |
| tiktok-watch（LIVE） | healthy | 0 |
| tiktok-vpn | healthy | 0 |
| ig-watch / ig-telegram / ig-watchdog | healthy | 各 0 |
| x-watch | healthy | 1 |
| archive-export | healthy | 0 |
| tiktok-browser-resolver / archive-tunnel / telegram-bot-api | running，無 healthcheck | 各 0 |

RestartCount 不代表全部啟停／部署次數，容器重建會更換統計範圍；catalog 日誌最早時間早於最後 StartedAt，也顯示 0 不能等同「從未啟停」。

其他專案中，**運行中** `kmb-api-api-1`、`tiktok-browser-resolver`、`surfshark-vpn` 為 healthy，`x-archive-bridge` 為 unhealthy，這四個現存容器 RestartCount 都為 0。另有 5 個已停止容器殘留 unhealthy 狀態，包含舊 IG watch/watchdog、spacemake-gui、openclaw、jellyfin；不列為現行運行服務故障。其他未設健康檢查的運行容器不能當作「全程綠燈」。

**其他容器沒有同樣 37 小時的完整健康歷史，所以無法提供可信的歷史紅燈／恢復次數排行榜。**

Docker events 查詢雖要求歷史 24 小時，實際只返回 **256 筆、13:23:32–13:26:43（約 191 秒）**，沒有可用於本調查時段的完整 health_status 轉換。Docker 官方文件明載只返回最近 256 個事件：[Docker events](https://docs.docker.com/reference/cli/docker/system/events/)。目前 catalog inspect 健康檢查亦只保留最近 5 筆，無法補回過去 37 小時。

## 下一步調查建議（本次未實施）

1. 持久化全 NAS Docker health_status、start/die/restart/oom 事件，記錄容器 ID、服務、部署版本，保留至少 30 天；才可精確回答紅燈次數、恢復耗時及是否部署造成。
2. 在 catalog 失敗與恢復時保存安全錯誤碼、stream、連敗次數、browser generation、request 耗時；保存 browser 非敏感分類診斷，避免把 token、cookies、URL 或回應內容寫入。
3. 分開統計「程序／心跳」、「內容新鮮度／串流錯誤」、「下載進度」，同時收集磁碟等待、CPU、記憶體與 browser 子程序退出狀態。
4. 優先驗證 transport 失效如何觸發、退避是否延長恢復，再以受控單一變因測試 idle freeze、browser 輪替或儲存層。現有證據不足以支持直接加記憶體、關閉健康檢查或反覆重啟作為根治。
