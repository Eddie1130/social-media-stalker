# 匿名貼文查詢：部署與再驗證（2026-11-20）

- 正式映像：`sha256:ac422a08c7593670243742fc78069acb079e17a25828f173481121aaca1b5b60`。原 Git HEAD 為 `bb7e581`，部署包含未提交修改，不能只用 commit 表示版本；本機與 NAS 三個修改模組 SHA256 相同。
- 公開 post 使用獨立非持久匿名 context；Story／轉發／profile／like 保留登入 context。同一 Chromium 重用兩種 context，不複製登入 Cookie。修正跨 context 換頁與 popup guard、init script 累積；兩種 context 都安裝原讀取防護。
- 設定：`TIKTOK_CATALOG_ANONYMOUS_POSTS=1` 預設啟用；設 0 並重新建立 catalog 可回復登入貼文查詢。仍不保證私密內容能取得。
- 測試：54 項 catalog 測試（3 skip）、90 項 TikTok 測試通過；真 Chromium 無網路測試四輪身份切換，Cookie 隔離及每 context 一個 popup listener 通過。首次匿名實測四個 context 可取得清單，分頁各 20 筆、無重複。
- 備份：NAS `data/backups/catalog-anonymous-20261120/`，SQLite quick_check=ok，profile／control／Cookie／catalog.required 壓縮備份完整讀回；部署前 targets=4、streams=16、items=2972、outbox=0。私人備份不得提交。
- 建置：一般 `igctl build` 被無關 `export_service/snapshot.py` 讀取權限阻擋；沒有更動權限，改用最小 context，apt／pip／Chromium 層均命中快取：

```sh
export PATH=/usr/local/bin:/usr/bin:/bin:$PATH
tar cf - Dockerfile.tiktok-catalog tiktok/*.py |
  DOCKER_BUILDKIT=0 docker build --target catalog -f Dockerfile.tiktok-catalog -t social-media-stalker-tiktok-catalog -
```

先執行 preflight／config，核對 VPN config hash；本次為保留既有相依容器，使用文件的 stop catalog、rm catalog（不加 -v）、up --no-build --no-recreate tiktok-vpn tiktok-catalog 流程，未重建 VPN／LIVE。另做一次受控 stop／start，兩次均正常停止；為測試只將一個失敗 post 的 nextAt 改為立即重試，原 state 另存備份，未更動游標／baseline／失敗紀錄。

## 再次變紅的證據（15:23 香港時間）

容器自 10:56 起持續運行、restart=0、OOM=false，心跳正常、storageBlocked=false、manualRequired=false；4 個 post 出錯，另 12 條 Story／轉發／profile 無錯誤。四個帳號的最後成功時間分別約 14:00、14:02、15:11、15:12，代表部署曾實際成功，但未消除後續錯誤。

最近兩小時日誌：35 次 TIKTOK_EMPTY_RESPONSE、1 次 TIKTOK_RATE_LIMITED。空回應診斷顯示 HTTP 200、Content-Length=0、readBytes=0、providerChars=0；不是把合法空清單誤判為 JSON。正式匿名 context 經 CDP 查驗沒有登入 Cookie。

兩個全新匿名 context（導航後 2 秒／12 秒）仍然無法取得網頁原生及 provider 清單；另一個全新匿名頁面顯示 Something went wrong，未檢出 CAPTCHA 文字。本機全新 headless Chrome 則遇到人機驗證，不能作為有效網路出口對照，未嘗試繞過。

**結論：匿名方式有短期成功，服務容器及狀態恢復已驗證，但資料取得仍不可靠。HTTP 空回應是已確認的直接失敗；TikTok 為何回空（出口／風控／其他條件）尚未證實，不能將全部錯誤歸因 Cookie、CAPTCHA 或限流。不得宣稱 24 小時穩定。**

## 回復

舊映像保留為 `social-media-stalker-tiktok-catalog:before-anonymous-20261120`，來源檔案在 `source-before.tgz`。若需回復，先核對現有修改並只停止 catalog，恢復對應來源／Compose 設定、將舊映像重新標記，再依可靠性文件只重建 catalog。保留最新 SQLite、下載與通知收據；不要還原較舊資料庫來回退程式。

## 資料完整性再驗證

正式資料庫以分頁 online backup 複製至記憶體，先關閉來源後 quick_check=ok。與部署前備份比較：targets 4→4、streams 16→16、items 2972→2972，各主鍵缺失皆 0；outbox 0→0。任務為 ready 2971、unresolved 1，無 pending。這確認既有紀錄保留，不代表已完成新的真實下載或證明無重複 Telegram 通知。

24 小時觀察須記錄貼文 lastSuccess 是否持續推進、空回應／429 比例、重啟數與 pending/unresolved；目前仍有真實失敗，不能因心跳正常便判定穩定。檢查方式見 tiktok-catalog-reliability.md。
