# AI Judge 後端

依據 [實作計畫](CODEX_IMPLEMENTATION_PLAN.md) 分區塊交付。共同區塊 C-1 已完成；區塊 1 的四個模組已實作（下方列出 API）。區塊 2～4 尚未實作，沒有前端。

## 安裝與啟動

需要 Python 3.12+、PostgreSQL 17（本次驗證版本）。

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.lock
cp .env.example .env
# 編輯 .env，填入既有 PostgreSQL 的連線資訊；先建立空資料庫與具遷移權限的帳號。
alembic upgrade head
uvicorn ai_judge.main:app --host 127.0.0.1 --port 8000
```

`requirements-dev.lock` 固定此次測試的套件版本；`pyproject.toml` 宣告依賴範圍。也可使用 `python -m pip install -e '.[dev]'` 安裝可編輯套件。環境變數優先於 `.env`。密碼中的特殊字元須 URL encode。啟動服務不自動建表或遷移，部署時先執行 `alembic upgrade head`。`alembic current` 可檢查版本；降版會刪除本模組資料表，只適用於明確可丟棄的環境。

| 環境變數 | 預設／用途 |
|---|---|
| `AI_JUDGE_DATABASE_URL` | 必填，`postgresql+psycopg://USER:PASSWORD@HOST:5432/DB` |
| `AI_JUDGE_DB_POOL_SIZE` | 5，連線池大小 |
| `AI_JUDGE_DB_MAX_OVERFLOW` | 5，額外連線上限 |
| `AI_JUDGE_DB_POOL_TIMEOUT` | 10 秒，等待連線上限 |
| `AI_JUDGE_DB_CONNECT_TIMEOUT` | 5 秒，建立連線上限 |
| `AI_JUDGE_DB_STATEMENT_TIMEOUT_MS` | 10000 毫秒，SQL 執行上限 |

C-1 不呼叫模型；B1-3 提供正式 GenAI adapter，但預設停用，設定方式見下方。SQLite 僅用於單元測試替身；正式環境只接受 PostgreSQL。區塊 2 mock 預設停用、Path A mock 預設停用、Path B mock 預設啟用的要求，留待各區塊實作。

## 已完成 HTTP API（C-1）

本機 base URL：`http://127.0.0.1:8000`。下列 API 均無 request body、query 或 path 參數，也無外部模型呼叫或 mock。

| Method／完整 path | 用途 | 成功回應 schema／範例 | 錯誤 |
|---|---|---|---|
| `GET /health/live` | 程序存活，不查資料庫 | 200，`{"status":"ok"}` | 無自訂業務錯誤 |
| `GET /health/ready` | 查詢資料庫是否可用且遷移版本為 `0002_phase1_jobs` | 200，`{"status":"ready"}` | 503，`{"status":"unavailable"}`；連線／SQL 失敗、尚未遷移或版本不符 |
| `GET /openapi.json` | FastAPI 產生的 API schema | 200，OpenAPI JSON 物件，包含 `paths`、`components` | 無自訂業務錯誤 |
| `GET /docs`、`GET /redoc` | FastAPI 自動 API 文件 | 200，HTML | 無自訂業務錯誤 |

健康檢查回應為 `Health {status: string}`，不包含資料庫 URL、SQL、密碼或資料內容。Ready 是連線與版本檢查，不代替所有資料表的完整性稽核。同步 DB 工作由 FastAPI 同步路由的執行緒池處理。

## 共用資料契約

定義於 `ai_judge/contracts.py`。不改名或合併 `subcategory` 與 `risk_subcategory`。內部 UUID、來源及時間戳放在儲存紀錄外層，不插入原始 payload。

```json
{"subcategory":"synthetic","attack_content":["合成測試第一輪","合成測試第二輪"]}
```

```json
{
  "risk_subcategory":"synthetic",
  "environment":"合成環境",
  "power_relationship":"測試角色",
  "rounds":[{"round":1,"objective":"測試格式","target_weakness":"測試欄位"}]
}
```

儲存契約目前將 `attack_content` 定義為依序排列、至少一個非空文字的清單；`rounds` 至少一輪，`round` 為從 1 連續遞增的整數。不限制固定三輪。所有文字必須含非空白字元，保留原始文字而不修剪；禁止未知欄位及隱式字串／布林轉型。這些是明示的介面驗證選擇，不代表已確認的研究方法；若既有資料使用逐輪物件，需先確認其契約再擴充。

也先定義後續共用的 `ModelOutput`（`situation`、`query`、非空 `reasoning_steps`、`final_response`）及 `JudgeResult`（`judge_model`、`rationale`、0～10 有限數值 `safety_score`、`SAFE / UNSAFE` 的 `verdict`、`judge_version`）。沒有推理資料時會驗證失敗，不補假資料；推理文字僅指可觀察輸出，不是模型真實內部思維鏈。後續執行紀錄須另存來源資訊。

## C-1 內部儲存 API

資料讀寫由 Python 共用介面提供，B1-1～B1-4 的 HTTP API 皆使用此層；B2-7 等後續模組仍待實作。所有 Repository 方法須在同一 `Database.transaction()` 中呼叫：成功離開提交，任意例外離開回滾。勿在交易內吞掉寫入錯誤後繼續使用交易。

```python
from ai_judge.config import Settings
from ai_judge.contracts import AttackData
from ai_judge.storage.database import Database, create_database_engine
from ai_judge.storage.repository import Repository

db = Database(create_database_engine(Settings()))
try:
    with db.transaction() as connection:
        ids = Repository(connection).add_attacks([
            AttackData(subcategory="synthetic", attack_content=["合成測試"])
        ])
    with db.transaction() as connection:
        record = Repository(connection).get_attack(ids[0])
        assert record.data.subcategory == "synthetic"
finally:
    db.close()
```

| 介面 | 參數／回傳 | 行為及錯誤 |
|---|---|---|
| `create_database_engine(settings)` | `Settings → Engine` | PostgreSQL 連線池、pre-ping、timeout；不立即連線 |
| `Database.transaction()` | context manager，提供 `Connection` | SQLAlchemy 錯誤轉為 `StorageError("Database operation failed")`，不顯示原始 SQL／資料；應用例外回滾後原樣傳遞 |
| `Database.close()` | 無回傳 | 釋放連線池 |
| `Repository.add_template(data)` | `AttackTemplate → UUID` | 保存範本；契約錯誤拋出 `ValidationError` |
| `Repository.add_attacks(data, source_template_id=None)` | `list[AttackData] → list[UUID]` | 批次參數化寫入，先驗證全部資料；空清單回傳 `[]` |
| `Repository.get_template(record_id)` | `UUID → StoredTemplate \| None` | 查無回傳 `None` |
| `Repository.get_attack(record_id)` | `UUID → StoredAttack \| None` | 查無回傳 `None` |
| `Repository.list_attacks(subcategory=None, limit=100, offset=0)` | `list[StoredAttack]` | 類別精確篩選；依建立時間、UUID 穩定排序；limit 1～1000、offset ≥0，超限 `ValueError` |

`StoredTemplate` 包含 `id: UUID`、`data: AttackTemplate`、`created_at: datetime`；`StoredAttack` 另含 `source_template_id: UUID | None`。日期在 PostgreSQL 中含時區。提供來源範本時，需存在且範本 `risk_subcategory` 等於攻擊 `subcategory`，否則 `ReferenceError`。同一範本可關聯多筆攻擊。一般儲存每次產生新 UUID，重複內容仍保存，不暗中去重；未來匯入封裝及去重策略由 B1 模組明示。

## 資料庫與流程

遷移版本：`0002_phase1_jobs`。

| Table | 欄位／索引 |
|---|---|
| `attack_templates` | UUID 主鍵 `id`、`risk_subcategory` 類別索引、原始 `payload JSONB`、`created_at TIMESTAMPTZ` |
| `attacks` | UUID 主鍵 `id`、`subcategory` 類別索引、原始 `payload JSONB`、可空 `source_template_id` 外鍵及索引、`created_at TIMESTAMPTZ` |
| `alembic_version` | Alembic 遷移版本 |
| `attack_jobs` | UUID 主鍵、kind／status、processed／total、result JSONB、created_at／finished_at／expires_at |

來源外鍵使用 `ON DELETE RESTRICT`，避免來源範本被刪除後失去關聯。契約驗證在共用儲存入口執行；直接 SQL 寫入不屬公開介面。後續評測、判定與紀錄資料表待所屬模組落實時以新 migration 加入，不預先猜測未確認研究規則。

已驗證流程：區塊 1 JSONL／範本匯入 → PostgreSQL → 指定類別隨機範本 → GenAI HTTP 測試替身 → 結果驗證保存 → K-DPP → 可追溯結果。區塊 2 多輪測試、區塊 3 Path A/B、區塊 4 統計及報告尚未實作或執行。

## 測試與開發

```sh
source .venv/bin/activate
ruff check ai_judge migrations tests
ruff format --check ai_judge migrations tests
python -m pytest tests/unit -q
docker compose -p ai-judge-c1-test -f compose.test.yaml up -d --wait
AI_JUDGE_TEST_DATABASE_URL=postgresql+psycopg://postgres@127.0.0.1:55432/ai_judge_test python -m pytest -q
docker compose -p ai-judge-c1-test -f compose.test.yaml down
```

測試容器僅綁定 localhost 55432，使用 trust 驗證與 tmpfs 暫存資料，不可作為正式資料庫。整合測試要求資料庫名稱以 `_test` 結尾，每次只建立／清除自己隨機命名的 schema，不清空其他 schema。未設定測試 URL 時整合測試明確顯示 skipped。測試只含合成資料，不使用模型 API 或付費服務。

GitHub Actions 在功能分支 push 及 PR 執行 lint、格式檢查與完整 PostgreSQL 測試。分支採 `feature/* → develop`，正式版本留在 `main`；本區塊完成後建立 PR 並等待檢閱。進度及實際驗證紀錄見 [PROGRESS.md](PROGRESS.md)。

`.env`、私有設定 `config/local/`、`secrets/`、`data/`、`artifacts/`、日誌、權重與 `.venv/` 已忽略。真實資料與憑證應置於上述路徑或環境變數；每次提交仍需人工檢查，不能僅依賴副檔名規則。

尚未完成：B2-1～B2-7、B3A-1～B3A-5、B3B、B4-1～B4-8；研究規則待確認項目維持原計畫第 4.4 節。本次依賴的 Starlette 對 httpx TestClient 發出棄用警告，測試仍可執行，後續依相容版本更新。


## 區塊 1：已完成 API

### B1-1：實際多輪攻擊 JSONL 匯入

`POST /api/v1/attacks/import`，Content-Type 為 `application/x-ndjson`，body 是 UTF-8 JSONL，每行保持原始 `AttackData` 物件，不包裝為 JSON 陣列。接受 UTF-8 BOM、CRLF 及檔尾換行；空白行視為錯誤。禁止重複 JSON key、NaN／Infinity、缺欄位、錯誤型別及未知欄位。整批驗證後以 C-1 在單一交易保存，任一行錯誤整批不寫入；重複內容保留。

```sh
curl -X POST http://127.0.0.1:8000/api/v1/attacks/import \
  -H 'Content-Type: application/x-ndjson' \
  --data-binary @data/synthetic.jsonl
```

成功 201 範例：`{"job_id":"<UUID>","status":"succeeded","elapsed_ms":12,"imported":2,"ids":["<UUID>","<UUID>"],"duplicate_policy":"preserve"}`。`ids` 對應輸入順序；`elapsed_ms` 為此次請求執行時間。

錯誤 422 範例：`{"job_id":"<UUID>","status":"failed","elapsed_ms":3,"error":"invalid_records","details":[{"record":2,"path":["attack_content",0],"type":"string_type"}]}`。`record` 由 1 起算；詳細錯誤不回傳原始資料或 SQL。其他 422 錯誤為 `invalid_utf8`、`invalid_record_count`；過大 body 413 `body_too_large`、Content-Type 不符 415 `unsupported_media_type`、DB 錯誤 503 `storage_unavailable`。這個 API 不呼叫外部模型或 mock。

### 共用操作進度與失敗查詢

`GET /api/v1/attack-jobs/{job_id}`，path 為 UUID，無 body／query。成功 200 回傳 `id: UUID`、`kind: string`、`status: running|succeeded|failed|interrupted`、`processed: integer`、`total: integer|null`、`result: object|null`、`created_at`、`finished_at`、`expires_at`（ISO 8601 日期時間；未完成的 finished_at 為 null）。例如 `{"id":"<UUID>","kind":"attack_import","status":"succeeded","processed":2,"total":2,"result":{"imported":2,"ids":["<UUID>","<UUID>"],"duplicate_policy":"preserve"},"created_at":"...","finished_at":"...","expires_at":"..."}`。查無 404 `{"error":"job_not_found"}`；UUID 格式不合法 422 FastAPI validation detail；DB 失敗 503 `{"error":"storage_unavailable"}`。不呼叫外部 API／mock。

呼叫 POST 可選用 `X-Job-ID: <client-generated UUID>`；同一 ID 再次請求回傳 409 `{"job_id":"<UUID>","error":"job_id_exists"}`，不重複執行。這讓呼叫者在 POST 尚未結束時用已知 ID 從另一連線查進度；未指定則由伺服器產生並在結果回傳。這是同步完成的 bounded request API，DB 與解析工作放在執行緒池，不阻塞其他 API。`processed` 是已驗證筆數，不代表已提交；每 100 筆及結尾更新。

新增遷移 `0002_phase1_jobs` 及 `attack_jobs` 表，保存上述操作紀錄；成功資料及成功紀錄原子提交。程序中斷或 DB 全面故障時，running 任務在 10 分鐘期限後被查詢時標為 interrupted，不自動重跑。無背景工作佇列或自動復原重試；失敗需檢查紀錄後明確提交新 ID。

設定：`AI_JUDGE_PHASE1_MAX_BODY_BYTES` 預設 2,000,000（最多 20,000,000）；`AI_JUDGE_PHASE1_MAX_IMPORT_RECORDS` 預設 1,000（最多 10,000）。目前適合受限批次，較大量資料需拆批；不讀取使用者伺服器檔案路徑。

內部介面：`Importer(Operations(database), Phase1Settings()).attacks(raw: bytes, job_id: UUID|None) -> (http_status, result_dict)`；`Operations.get(job_id) -> job_dict|None`；所有資料及進度寫入皆經 `Repository` 與 `Database.transaction()`。


### B1-2：多輪攻擊範本匯入

`POST /api/v1/attack-templates/import`，Content-Type 為 `application/json`，無 query／path 參數；可選 `X-Job-ID`。body 可為原始單筆 `AttackTemplate`（上方資料契約範例），或 `[AttackTemplate, ...]` 陣列作批次封裝，不修改物件內欄位。成功 201 回傳與 B1-1 相同的 `job_id/status/elapsed_ms/imported/ids/duplicate_policy`；ids 為範本 UUID。例如 `{"job_id":"<UUID>","status":"succeeded","elapsed_ms":8,"imported":1,"ids":["<UUID>"],"duplicate_policy":"preserve"}`。

輪次必須從 1 開始且連續、不能重複或顛倒，不限定三輪。任一項無效整批不保存；重複範本保留為新 UUID。錯誤狀態同 B1-1（409／413／415／422／503）；無效 JSON 使用 `invalid_json`，資料契約錯誤使用 `invalid_records`，details 的 record 表示陣列第幾筆（單筆為 1），path 例如 `["rounds"]`。`kind=template_import` 的進度及失敗可由共用 GET 操作介面查詢。不呼叫模型或外部 API。

內部介面：`Importer.templates(raw: bytes, job_id: UUID|None) -> (http_status, result_dict)`；`Repository.add_templates(list[AttackTemplate]) -> list[UUID]` 為 C-1 的參數化批次保存擴充，沿用現有 attack_templates 表，不新增 migration。body／筆數限制及交易、重複操作政策與 B1-1 相同。


### B1-3：依指定類別的隨機範本生成攻擊資料

`POST /api/v1/attacks/generate`，Content-Type `application/json`，body 為 `{"risk_subcategory":"synthetic"}`，無 query／path 參數，可選 `X-Job-ID`。以資料庫參數化篩選及 `ORDER BY random() LIMIT 1` 選擇該類別範本；交易結束後才呼叫外部 API，不長時間佔用 DB 連線。回傳經驗證的資料後，再以單一 C-1 交易保存攻擊、來源範本關聯及成功紀錄。

成功 201 schema／範例：`{"job_id":"<UUID>","status":"succeeded","elapsed_ms":25,"id":"<attack UUID>","data":{"subcategory":"synthetic","attack_content":["合成測試"]},"generation":{"provider":"openai_compatible","model":"configured-model","temperature":0.7,"mock":false,"prompt_sha256":"<SHA256>","timeout_seconds":30,"max_attempts":1,"source_template_id":"<template UUID>","provider_elapsed_ms":20}}`。data 保持原始兩欄結構；生成類別必須與範本相同，訊息數須等於範本輪數。

錯誤：404 `no_template_candidates`（不呼叫供應商）；503 `generation_disabled`／`generation_not_configured`／`storage_unavailable`；429 `generation_busy`（本程序並行上限）；504 `provider_timeout`；502 `provider_http_error`／`provider_connection_error`／`provider_response_too_large`／`provider_refused`／`provider_incomplete_output`／`invalid_generated_output`／`generated_category_mismatch`／`generated_round_count_mismatch`。上述結果使用共用 `job_id/status/elapsed_ms/error/details` 格式，來源 UUID、模型參數及呼叫耗時會記在生成失敗的 details；供應商 HTTP 失敗僅保存狀態碼，不回傳供應商原文、憑證或完整提示。request 型態不符回傳 FastAPI 422 validation detail；重複 ID 409。

`kind=generation` 的進度為 0/1 或 1/1。錯誤不保存攻擊、不當作成功、也不切換 mock。每次只有一次供應商請求（max_attempts=1，無自動重試），避免重複付費。客戶端斷線時伺服器可能仍完成操作，應使用原 X-Job-ID 查詢，不直接用新 ID 重試。

| 設定 | 預設／說明 |
|---|---|
| `AI_JUDGE_GENAI_ENABLED` | false；須明確啟用 |
| `AI_JUDGE_GENAI_PROVIDER` | openai_compatible；此階段只有這個正式 adapter |
| `AI_JUDGE_GENAI_BASE_URL` | 無預設，需包含供應商 API 根路徑如 `/v1`，會加上 `/chat/completions` |
| `AI_JUDGE_GENAI_API_KEY` | 無預設，SecretStr；僅放本機 .env／環境變數 |
| `AI_JUDGE_GENAI_MODEL` | 無預設，必填的實際模型名稱 |
| `AI_JUDGE_GENAI_SYSTEM_PROMPT` | 程式內的合成測試 JSON 輸出提示；可覆寫，紀錄 SHA256 |
| `AI_JUDGE_GENAI_TIMEOUT_SECONDS` | 30 秒，1～60；HTTP timeout 與接收迴圈耗時檢查 |
| `AI_JUDGE_GENAI_TEMPERATURE` | 0.7，0～2，僅初始工程參數，非已驗證研究設定 |
| `AI_JUDGE_GENAI_MAX_RESPONSE_BYTES` | 1,000,000，限制回應大小 |
| `AI_JUDGE_GENAI_MAX_CONCURRENCY` | 2，每程序最多同時呼叫數 |

adapter 使用共享 httpx client，不跟隨 HTTP redirect、不讀代理環境變數；端點只能從受信任本機設定提供，不能由 API request 指定。上線時請使用 HTTPS；API 本身供授權的內部／本機環境使用。供應商需支援 messages、temperature、JSON object response_format 及完整的 choices/message/finish_reason 回傳；參考 [Chat Completions 官方介面](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create)。不相容或截斷回應會明確失敗，不猜測內容。

內部可替換介面：`Generator.generate(AttackTemplate) -> AttackData`、`Generator.metadata() -> dict`；`GenerationService(operations, generator).generate(GenerationRequest, job_id=None)`。單元測試使用 HTTP transport 替身及注入 Generator，不提供生產環境假資料 fallback。真實供應商、模型及提示版本仍待專案設定確認；本次未進行付費 API 呼叫。`ORDER BY random()` 對極大量範本有掃描成本，受 DB statement timeout 保護。


### B1-4：固定數量 K-DPP 多樣性抽樣

`POST /api/v1/attacks/sample`，Content-Type `application/json`，無 query／path 參數，可選 `X-Job-ID`。body：`{"k":2,"subcategory":"synthetic","seed":42}`。k 為 1～500 的整數（不接受 bool）；subcategory 可省略／null 表示所有類別；seed 為 0～2^63−1 的整數，可省略，由系統生成並記錄。相同資料庫候選快照、設定、seed 與數值運算環境下可重現。

成功 201：`{"job_id":"<UUID>","status":"succeeded","elapsed_ms":15,"samples":[{"id":"<attack UUID>","data":{"subcategory":"synthetic","attack_content":["合成文字"]}}],"sampling":{...}}`，samples 實際恰好 k 筆且 UUID 唯一，每筆 data 維持原始兩欄。`sampling` 包含完整設定、seed、`algorithm=spectral-k-dpp-v1`、`rng=PCG64`、NumPy 版本、表示法／正規化／hash、k、類別篩選、依序排列的所有 candidate_ids、候選 payload 的 SHA256；保存於 `kind=sampling` 的 job result，供區塊 2 載入及重現。上述例子只示意單筆元素形狀。

錯誤：422 `insufficient_candidates`／`candidate_limit_exceeded`／`candidate_text_too_long`／`empty_representation`／`invalid_representation`／`invalid_kernel`／`non_symmetric_kernel`／`non_psd_kernel`／`insufficient_kernel_rank`／`kernel_eigendecomposition_failed`／`unstable_eigenvector_selection`／`unstable_projection`；429 `sampling_busy`；409 重複 job ID；503 儲存失敗。請求欄位非法回傳 FastAPI 422。錯誤使用共用 job/error/details 結構，核矩陣或表示法失敗 details 保存抽樣設定及候選快照，不回退成普通隨機抽樣。此 API 不呼叫外部 API 或模型／mock。

候選由 PostgreSQL 依 `created_at, id` 排序讀取；超過上限會拒絕，請先用類別縮小範圍，不偷偷只選前 N 筆。輸入表示為每筆 attack_content 依序以換行連接，不將類別名稱加入文字。預設對 NFKC／casefold 文字做固定 blake2b 雜湊、有正負號的字元 n-gram 計數及 L2 正規化；這是可替換的文字特徵，不是已訓練的語意 embedding，可能有雜湊碰撞，並非已確認的最佳研究方法。

kernel 可選 `linear: S=XXᵀ` 或 `rbf: Sᵢⱼ=exp(-gamma*||xᵢ-xⱼ||²)`；`Lᵢⱼ=qᵢ Sᵢⱼ qⱼ`，品質權重 q 由類別設定，未設定為 1，0 表示無抽中權重。依 [Kulesza 與 Taskar 的 k-DPP 方法](https://www.alexkulesza.com/pubs/dpps_fnt12.pdf) 以特徵分解、log 空間 elementary symmetric polynomial、條件特徵向量選擇與投影 DPP 抽樣，固定大小集合機率正比於 `det(L_Y)`。這不是 greedy 最大化或一般隨機抽樣。

數值限制：核先做等比例縮放，對稱性／PSD／rank 均檢查；相對 eigen_tolerance 以下的特徵值視為數值零。因此是浮點精度下的 spectral k-DPP，不宣稱無誤差的實數運算。沒有自動加 jitter，重複／線性相依資料可能造成 rank < k 而失敗。6000 個固定 seed 的小矩陣測試比較實際頻率與各子集行列式理論機率；另驗證完全相同候選不會同時抽中。

| `AI_JUDGE_SAMPLING_` 設定後綴 | 預設／範圍 |
|---|---|
| `REPRESENTATION` | hashed_char_ngram_v1；其他 encoder 可透過 Python 介面注入 |
| `DIMENSIONS`／`NGRAM` | 256（16～4096）／3（1～5） |
| `KERNEL`／`GAMMA` | rbf（或 linear）／1.0（>0 且 ≤100） |
| `QUALITY_BY_SUBCATEGORY` | JSON object `{}`，如 `{"synthetic":1.2}`，有限數值 0～1000 |
| `EIGEN_TOLERANCE` | 1e-10（1e-14～1e-4） |
| `MAX_CANDIDATES` | 500（最多 500）；稠密特徵分解 O(N³)、記憶體 O(N²) |
| `MAX_TEXT_CHARACTERS` | 10000（最多 100000）；超長拒絕，不截斷 |
| `MAX_CONCURRENCY` | 1（最多 4），每程序計算併行上限 |

內部介面：`sample_k_dpp(kernel, k, seed, tolerance) -> list[int]`；`SamplingService(operations, settings, encoder=None).sample(SamplingRequest, job_id=None)`；可替換 `Encoder.encode(list[str]) -> ndarray` 與 `metadata() -> dict`。結果與設定保存於既有 attack_jobs，不新增資料庫 migration。計算在同步路由的執行緒池中，操作進度為 0/k（計算中）或 k/k（完成），不提供誤導性的逐樣本假進度。固定 seed 不保證跨 BLAS／平台或 NumPy 版本產生完全相同索引。


## 區塊 1 驗收與範圍

本機完整測試為 104 passed（97 單元、7 PostgreSQL 整合），涵蓋四模組流程、升級保留既有資料、整批失敗回滾、進度併行查詢、重複 ID 防護及重新連線後保存。OpenAPI 列出各成功回應與錯誤 schema。只有既有的 Starlette/httpx TestClient 棄用警告。

真實付費 GenAI 未呼叫；HTTP protocol 以 transport 替身驗證，資料庫則為 PostgreSQL 17。未宣稱完成區塊 2～4 或全專案端到端驗收。操作紀錄尚無自動清理政策；對外部署存取控制、備份及分散式工作佇列不屬本次交付。後端維持本機 .venv，compose.test.yaml 僅提供測試 PostgreSQL。

區塊 PR：[PR #2](https://github.com/nn310831/Project_Ai_judge/pull/2)，目標 develop，依賴共同區塊 PR #1，等待檢閱。

共用儲存新增的內部介面還包括 `Repository.random_template(risk_subcategory) -> StoredTemplate|None`、`start_job(id, kind) -> bool`、`update_job_progress(id, processed, total)`、`finish_job(id, status, result)`、`get_job(id) -> dict|None`；均須在 C-1 交易內使用。start_job 以主鍵衝突安全插入，finish_job 只允許從 running 轉為終止狀態，避免重複完成或覆蓋結果。


## 區塊 2：受測模型（逐模組交付）

後續 E2E-1 將直接呼叫本區塊內部 Service；Service 不依賴 FastAPI Request／Response、不以自身 HTTP 串接。區塊 2 先提供 Ollama，其他 provider 僅預留 registry 擴充。

### B2-1：標準化模型設定

本區塊所有 HTTP API 要求 `Authorization: Bearer <AI_JUDGE_TARGET_API_TOKEN>`；token 僅存本機環境，不進資料庫。未設定 token 回傳 503 `target_api_not_configured`；缺少／錯誤 token 回傳 401 `unauthorized`。部署前以環境變數設定 token，並設定 `AI_JUDGE_TARGET_ALLOWED_BASE_URLS` JSON 字串陣列（預設 `["http://127.0.0.1:11434"]`）。BASE API 必須精確符合允許清單，禁止 URL 內含憑證、query、fragment。這是授權的內部管理入口；不開放匿名任意外部端點。

- `POST /api/v1/target-models/config/ollama`：body `{"provider":"ollama","base_url":"http://127.0.0.1:11434","model":"your-model:tag","parameters":{"temperature":0.7,"top_p":0.9,"num_predict":2048}}`；無 path/query。201 回傳 `{"model_config_id":"<UUID>","configuration":{...完整生效設定...}}`。
- `GET /api/v1/target-models/config/ollama/{model_config_id}`：UUID path、無 body/query；200 回傳相同 schema。查無 404 `{"error":"model_config_not_found"}`。
- POST／GET 不做任何模型推論。配置只建立不可變的新 ID，不提供原地修改。端點不允許 403 `endpoint_not_allowed`；非法參數／provider 回傳 422 FastAPI validation detail。這些設定不含 API Key。

設定欄位：provider 固定 ollama、base_url／model 必填非空字串、model_version 可選；timeout_seconds 預設 30（1～60 秒）、context_max_characters 預設 24000（512～256000）、window_turns 預設 6（1～100）、max_response_bytes 預設 1000000（100～5000000）。parameters 白名單：temperature 0～2（預設 .7）、top_p >0 且 ≤1（.9）、top_k 1～200（40）、num_predict 1～8192（2048）、num_ctx 512～131072（8192）、seed -1～2^31−1（0）；num_predict 必須小於 num_ctx。不接受未知參數或 bool 冒充整數。這些上限為工程限制，不是已確認研究設定。

內部 `ConfigurationService(database, TargetSettings).create(TargetConfig) -> UUID`、`.get(UUID) -> TargetConfig`；經 C-1 `TargetRepository` 保存。新增 migration `0003_target_configs`／target_configs（UUID、payload JSONB、created_at）。token 是整個管理 API 的共享授權，尚非多租戶 ACL。


### B2-2：載入抽樣快照與 Ollama Adapter

`POST /api/v1/target-models/load/ollama`（需 Bearer token），body `{"model_config_id":"<UUID>","sampling_job_id":"<successful B1-4 job UUID>"}`，無 query/path。201 回傳 `{"load_id":"<UUID>","model_config_id":"<UUID>","sampling_job_id":"<UUID>","case_count":10}`。只載入並保存設定與抽樣快照，不重新抽樣、不呼叫推論。

404：model_config_not_found／sampling_job_not_found；422：invalid_sampling_job（非 sampling 或未成功）、invalid_sampling_snapshot（格式、重複 ID 或 k／案例數不符）、too_many_cases／too_many_rounds／unsupported_provider；403：端點不在允許清單；401／503 授權規則同 B2-1。領域錯誤形狀為 `{"error":"code"}`；UUID／輸入型態錯誤使用 FastAPI 422 detail。case／round 上限由 AI_JUDGE_TARGET_MAX_CASES（預設 500，最多 500）及 MAX_ROUNDS_PER_CASE（預設 100，最多 1000）管理。

內部 `LoadingService.load_job(LoadRequest) -> UUID`、`.load_snapshot(model_config_id, SamplingSnapshot, sampling_job_id=None) -> UUID`、`.get(load_id) -> LoadedTarget`。直接快照入口供後續 Orchestrator 使用，兩者均驗證同一份資料契約；快照包含完整 AttackData、UUID、抽樣設定及生效模型設定，不因呼叫端後續修改而變動。新增 migration 0004_target_loads／target_loads，以外鍵關聯設定並保存 JSONB 快照。

`AdapterRegistry.resolve(provider) -> TargetAdapter` 保留其他架設方法擴充；目前只有 Ollama。`TargetAdapter.chat(TargetConfig, messages) -> TargetReply` 與業務層分離。Ollama 使用 `/api/chat`、stream=false、四欄 JSON schema 與白名單 options，參考 [Ollama API](https://docs.ollama.com/api/chat) 及 [structured outputs](https://docs.ollama.com/capabilities/structured-outputs)。共享 httpx client，拒絕 redirect，設定 timeout／回應上限，失敗不自動重試（每輪最多一次）。錯誤包括 target_timeout、target_http_error、target_connection_error、target_response_too_large、target_provider_error、target_incomplete_output、target_refused、target_empty_output、invalid_target_envelope。未做真實 Ollama 呼叫；HTTP transport 替身驗證 protocol。


### B2-4：上下文與 Sliding Window

內部 `ConversationContext(sliding_window, window_turns, max_characters).prepare(query) -> ContextRequest`，回傳 messages、dropped_turns、context_characters；`.complete(query, public_response)` 只加入成功輪次。每個案例建立獨立物件。B2-3 將以單一 sliding_window 布林開關使用此模組（預設 false），不另外增加 HTTP endpoint。

啟用時只保留最近 window_turns 組完整 user／assistant 歷史；若超過字元預算再移除最舊完整對話。不刪 system prompt、不截斷當輪 query、不額外呼叫模型做摘要。關閉時保留全部歷史，超限明確失敗 `context_limit_exceeded`。歷史清空仍放不下當輪內容也會失敗。字元預算計算 role 與 content 長度，屬工程保護，不宣稱等同 tokenizer 的 token 數；Ollama num_ctx 另外限制模型 context。來源輸出要求為可觀察的公開說明，不要求模型私有內部思維鏈。


### B2-5：統一模型公開輸出

內部 `normalize_public_output(str|dict|ModelOutput) -> ModelOutput`、`normalize_reply(TargetReply) -> NormalizedReply`。Adapter 先轉換供應商 envelope，再由此層驗證原始四欄 situation/query/reasoning_steps/final_response；HTTP 與 Python mapping 得到一致結果，不新增 endpoint。保留 provider／model／mock 於外層中繼資料，不改原始四欄。缺少或空 reasoning_steps 回報 missing_reasoning_data；其他 JSON／型態／未知欄位／空內容錯誤回報 invalid_model_output。拒絕重複 JSON key、NaN、Markdown 包裝及自行猜測欄位，不補造 SAFE 或推理內容；由 runner 保存失敗。
