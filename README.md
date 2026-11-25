# AI Judge 後端

依據 [實作計畫](CODEX_IMPLEMENTATION_PLAN.md) 分區塊交付。共同區塊 C-1 已完成；區塊 1 正在逐模組交付（下方列出已完成 API）。區塊 2～4 尚未實作，沒有前端。

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

本區塊不呼叫 GenAI 或其他模型，沒有正式模型或 mock 開關。SQLite 僅用於單元測試替身；正式環境只接受 PostgreSQL。區塊 2 mock 預設停用、Path A mock 預設停用、Path B mock 預設啟用的要求，留待各區塊實作。

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

資料讀寫目前為 Python 內部介面，尚無對外資料匯入 HTTP endpoint；未來 B1-1、B1-2、B1-3 及 B2-7 等使用此層。所有 Repository 方法須在同一 `Database.transaction()` 中呼叫：成功離開提交，任意例外離開回滾。勿在交易內吞掉寫入錯誤後繼續使用交易。

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

來源外鍵使用 `ON DELETE RESTRICT`，避免來源範本被刪除後失去關聯。契約驗證在共用儲存入口執行；直接 SQL 寫入不屬公開介面。後續評測、判定與紀錄資料表待所屬模組落實時以新 migration 加入，不預先猜測未確認研究規則。

目前流程：資料契約驗證 → 交易 → Repository 批次保存／讀取 → PostgreSQL。後續依計畫為區塊 1 匯入／生成／K-DPP → 區塊 2 多輪測試 → 區塊 3 Path A/B → 區塊 4 統計及報告，本次未執行這些流程。

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

尚未完成：B1-3～B1-4、B2-1～B2-7、B3A-1～B3A-5、B3B、B4-1～B4-8；研究規則待確認項目維持原計畫第 4.4 節。本次依賴的 Starlette 對 httpx TestClient 發出棄用警告，測試仍可執行，後續依相容版本更新。


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
