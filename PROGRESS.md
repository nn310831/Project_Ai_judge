# 開發進度

更新日期：2026-11-27（Asia/Taipei）。本次僅實作 B3A-1，程式與 23 項新增測試完成；全部單元測試 176 passed。已 Commit／Push，依第 1.1 節停止，等待下一次單模組授權。

## Repository 與分支

- 沿用 `https://github.com/nn310831/Project_Ai_judge.git`；未新建 Repository、變更 Remote、重寫歷史或合併 main。
- 本次開始前確認 status、remote、branch、log 及 ls-remote：main／develop 仍為 `245ef663eb8a08078616123c3e088a52d9bd603a`，C-1 為 `cf3b19d`，無遠端衝突。
- 前次區塊 1 分支 `feature/phase1-attacks`，從已測試的 C-1 延伸；[PR #2](https://github.com/nn310831/Project_Ai_judge/pull/2) 目標 develop，依賴尚待整合的 [PR #1](https://github.com/nn310831/Project_Ai_judge/pull/1)。兩個 PR 均未由本次工作合併。
- 使用者未提交的 `.gitignore` 修改（忽略 compose.dev.yaml）原樣保留，不納入 Commit；未讀取或操作開發資料庫。

## 模組與 Commit

| 區塊／模組 | 狀態 | Commit／交付 |
|---|---|---|
| 共同區塊 1／C-1 | 完成、已 Push；PR #1 | `d2c6c9e` 儲存、`cf3b19d` 交付紀錄 |
| 區塊 1／B1-1 | 完成、已獨立 Commit／Push | `6754b4f` JSONL 匯入、原子保存、逐行錯誤、操作查詢 |
| 區塊 1／B1-2 | 完成、已獨立 Commit／Push | `20c43f5` 單筆／批次範本匯入、輪次驗證 |
| 區塊 1／B1-3 | 完成、已獨立 Commit／Push | `88bee72` 隨機範本、可替換 GenAI、驗證及來源保存 |
| 區塊 1／B1-4 | 完成、已獨立 Commit／Push | `88f1c80` spectral K-DPP、可設定表示法／kernel／品質／seed |
| 區塊 1 整合 | 完成、已 Commit／Push | `5ca7a2e` PostgreSQL 流程與 OpenAPI schema 驗證 |
| 區塊 2／B2-1 | 完成、已 Commit／Push | `e873f36` 設定 |
| 區塊 2／B2-2 | 完成、已 Commit／Push | `26f45f8` 載入與 adapter |
| 區塊 2／B2-3 | 完成、已 Commit／Push | `56b1125` 多輪 runner／worker |
| 區塊 2／B2-4 | 完成、已 Commit／Push | `caeb21e` 上下文 |
| 區塊 2／B2-5 | 完成、已 Commit／Push | `5bece56` 輸出統一 |
| 區塊 2／B2-6 | 完成、已 Commit／Push | `7037657` 共用證據 |
| 區塊 2／B2-7 | 完成、已 Commit／Push | `6b05e3f` 持久化與查詢 |
| 區塊 3 Path A／B3A-1 | 完成、已 Commit／Push | `1af9779` 三位 Judge 輸入整理 |
| 區塊 3 Path A／B3A-2、B3A-3、B3A-4、B3A-5 | 未開始 | 等待各次單模組授權 |
| 區塊 3 Path B／B3B | 未開始 | 等待指示 |
| 區塊 4／B4-1、B4-2、B4-3、B4-4、B4-5、B4-6、B4-7、B4-8 | 未開始 | 等待指示 |

每個功能模組先測試並更新 README／進度、檢查暫存檔案及憑證模式，再建立 Conventional Commit 並立即 Push，回報並停止，收到下一次明確授權才開始下一模組。Hash 在後續文件補記，未使用 amend／force push。

## 區塊 1 歷史測試紀錄

| 階段 | 實際結果 |
|---|---|
| C-1 前次交付 | 37 passed（34 單元、3 PostgreSQL），遠端 CI 通過 |
| B1-1 | `.venv/bin/python -m pytest tests/unit -q`：45 passed；含 PostgreSQL 全套 48 passed |
| B1-2 | 同上單元測試：60 passed，新增 15 項範本案例 |
| B1-3 | 同上單元測試：77 passed，新增 17 項生成／供應商替身案例 |
| B1-4 | 同上單元測試：96 passed，新增 19 項抽樣案例 |
| 區塊 1 最終整合 | 104 passed（97 單元、7 PostgreSQL），0 failed、0 skipped |

最終測試指令：

```sh
AI_JUDGE_TEST_DATABASE_URL=postgresql+psycopg://postgres@127.0.0.1:55432/ai_judge_test .venv/bin/python -m pytest -q
.venv/bin/ruff check ai_judge migrations tests
.venv/bin/ruff format --check ai_judge migrations tests
git diff --check
```

以上皆通過。1 項既有 Starlette/httpx TestClient 棄用警告，無未處理失敗。資料庫測試僅使用專屬 Docker PostgreSQL 17、隨機隔離 schema、合成資料。

- 真實 PostgreSQL 驗證四模組流程、失敗批次不寫入、升級保留 C-1 資料、執行中進度與健康查詢、重複 ID 防護、重新建立連線後保存，以及 C-1 遷移／回滾／timeout 回歸。
- K-DPP 使用 6000 個固定 seed 比較子集頻率與行列式理論機率；另測完全相同候選排斥、唯一性、重現性、候選／rank 不足及數值檢查。
- GenAI 正式 adapter 已實作、預設停用；HTTP transport 替身驗證供應商 protocol，未進行真實付費呼叫，沒有生產 mock fallback。
- 區塊 2～4 及全專案端到端測試未執行。

## 介面及資料變更

- POST `/api/v1/attacks/import`、`/api/v1/attack-templates/import`、`/api/v1/attacks/generate`、`/api/v1/attacks/sample`；GET `/api/v1/attack-jobs/{job_id}`。OpenAPI／README 列成功及錯誤 schema、設定、範例與限制。
- 新增 `0002_phase1_jobs` 遷移與 attack_jobs；保留原始攻擊／範本欄位。成功資料與成功 job 狀態原子提交。
- 新增 AI_JUDGE_PHASE1_*、AI_JUDGE_GENAI_*、AI_JUDGE_SAMPLING_* 設定，.env.example 不含真實憑證。
- 新增 NumPy，httpx 列為正式依賴，requirements-dev.lock 同步。

## 區塊 1 交付時的限制與待確認

- 真實 GenAI 供應商、模型及提示版本仍需專案設定；只交付 Chat Completions 相容 adapter，不宣稱驗證真實模型品質。
- hash char n-gram 文字表示可替換；kernel／品質設定為工程起點，不代表已確認研究方法。候選最多 500，超限拒絕，不截取前 N 筆或退回普通隨機抽樣。
- 浮點 k-DPP 按 tolerance 將微小特徵值視為零；不自動加 jitter。跨平台／BLAS／NumPy 版本不保證索引完全相同。
- 匯入保留重複內容，失敗整批不寫入。攻擊仍用非空文字陣列；範本 round 從 1 連續遞增。
- 有上限的同步請求由執行緒池執行，可預先指定 X-Job-ID 查進度。中斷操作在 10 分鐘期限後被查詢時標示 interrupted；無自動重試、重複付費或背景佇列。
- 原計畫 4.4 其餘研究規則保留待確認；未提前實作區塊 2～4。

## 交付追蹤

[PR #2](https://github.com/nn310831/Project_Ai_judge/pull/2) 已建立且未合併。功能與整合 Commit 已同步遠端；本文件以後續文件 Commit 補記實際交付，該 Commit Hash 由 git log 查閱。最新 GitHub Actions 以 PR checks 顯示為準。

- 整合 Commit `5ca7a2e` 的 [Push 檢查](https://github.com/nn310831/Project_Ai_judge/actions/runs/45641803953/job/139302149881) 與 [PR 檢查](https://github.com/nn310831/Project_Ai_judge/actions/runs/45641946500/job/139302666451) 均已確認 success。
- 本次測試容器與專用網路已以 `docker compose -p ai-judge-c1-test -f compose.test.yaml down` 移除。


## 區塊 2（2026-11-26）

- 依更新後第 4.5／4.6 節開發；此次只完成 B2，不提前實作 E2E-1 或 B3／B4。
- 分支 `feature/phase2-target-testing`，基於區塊 1 的 57081dc；遠端 main／develop 仍為 245ef66。新版計畫納入本次版本，其餘使用者修改（.gitignore、B1 generation／sampling、repository 及 test_storage）保留且不提交。
- 實作順序依內部相依性安排 B2-1、B2-2、B2-4、B2-5、B2-6、B2-7、B2-3，不改原始模組編號；每模組測試後立即 Commit／Push。
- 開始前既有單元測試 97 passed。
- B2-1 完成：不可變模型設定、參數白名單、受保護 API、端點允許清單、migration 0003；配置不呼叫模型。單元測試 108 passed；新增／修改程式 lint 通過。Commit 訊息 `feat(phase2): implement target model configuration`，Hash 於下一紀錄補入。

- B2-1：`e873f36` 已 Commit／Push。
- B2-2 完成：載入成功 B1-4 job 或直接快照，禁止暗中重新抽樣；不可變 load 快照、migration 0004、Ollama adapter 與可替換 registry。單元測試 119 passed，lint 通過。提交 `feat(phase2): load sampling snapshots and add Ollama adapter`。

- B2-2：`26f45f8` 已 Commit／Push。
- B2-4 完成：可開關的完整歷史對話視窗、字元上限、案例隔離、超限錯誤；供 runner 內部呼叫，不新增 endpoint。123 單元測試通過，lint 通過。提交 `feat(phase2): implement isolated sliding-window context`。

- B2-4：`caeb21e` 已 Commit／Push。
- B2-5 完成：供應商中立的公開輸出統一層，JSON／mapping／契約得到相同四欄，缺失推理不補造。134 單元測試通過，lint 通過。提交 `feat(phase2): normalize target model outputs`。

- B2-5：`5bece56` 已 Commit／Push。
- B2-6 完成：同一份可追溯的 Path A/B 公開推理資料、1 起算步驟、mock／來源標記與獨立副本，保留原四欄。137 單元測試通過，lint 通過。提交 `feat(phase2): standardize shared judging evidence`。

- B2-6：`7037657` 已 Commit／Push。
- B2-7 完成：queued run／案例快照、每輪 running→終止紀錄、參數／耗時／錯誤／證據、分頁查詢、lease／owner 與過期標記。migration 0005；當次參數覆寫隔離，查詢不重新執行。141 單元測試通過；真實 PostgreSQL 區塊整合在最後執行。提交 `feat(phase2): persist target runs and round records`。

- B2-7：`6b05e3f` 已 Commit／Push。
- B2-3 完成：202 持久化啟動、獨立 worker、逐輪順序／案例隔離、失敗保存與剩餘輪次跳過、雙重明確啟用的 mock，預設無重試。152 單元測試通過；區塊 PostgreSQL 整合接續執行。提交 `feat(phase2): execute durable multi-turn target tests`。


- B2-3：`56b1125` 已 Commit／Push。
- 區塊 2 整合：完整 pytest 165 passed（153 單元、12 PostgreSQL），0 failed、0 skipped；真實 PostgreSQL 17 使用專屬測試 DB 與隨機 schema。新增 5 項 B2 整合與 1 項 OpenAPI 測試。既有 1 項 Starlette/httpx 警告。
- `ruff check ai_judge migrations tests` 通過；B2 所有檔案 format 通過。工作目錄全域 format 僅因使用者未提交的 B1 generation 註解尾端空白失敗，未改寫該檔案；另以提交快照驗證遠端版本。
- 尚未執行真實 Ollama／付費 GenAI；HTTP protocol 使用 transport 替身，持久化使用真實 PostgreSQL；mock 預設仍停用。
- E2E-1 未開始，待 B3／B4 完成後實作共用 Orchestrator、完整啟動 API／CLI、雙軌及報告查詢。本次沒有提前實作或修改研究方法。


## 區塊 2 交付追蹤

- 目前分支：`feature/phase2-target-testing`；既有 Repository、Remote、main／develop 均維持原狀。
- 整合 Commit：`f14815b`；[PR #3](https://github.com/nn310831/Project_Ai_judge/pull/3) 目標 develop，依賴 #2／#1，未合併。所有七模組 Commit 均已推送。
- 使用 `git archive HEAD` 建立乾淨的提交快照再次驗證：165 passed、0 skipped；全域 Ruff lint 與 format 均通過（61 個 Python 檔案）。此結果不依賴使用者的五個未提交修改檔案。
- 整合 Commit 的 [Push CI](https://github.com/nn310831/Project_Ai_judge/actions/runs/45848992522/job/140010046132) 已確認 success；[PR CI](https://github.com/nn310831/Project_Ai_judge/actions/runs/45849096372/job/140010411877) 建立後執行中，最新結果以 PR checks 為準。交付紀錄另以 docs Commit 推送，不 amend／force push。
- 專用 PostgreSQL 測試容器與網路已執行 compose down 移除；未讀取或操作 compose.dev.yaml 或開發資料庫。
- 本次沒有阻擋後續的測試失敗；真實 Ollama 品質、B3／B4 與 E2E-1 尚未驗收。收到下一區塊指示前不繼續實作。


## B3A-1（2026-11-27）：三位 Judge 輸入整理

- 唯一授權模組 B3A-1，依賴已完成 B2-6。開始前確認 Git status／remote／log／ls-remote、既有程式及測試；原分支與遠端均為 d38f0be，main／develop 仍 245ef66，沒有遠端分歧。
- 本次分支 `feature/phase3-judge-inputs`，從 d38f0be 延伸，沿用原有 Repository；保留既有七個修改檔案：.env.example、.gitignore、CODEX_IMPLEMENTATION_PLAN.md、B1 generation／sampling、storage/repository.py、test_storage.py，均不納入本次提交。
- 檔案：新增 phase3/__init__.py、phase3/inputs.py、tests/unit/test_phase3_inputs.py；更新 README、PROGRESS。沒有新增依賴、HTTP endpoint、資料庫 migration、環境設定或既有資料契約變更。
- 完成：B2 物件／保存的 evidence 驗證、相同公開輸出與步驟／來源／ID 快照、明確傳入 JudgePolicy、版本紀錄、GPT／Claude／Gemini 內容片段、無副作用的獨立副本、規範與不可信資料訊息分離。附既有 JudgeResult schema，不擅定研究評分規則。
- 實際測試：開始前 153 單元通過；新增檔案 23 passed；完成後全部單元 176 passed，既有 Starlette/httpx 警告 1 項。Ruff 全域 lint 通過，新檔 format 通過。包含 B2 mock runner→持久化 evidence→B3A-1 三格式的內部串接（SQLite 單元替身）。本機本次未執行 PostgreSQL 整合，無資料庫變更；區塊 3 整合／PR 待最後模組完成。
- 正式／mock：本模組不呼叫外部模型、不實作評審 mock；僅保留 B2 target mock 來源。評審 Adapter、密鑰管理、裁決、Path B、評分及 E2E-1 尚未實作。
- 已知限制：需要專案提供已確認的評判規範及版本，未驗證真實 Judge 品質；訊息格式是內容片段，不是完整 HTTP 請求。後續 Adapter 需驗證指定模型、token 預算及結構化輸出相容性。
- 建議下一個模組：B3A-2（GPT 評審介面與模型設定），需另獲明確授權。本次完成後停止。


### B3A-1 版本交付

- 實作 Commit `1af9779c4002d83d5aa4682d06e17c4747805c5f` 已推送至 origin/feature/phase3-judge-inputs。
- 以 git archive 建立乾淨提交快照再次確認：176 單元測試通過、全域 Ruff lint／format 通過（64 個檔案）。原有七個使用者修改均保留且未提交。
- [GitHub Actions](https://github.com/nn310831/Project_Ai_judge/actions/runs/45858279346/job/140042294833) 已啟動；此紀錄建立時執行中，最終狀態以 Actions 為準。
- 本次不是區塊 3 最後一個模組，不提前執行區塊 3 全流程驗收或建立完成 PR。B3A-2 僅為建議下一模組，尚未開始。
