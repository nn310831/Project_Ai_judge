# 開發進度

更新日期：2026-11-25（Asia/Taipei）。本次範圍為「區塊 1」，每個模組測試後立即 Commit／Push，區塊完成後停止。

## Repository 基準

- Remote：`https://github.com/nn310831/Project_Ai_judge.git`，沿用既有 Repository。
- 初始 `main`／遠端 `main`：`245ef663eb8a08078616123c3e088a52d9bd603a`（初次上傳）。開始時工作目錄乾淨，遠端只有 main，已用 `git ls-remote --heads origin` 確認。
- 原先只有 `.gitignore` 受追蹤；實作計畫被忽略。本次保留計畫原文並納入版本控制。
- 建立 `develop` 於上述基準；本次工作分支：`feature/common-storage`，PR 目標 `develop`。不合併或直接更新 main。

## 模組狀態

| 區塊／模組 | 狀態 | 交付 |
|---|---|---|
| 共同區塊 1／C-1 | 已完成，37 項測試通過；已 Commit／Push／建立 PR #1 | 資料契約、連線池、批次持久化、來源關聯、交易回滾、Alembic 遷移、健康檢查 |
| 區塊 1／B1-1 | 已完成，已 Commit／Push：6754b4f | JSONL 匯入、原子保存、操作及錯誤查詢 |
| 區塊 1／B1-2 | 已完成，已 Commit／Push：20c43f5 | 單筆／批次範本匯入、輪次驗證 |
| 區塊 1／B1-3 | 已完成單元測試，準備提交 | 隨機範本、可替換 GenAI、驗證及來源保存 |
| 區塊 1／B1-4 | 未開始 | K-DPP 抽樣 |
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
- GitHub Actions 的功能 Commit Push 檢查已通過：[common-storage](https://github.com/nn310831/Project_Ai_judge/actions/runs/45440915602/job/138611442852)。後續文件 Commit 及 PR 檢查以 GitHub 顯示的最新結果為準。
- 本次測試容器及專用網路已透過 `docker compose -p ai-judge-c1-test -f compose.test.yaml down` 清除。
- 真實模型 API：未實作／未呼叫；模型 mock：未實作／未啟用。全專案端到端流程尚未執行。

## Commit 與遠端追蹤

- 基準 Commit：`245ef663eb8a08078616123c3e088a52d9bd603a`。
- C-1 功能 Commit：`d2c6c9e32f160b1787d9556efbc62bc8825a50ab`，`feat(common): implement PostgreSQL storage module`；測試通過後已立即 Push 至 `origin/feature/common-storage`。
- `develop` 已 Push 至 `origin/develop`，仍為初始穩定基準 `245ef66`，等待 PR 檢閱後整合。
- [PR #1](https://github.com/nn310831/Project_Ai_judge/pull/1)：`feature/common-storage → develop`，已建立且未合併；`main` 維持原基準。
- 此紀錄以後續 `docs(progress): record C-1 delivery and pull request` Commit 補記功能 Hash 與實際遠端結果；文件 Commit 本身 Hash 可由 `git log` 查閱，不改寫既有歷史。
- 所有提交檔案已檢閱，憑證模式掃描通過；未提交本機環境、憑證、真實資料或模型權重。

## 已知限制與待處理

- 目前只提供 C-1 內部儲存及健康檢查，資料匯入 HTTP API 屬下一區塊。
- `attack_content` 採非空字串陣列；範本輪次由 1 連續遞增。README 明列此介面選擇，若實際資料採逐輪物件需確認後擴充。
- 一般儲存不去重；匯入政策及原計畫 4.4 的研究決策仍待各區塊確認。
- Starlette TestClient 對 httpx 有棄用警告，不影響本次結果。
- 環境沒有 GitHub CLI，已透過既有 Git credential 與 GitHub API 建立 PR，未輸出或寫入憑證。
- 本區塊已交付；停止於 C-1，待使用者指示再開始區塊 1。


## 區塊 1 開發紀錄

- 開始前已確認 status、remote、branch、log 及 ls-remote；遠端 main／develop 仍為 245ef66，C-1 功能分支 cf3b19d。從已驗證的 C-1 建立 `feature/phase1-attacks`，PR 將以 develop 為目標並註明依賴 PR #1。
- 使用者未提交的 `.gitignore` 修改（忽略 compose.dev.yaml）原樣保留，不納入本次 Commit；不讀取或操作其開發資料庫。
- B1-1：新增 JSONL 匯入、strict JSON／資料契約驗證、原子批次保存、可查詢操作紀錄與錯誤；migration 0002_phase1_jobs。README 已列完整 API／限制。
- B1-1 單元測試：`.venv/bin/python -m pytest tests/unit -q`，45 passed；lint 通過。提交訊息 `feat(phase1): implement JSONL dataset importer`；Hash 在下一模組紀錄補記，不改寫歷史。

- B1-1 全套測試（含隔離 PostgreSQL）：48 passed、0 failed、0 skipped；遷移與既有功能回歸通過，1 項已知 TestClient 棄用警告。

- B1-1 功能 Commit：`6754b4f`，已立即 Push 至 origin/feature/phase1-attacks。
- B1-2：單筆或陣列封裝範本匯入；驗證輪次順序／型態，整批保存或回滾，保留重複資料。README 與測試同步更新。
- B1-2：`.venv/bin/python -m pytest tests/unit -q`，60 passed，lint 通過；新增 15 個範本匯入案例。提交訊息 `feat(phase1): implement attack template importer`，Hash 於下一模組補記。

- B1-2 功能 Commit：`20c43f5`，已立即 Push。
- B1-3：完成可設定的 Chat Completions 正式 adapter、指定類別隨機範本、結果驗證及關聯保存；請求 timeout、回應大小／並行上限、單次呼叫無自動重試、錯誤記錄及憑證遮蔽。預設停用，未呼叫真實付費模型。
- B1-3：`.venv/bin/python -m pytest tests/unit -q`，77 passed；lint 通過。新增 17 項生成與供應商替身測試。README／.env.example 更新。提交訊息 `feat(phase1): implement template-based GenAI generation`。
