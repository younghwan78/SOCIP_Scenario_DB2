# Import Workbench Plan

## Decision

Import Workbench는 필요하다. 다만 1차 목표는 "DB 편집 UI"가 아니라
"legacy/import 결과를 검토하고 Write API staging으로 넘기는 보조 화면"이다.

현재 repo에는 이미 아래 경로가 있다.

- Legacy YAML -> canonical YAML: `scenario_db.legacy_import.cli`
- Canonical YAML -> Write API payload: `scenario_db.legacy_import.write_bundle`
- Write API: `stage -> validate -> diff -> apply`
- Viewer: DB에 올라간 scenario/variant 확인

따라서 Workbench는 새 truth source를 만들지 않는다. canonical YAML 또는
`scenario.import_bundle` payload만 만들고, 실제 DB 변경은 Write API `apply`만
수행한다.

## Scope Boundary

### In Scope

- Legacy YAML path 입력 또는 generated canonical directory 입력.
- Importer 실행 또는 기존 generated output 재사용.
- `import_report.json` 요약 표시.
- Generated canonical YAML 문서 목록 표시.
- Write API import bundle 생성.
- Write API `stage`, `validate`, `diff` 호출.
- `validation.issues`, `import_report`, `diff.impact` 표시.
- 사용자가 명시적으로 누른 경우에만 `apply`.
- Apply 후 scenario/variant read link 또는 viewer 이동 안내.

### Out Of Scope For First Version

- Browser 기반 YAML 직접 편집.
- Excel/CSV/Markdown table import.
- Visio/diagram import.
- Multi-user approval workflow.
- DB row direct editing.
- Resolver/Gate Engine 전용 화면.

Excel/CSV/Markdown import는 나중에 source adapter로 추가한다. 첫 버전에서
같이 넣으면 legacy YAML import 안정화보다 UI 예외 처리에 시간이 더 들어간다.

## Target Workflow

```mermaid
flowchart TD
    A["Legacy YAML paths<br/>hw / sensor / display / scenario"] --> B["Legacy Importer CLI"]
    B --> C["Generated canonical YAML<br/>00_hw / 02_definition"]
    B --> D["import_report.json"]
    C --> E["write_bundle builder"]
    D --> E
    E --> F["scenario.import_bundle payload"]
    F --> G["Write API stage"]
    G --> H["Validate"]
    H --> I["Diff Preview"]
    I --> J{"User confirms apply?"}
    J -- "No" --> K["Keep staged batch for review"]
    J -- "Yes" --> L["Apply to PostgreSQL"]
    L --> M["Read API / Viewer"]
```

## UI Layout

Streamlit page: `dashboard/pages/2_Import_Workbench.py`

Recommended layout is vertical, not tab-heavy. Import is a step-by-step review
flow and should show state from top to bottom.

### Section 1. API And Workspace

Inputs:

- `API Base`: default from `SCENARIODB_API_BASE`, fallback `http://127.0.0.1:18000/api/v1`
- `Generated Output Directory`
- `Actor`
- `Note`

Status:

- API health check result.
- Whether generated directory exists.
- Whether `import_report.json` exists.

### Section 2. Source Mode

Mode A: Use existing generated canonical directory.

- User already ran importer.
- Workbench only builds bundle and stages it.

Mode B: Run legacy importer from paths.

- `hw_config/projectA_hw.yaml`
- `hw_config/sensor_config.yaml`
- optional `hw_config/display_config.yaml`
- one of:
  - single scenario YAML
  - scenario directory
  - scenario group files
- output directory
- project ID/name
- SoC ID
- strict / fail-on-warning checkboxes

First implementation can start with Mode A. Mode B is useful but needs safe
path handling and clearer command preview.

### Section 3. Import Report Preview

Show:

- `ok`
- generated counters
- messages grouped by `error`, `warning`, `info`
- source path, code, message

Rules:

- Error messages block `apply`.
- Warning messages do not block staging, but must remain visible.
- Unsupported generated document kinds from `write_bundle` are shown as errors.

### Section 4. Canonical Document Preview

Show one table:

| kind | id | path | status |
| --- | --- | --- | --- |
| ip | ip-isp-v12 | 00_hw/ip-isp-v12.yaml | included |
| project | proj-projectA | 02_definition/proj-projectA.yaml | included |
| scenario.usecase | uc-camera-recording | 02_definition/uc-camera-recording.yaml | included |

Click/expand for YAML/JSON preview is optional. First version only needs a
safe `st.code` preview for selected document.

### Section 5. Bundle And Stage

Actions:

1. Build `scenario.import_bundle` payload.
2. Save to output path, e.g. `generated/scenariodb/import_bundle.json`.
3. Call `POST /write/staging`.

Show:

- `batch_id`
- `target_id`
- staged status

### Section 6. Validate And Diff

Actions:

1. `POST /write/staging/{batch_id}/validate`
2. `POST /write/staging/{batch_id}/diff`, only when validation is valid

Show validation:

- `valid`
- issue table: severity, code, path, message
- import report summary from Write API response

Show diff:

- operation: create/update
- document changes
- scenario impacts:
  - scenario id
  - operation
  - variant count before/after
  - variants added
  - variants removed
  - variants updated

### Section 7. Apply

Apply button rules:

- Disabled unless `validation.valid == true`.
- Disabled unless `diff` was generated.
- Button label must be explicit: `Apply to DB`.
- Show warning text before button:
  - "This writes canonical tables through Write API apply."

After apply:

- Show `applied_refs`.
- Show viewer link inputs:
  - scenario ID
  - variant ID candidates from diff or imported document

## Software Components

### Existing Components To Reuse

- `scenario_db.legacy_import.cli.main`
- `scenario_db.legacy_import.write_bundle.build_import_bundle_request`
- `dashboard/Home.py`
- existing `requests` usage pattern from Pipeline Viewer page
- Write API endpoints

### New Components

```text
dashboard/pages/2_Import_Workbench.py
  - Streamlit page
  - imports source paths / generated dir
  - calls Python utility functions directly where safe
  - calls Write API through requests

dashboard/components/import_workbench_client.py
  - optional helper module
  - stage/validate/diff/apply wrappers
  - keeps page code small

tests/unit/test_import_workbench_payload.py
  - optional pure tests for report/document table conversion
```

For the first implementation, keep API client helpers small. Avoid adding a new
framework or frontend build.

## Implementation Steps

### Step 7A. Workbench Plan And Contract

Output:

- `docs/import-workbench-plan.md`
- Update `README.md` or dashboard section later after implementation.

Acceptance:

- Scope explicitly says Workbench is not a direct DB editor.
- It uses `scenario.import_bundle`.

### Step 7B. API Client Helper

Add:

- `dashboard/components/import_api_client.py`

Functions:

- `stage_import_bundle(api_base: str, payload: dict) -> dict`
- `validate_batch(api_base: str, batch_id: str) -> dict`
- `diff_batch(api_base: str, batch_id: str) -> dict`
- `apply_batch(api_base: str, batch_id: str) -> dict`
- `get_batch(api_base: str, batch_id: str) -> dict`

Rules:

- Use `requests`.
- Surface HTTP errors as readable `{status_code, text}` messages.
- Do not hide Write API validation issues.

### Step 7C. Generated Directory Mode

Add:

- `dashboard/pages/2_Import_Workbench.py`

Features:

- Input generated dir.
- Build bundle via `build_import_bundle_request`.
- Show import report and document list.
- Save bundle JSON optionally.
- Stage to Write API.

Acceptance:

- User can take `generated/scenariodb` and create a Write API batch without CLI.
- Unsupported documents appear in UI before staging.

### Step 7D. Validate/Diff/Apply Flow

Features:

- Validate current batch.
- Render validation issue table.
- Render diff impact.
- Apply only after valid diff.

Acceptance:

- A generated import bundle can be staged, validated, diffed, applied from UI.
- `apply` is disabled or guarded when validation fails.

### Step 7E. Importer Run Mode

Add optional importer execution from UI.

Implementation choice:

- Prefer command preview first.
- Then allow run via `scenario_db.legacy_import.cli.main(args)` inside Python.

Inputs:

- hw path
- sensor path
- display path
- scenario path OR scenario dir OR scenario group
- project/soc fields
- strict/fail-on-warning

Acceptance:

- Running importer from Workbench produces the same files as CLI.
- Errors are shown from `import_report.json`.

### Step 7F. Pilot With Real Legacy YAML

Use a copy of one real internal scenario set.

Checklist:

- HW catalog generated.
- Sensor catalog generated.
- Display catalog generated if available.
- Scenario usecase generated.
- Bundle stages.
- Validation passes or gives actionable issue codes.
- Diff shows scenario and variant impact.
- Apply succeeds.
- Viewer can load the applied scenario/variant.

## Test Plan

### Unit Tests

- `write_bundle` already tested.
- Add helper tests for:
  - issue table conversion
  - document list extraction
  - disabled apply state when invalid

### Integration Tests

- Existing Write API integration already covers `scenario.import_bundle`.
- Add one dashboard helper test only if helper logic becomes non-trivial.

### Manual Smoke Test

```powershell
cd E:\50_Codex_Soc_Scenario_DB\implementation
$env:DATABASE_URL="postgresql+psycopg2://scenario_user:scenario_pass@localhost:5432/scenario_db"
uv run uvicorn scenario_db.api.app:app --host 127.0.0.1 --port 18000
```

In another shell:

```powershell
$env:SCENARIODB_API_BASE="http://127.0.0.1:18000/api/v1"
uv run --group dashboard streamlit run dashboard\Home.py --server.port 18502 --server.address 127.0.0.1
```

Open:

```text
http://127.0.0.1:18502/Import_Workbench
```

## Risk And Mitigation

| Risk | Mitigation |
| --- | --- |
| UI becomes a second DB editor | Only generate bundle and call Write API. No direct DB writes. |
| Importer path handling differs between Windows and Ubuntu | Use `pathlib.Path`; document Ubuntu paths separately if needed. |
| Users apply warning-heavy imports too easily | Show warning count and message table before apply. |
| Unsupported source formats expand scope | Keep Excel/CSV/Markdown as later source adapters. |
| Generated docs include unsupported kinds | `write_bundle` reports unsupported kind and marks import report `ok=false`. |
| Apply modifies existing scenario unexpectedly | Diff impact must show variants added/removed/updated before apply. |

## Recommendation

Proceed with Step 7B -> 7C -> 7D first. This gives a useful Workbench without
waiting for Excel/CSV/Markdown parser design.

After one real internal legacy import succeeds end-to-end, decide whether Step
7E importer execution from UI is worth adding. In many server environments,
operators may prefer running importer CLI separately and using Workbench only for
review/staging/apply.
