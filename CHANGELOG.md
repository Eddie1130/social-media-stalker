# Changelog

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
