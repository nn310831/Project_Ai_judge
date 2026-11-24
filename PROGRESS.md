# 開發進度

更新日期：2026-11-25（Asia/Taipei）。本次範圍僅「共同區塊」，完成後等待使用者指示。

## Repository 基準

- Remote：`https://github.com/nn310831/Project_Ai_judge.git`，沿用既有 Repository。
- 初始 `main`／遠端 `main`：`245ef663eb8a08078616123c3e088a52d9bd603a`（初次上傳）。開始時工作目錄乾淨，遠端只有 main，已用 `git ls-remote --heads origin` 確認。
- 原先只有 `.gitignore` 受追蹤；實作計畫被忽略。本次保留計畫原文並納入版本控制。
- 建立 `develop` 於上述基準；本次工作分支：`feature/common-storage`，PR 目標 `develop`。不合併或直接更新 main。

## 模組狀態

| 區塊／模組 | 狀態 | 交付 |
|---|---|---|
| 共同區塊 1／C-1 | 已完成，37 項測試通過；待 Commit／Push／PR | 資料契約、連線池、批次持久化、來源關聯、交易回滾、Alembic 遷移、健康檢查 |
| 區塊 1／B1-1、B1-2、B1-3、B1-4 | 未開始 | 等待使用者指定下一區塊 |
| 區塊 2／B2-1、B2-2、B2-3、B2-4、B2-5、B2-6、B2-7 | 未開始 | 依計畫相依關係實作 |
| 區塊 3 Path A／B3A-1、B3A-2、B3A-3、B3A-4、B3A-5 | 未開始 | 真實介面與預設停用 mock 待實作 |
| 區塊 3 Path B／B3B | 未開始 | 可替換的 mock AffordRanker 待實作 |
| 區塊 4／B4-1、B4-2、B4-3、B4-4、B4-5、B4-6、B4-7、B4-8 | 未開始 | 聯合判定、保存、指標及報告待實作 |

## 驗證紀錄

- 初次單元測試：`python -m pytest tests/unit -q`，33 passed。
- 初次 PostgreSQL 整合測試：沙盒阻擋本機 TCP 連線，2 setup errors；取得執行權限後重跑，2 passed。測試使用專屬 Docker PostgreSQL 17，不使用正式資料庫。
- 已驗證：JSONB 持久化、重建實體連線後讀取、來源外鍵、交易錯誤回滾、重複執行 upgrade、schema 與 migration 一致、downgrade／upgrade、實際 health ready 狀態。
- 最終完整測試：`AI_JUDGE_TEST_DATABASE_URL=postgresql+psycopg://postgres@127.0.0.1:55432/ai_judge_test .venv/bin/python -m pytest -q`，37 passed（34 單元、3 PostgreSQL 整合）、0 failed、0 skipped，1 個已知依賴棄用警告。已含設定錯誤遮蔽、SQL timeout 恢復案例。
- `.venv/bin/ruff check ai_judge migrations tests`、`.venv/bin/ruff format --check ai_judge migrations tests`、`git diff --check` 均通過。
- 真實模型 API：未實作／未呼叫；模型 mock：未實作／未啟用。全專案端到端流程尚未執行。

## Commit 與遠端追蹤

- 基準 Commit：`245ef663eb8a08078616123c3e088a52d9bd603a`。
- C-1 功能 Commit：待建立；將以 `feat(common): implement PostgreSQL storage module` 獨立提交，成功後即 push。
- 因 Commit 無法包含自己的最終 Hash，會以後續文件 Commit 補記實際功能 Hash、Push 與 PR 結果，不改寫既有歷史。

## 已知限制與待處理

- 目前只提供 C-1 內部儲存及健康檢查，資料匯入 HTTP API 屬下一區塊。
- `attack_content` 採非空字串陣列；範本輪次由 1 連續遞增。README 明列此介面選擇，若實際資料採逐輪物件需確認後擴充。
- 一般儲存不去重；匯入政策及原計畫 4.4 的研究決策仍待各區塊確認。
- Starlette TestClient 對 httpx 有棄用警告，不影響本次結果。
- 環境沒有 GitHub CLI；將使用既有 Git credential 與 GitHub API 建立 PR，不輸出憑證。遠端權限結果以實際執行為準。
