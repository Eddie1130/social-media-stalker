# TikTok catalog 維護

以 `AGENTS.md` 為準；正式環境在 NAS `/volume1/docker/social-media-stalker`。

- 修改後須保留兩端未提交修改、更新 `CHANGELOG.md`，並同步 NAS／驗證實際查詢。
- 部署與回復程序見 `docs/tiktok-catalog-reliability.md`、`docs/nas-operations.md`。
- NAS Docker 不支援 CFS quota；部署前執行 `./igctl preflight`。自訂 Compose 全域選項放在 `preflight` 後，並與部署使用相同設定。
- catalog 與 login 共用持久 profile，必須互斥；不得刪除未知 owner 的 Chromium Singleton 鎖。
- 不執行 `down -v`，不覆蓋 `.env*`、cookies、profile、資料庫或通知收據。
- 不因 Docker healthy 就認定查詢成功；核對 `lastSuccess`、失敗分類、SQLite 與佇列進度。

正式 SQLite 完整性檢查使用 online backup 快照，先關閉來源連線再執行 quick_check。

公開貼文預設使用獨立匿名 context（TIKTOK_CATALOG_ANONYMOUS_POSTS=1）；其他類型保留登入 context。兩者共用 Chromium、隔離 Cookie，禁止將登入 Cookie 複製到匿名 context。設 0 可回復舊查詢模式，無需回滾資料庫。
