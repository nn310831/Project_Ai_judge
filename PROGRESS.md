# 開發進度

更新日期：2026-11-25（Asia/Taipei）。本次「區塊 1」完成；四個模組均獨立測試、Commit、Push，區塊整合通過並建立 PR #2。停止於區塊 1，等待使用者指示區塊 2。

## Repository 與分支

- 沿用 `https://github.com/nn310831/Project_Ai_judge.git`；未新建 Repository、變更 Remote、重寫歷史或合併 main。
- 本次開始前確認 status、remote、branch、log 及 ls-remote：main／develop 仍為 `245ef663eb8a08078616123c3e088a52d9bd603a`，C-1 為 `cf3b19d`，無遠端衝突。
- 現在分支 `feature/phase1-attacks`，從已測試的 C-1 延伸；[PR #2](https://github.com/nn310831/Project_Ai_judge/pull/2) 目標 develop，依賴尚待整合的 [PR #1](https://github.com/nn310831/Project_Ai_judge/pull/1)。兩個 PR 均未由本次工作合併。
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
| 區塊 2／B2-1、B2-2、B2-3、B2-4、B2-5、B2-6、B2-7 | 未開始 | 等待指示 |
| 區塊 3 Path A／B3A-1、B3A-2、B3A-3、B3A-4、B3A-5 | 未開始 | 等待指示 |
| 區塊 3 Path B／B3B | 未開始 | 等待指示 |
| 區塊 4／B4-1、B4-2、B4-3、B4-4、B4-5、B4-6、B4-7、B4-8 | 未開始 | 等待指示 |

每個功能模組先測試並更新 README／進度、檢查暫存檔案及憑證模式，再建立 Conventional Commit 並立即 Push，才開始下一模組。Hash 在後續文件補記，未使用 amend／force push。

## 測試紀錄

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

## 限制與待確認

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
