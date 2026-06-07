# CDGM Import Guide

이 문서는 ScenarioDB에 CDGM(camera DVFS guide module) 입력 데이터를 import하는
방법을 설명한다. 현재 구현 기준으로 CDGM import는 두 종류의 데이터를 분리해서
다룬다.

| 데이터 | 위치 | Import 방법 |
| --- | --- | --- |
| CDGM role mapping | `ip_catalog.capabilities.sim.cdgm_roles` | `ip` YAML에 포함해서 Import Workbench `Canonical Bundle` tab으로 import |
| CDGM profile/override | `soc.cdgm_profile` | Import Workbench `CDGM Profile` tab에서 YAML/JSON file upload |

`RT_ISP`, `MFC_MFD` 같은 값은 물리 IP가 아니라 CDGM 계산 role이다. 따라서 별도
`ip_catalog` row를 만들지 말고, 기존 물리 IP의 `cdgm_roles` 또는
`soc.cdgm_profile.role_overrides`로 표현한다.

## 1. 준비

서버 실행:

```powershell
cd E:\50_Codex_Soc_Scenario_DB\implementation

docker compose up -d postgres pgadmin

$env:DATABASE_URL="postgresql+psycopg2://scenario_user:scenario_pass@localhost:15432/scenario_db"
uv run alembic upgrade head

uv run uvicorn scenario_db.api.app:app --host 127.0.0.1 --port 18000
```

Streamlit:

```powershell
cd E:\50_Codex_Soc_Scenario_DB\implementation

$env:DATABASE_URL="postgresql+psycopg2://scenario_user:scenario_pass@localhost:15432/scenario_db"
$env:SCENARIODB_API_BASE="http://127.0.0.1:18000/api/v1"
uv run --group dashboard streamlit run dashboard\Home.py --server.port 18502 --server.address 127.0.0.1
```

URLs:

- FastAPI: `http://127.0.0.1:18000/docs`
- Import Workbench: `http://127.0.0.1:18502/Import_Workbench`
- pgAdmin: `http://127.0.0.1:15050`

## 2. Import 대상 구분

### 2.1 `cdgm_roles`

`cdgm_roles`는 물리 IP가 CDGM `arch_info`에 어떤 row로 나가는지 정의한다. 이 값은
`ip` document의 일부이므로 `CDGM Profile` tab이 아니라 `Canonical Bundle` tab으로
import한다.

예시:

```yaml
id: ip-isp-v12
schema_version: "2.3"
kind: ip
category: camera
hierarchy:
  type: simple
capabilities:
  operating_modes:
    - id: normal
  sim:
    hw_name: ISP
    cdgm_roles:
      RT_ISP:
        arch_ip: RT_ISP
        path_type: rt
        ppc: 8.0
        vdd: VDD_CAM
        dvfs_domain: CAM
        source:
          kind: native
          ref: cdgm_arch_info.RT_ISP

      ISP:
        arch_ip: ISP
        path_type: nrt
        ppc: 4.0
        vdd: VDD_CAM
        dvfs_domain: ISP
        pos:
          - STEP1
          - STEP2
          - STEP3
        source:
          kind: native
          ref: cdgm_arch_info.ISP
```

중요한 점:

- `RT_ISP`는 `ip-isp-*` 내부 role로 둔다.
- `pos`는 `STEP1+STEP2+STEP3` 문자열보다 배열을 권장한다.
- `dvfs_domain`은 CDGM resolve 시 선택한 `soc.dvfs_table.domains` key와 맞아야 한다.

### 2.2 `soc.cdgm_profile`

`soc.cdgm_profile`은 scenario/codec/FPS/HDR/sensor 조건에 따라 달라지는 CDGM
override를 담는다. Workbench의 `CDGM Profile` tab은 이 문서 하나를 file upload로
받아 `scenario.import_bundle`을 만든다.

샘플 파일:

```text
demo/cdgm_profiles/cdgm-prof-soc-exynos2500-v1.yaml
```

샘플 내용:

```yaml
id: cdgm-prof-soc-exynos2500-v1
schema_version: "2.3"
kind: soc.cdgm_profile
soc_ref: soc-exynos2500
profile_version: 1
evt_hint: EVT0
compatibility_scope: soc
domain_schema_hash: cam-isp-intcam-mfc-v1
source:
  guide_name: camera_dvfs_guide
  source_revision: arch-info-r1
  path: demo/cdgm_profiles/cdgm-prof-soc-exynos2500-v1.yaml
  note: Demo CDGM profile for Workbench file import.
role_overrides:
  MFC_MFD:
    ip_ref: ip-mfc-v14
    arch_ip: MFC_MFD
    path_type: codec
    ppc: 4.0
    vdd: VDD_INT
    dvfs_domain: MFC
    when:
      scenario_domain: camera
      codec_flow: decode

  MFC_MFD_UHD60_HLG:
    extends: MFC_MFD
    ip_ref: ip-mfc-v14
    arch_ip: MFC_MFD_UHD60_HLG
    path_type: codec
    ppc: 6.0
    vdd: VDD_INT
    dvfs_domain: MFC
    when:
      scenario_domain: camera
      resolution_class: UHD
      fps: 60
      hdr_format: HLG
selection_policy:
  default_profile: true
```

## 3. Workbench로 CDGM profile import

1. `http://127.0.0.1:18502/Import_Workbench`를 연다.
2. Step 1에서 `CDGM Profile` tab을 선택한다.
3. `CDGM profile file`에 `demo/cdgm_profiles/cdgm-prof-soc-exynos2500-v1.yaml`을 업로드한다.
4. 아래 `CDGM profile document JSON` preview를 확인한다.
5. `Build CDGM import_bundle`을 누른다.
6. Step 2에서 `Stage bundle`을 누른다.
7. Step 3에서 `Validate batch`, `Preview diff`를 순서대로 누른다.
8. 문제가 없으면 Step 4에서 `Apply to DB`를 누른다.

Workbench가 생성하는 payload는 다음 형태다.

```json
{
  "kind": "scenario.import_bundle",
  "actor": "cdgm-importer@example.com",
  "note": "Stage CDGM profile document",
  "payload": {
    "import_report": {
      "ok": true,
      "generated": {
        "soc.cdgm_profile": 1
      },
      "messages": []
    },
    "documents": [
      {
        "id": "cdgm-prof-soc-exynos2500-v1",
        "schema_version": "2.3",
        "kind": "soc.cdgm_profile",
        "soc_ref": "soc-exynos2500",
        "profile_version": 1,
        "compatibility_scope": "soc",
        "role_overrides": {}
      }
    ]
  }
}
```

전체 샘플 payload:

```text
demo/write_payloads/cdgm_profile_import_bundle_valid.json
```

## 4. API로 직접 import

Workbench를 거치지 않고 Write API로 직접 확인할 수 있다.

```powershell
$api="http://127.0.0.1:18000/api/v1"
$payload = Get-Content demo\write_payloads\cdgm_profile_import_bundle_valid.json -Raw

$stage = Invoke-RestMethod `
  -Method Post `
  -Uri "$api/write/staging" `
  -ContentType "application/json" `
  -Body $payload

$validation = Invoke-RestMethod -Method Post -Uri "$api/write/staging/$($stage.batch_id)/validate"
$diff = Invoke-RestMethod -Method Post -Uri "$api/write/staging/$($stage.batch_id)/diff"

$validation.valid
$validation.issues
$diff.impact

Invoke-RestMethod -Method Post -Uri "$api/write/staging/$($stage.batch_id)/apply"
```

적용 후 조회:

```powershell
Invoke-RestMethod "$api/soc-cdgm-profiles?soc_ref=soc-exynos2500" | ConvertTo-Json -Depth 8
Invoke-RestMethod "$api/soc-cdgm-profiles/cdgm-prof-soc-exynos2500-v1" | ConvertTo-Json -Depth 8
```

## 5. CDGM resolve 확인

CDGM resolve는 다음 입력을 조합한다.

- scenario/variant
- `ip_catalog.capabilities.sim.cdgm_roles`
- `soc.cdgm_profile`
- `soc.dvfs_table`

요청 예시:

```powershell
$body = @'
{
  "scenario_id": "uc-camera-recording",
  "variant_id": "UHD60-HDR10-H265",
  "soc_ref": "soc-exynos2500",
  "dvfs_version": 4,
  "cdgm_profile_version": 1
}
'@

Invoke-RestMethod `
  -Method Post `
  -Uri "$api/cdgm/resolve" `
  -ContentType "application/json" `
  -Body $body | ConvertTo-Json -Depth 10
```

응답의 핵심 필드:

```json
{
  "scenario_id": "uc-camera-recording",
  "variant_id": "UHD60-HDR10-H265",
  "soc_ref": "soc-exynos2500",
  "dvfs_table_ref": "dvfs-soc-exynos2500-v4",
  "cdgm_profile_ref": "cdgm-prof-soc-exynos2500-v1",
  "arch_info_rows": [
    {
      "ip_ref": "ip-isp-v12",
      "role_key": "ISP",
      "arch_ip": "ISP",
      "pos": "STEP1+STEP2+STEP3",
      "ppc": 4.0,
      "vdd": "VDD_CAM",
      "dvfs_domain": "ISP"
    }
  ],
  "issues": []
}
```

주의:

- profile만 import하고 IP에 `cdgm_roles`가 없으면 base arch_info row가 비어 있을 수 있다.
- `dvfs_version`으로 resolve하려면 해당 SoC의 `soc.dvfs_table`이 먼저 import되어야 한다.
- `dvfs_domain`이 선택된 DVFS table에 없으면 `cdgm_dvfs_domain_not_found` issue가 나온다.

## 6. Field guide

### 6.1 `soc.cdgm_profile`

| Field | Required | 설명 |
| --- | --- | --- |
| `id` | yes | `cdgm-` prefix 권장. 예: `cdgm-prof-soc-exynos2500-v1`. |
| `schema_version` | yes | 현재 `"2.3"` 사용. |
| `kind` | yes | 반드시 `soc.cdgm_profile`. |
| `soc_ref` | yes | 대상 SoC id. |
| `profile_version` | yes | SoC 기준 CDGM profile sequence. DVFS version과 독립. |
| `evt_hint` | no | 참고 EVT metadata. version key가 아님. |
| `compatibility_scope` | yes | `soc` 또는 `project`. |
| `source_project_ref` | project scope일 때 yes | 과제별 domain/role 차이가 있으면 사용. |
| `domain_schema_hash` | no | voltage/domain 구성 호환성 marker. |
| `source` | no | guide name, revision, path, note 같은 provenance. |
| `role_overrides` | yes | 조건부 CDGM role 추가/override. 비어 있으면 `{}`. |
| `selection_policy` | no | default 여부, note 등 선택 정책 metadata. |

### 6.2 `role_overrides`

| Field | Required | 설명 |
| --- | --- | --- |
| `extends` | no | 기존 role을 상속할 때 사용. 예: `MFC_MFD_UHD60_HLG` extends `MFC_MFD`. |
| `ip_ref` | no | override가 연결되는 물리 IP. 지정하면 DB/import bundle에 존재해야 한다. |
| `arch_ip` | yes | CDGM arch_info IP 이름. |
| `path_type` | yes | `rt`, `nrt`, `codec`, `input`, `output`, `generic`. |
| `ppc` | yes | 양수. |
| `vdd` | no | voltage rail/domain. |
| `dvfs_domain` | yes | CDGM/DVFS domain 이름. resolve 시 DVFS table domain과 검증된다. |
| `pos` | NRT role은 yes | NRT step list. |
| `when` | no | scenario 조건. 비어 있으면 항상 적용. |
| `source` | no | override 값의 출처. |

지원하는 `when` key:

| Key | Source |
| --- | --- |
| `scenario_domain` | `scenario.metadata.domain` |
| `scenario_category` | `scenario.metadata.category` |
| `variant_id` | variant id |
| `variant_tag` | variant tags |
| `codec` | `variant.design_conditions.codec` |
| `codec_flow` | `variant.design_conditions.codec_flow` |
| `resolution_class` | `variant.design_conditions.resolution_class` |
| `fps` | `variant.design_conditions.fps` |
| `hdr_format` | `variant.design_conditions.hdr_format` |

## 7. 자주 나는 오류

| 오류 코드 | 의미 | 조치 |
| --- | --- | --- |
| `import_document_kind_unsupported` | import bundle이 지원하지 않는 kind | `kind: soc.cdgm_profile`인지 확인. |
| `import_document_schema_invalid` | YAML/JSON schema 오류 | `profile_version`, `role_overrides.*.ppc`, `compatibility_scope` 확인. |
| `import_soc_ref_not_found` | `soc_ref`가 DB/import bundle에 없음 | SoC를 먼저 import하거나 같은 bundle에 포함. |
| `import_project_ref_not_found` | `source_project_ref`가 DB/import bundle에 없음 | project scope이면 project를 먼저 import. |
| `import_cdgm_profile_ip_ref_not_found` | override의 `ip_ref`가 없음 | `ip` catalog를 먼저 import하거나 id mismatch 확인. |
| `cdgm_dvfs_domain_not_found` | resolve 시 DVFS table에 domain 없음 | `soc.dvfs_table.domains`와 `dvfs_domain` 이름을 맞춤. |
| `cdgm_nrt_pos_missing` | NRT role에 `pos` 없음 | `pos: [STEP1, STEP2, STEP3]` 추가. |

## 8. 운영 권장 순서

1. SoC와 물리 IP catalog를 import한다.
2. 필요한 IP YAML에 `capabilities.sim.cdgm_roles`를 추가한다.
3. `Canonical Bundle` tab으로 IP YAML 변경을 stage/validate/diff/apply한다.
4. `DVFS Table` tab으로 대상 SoC의 DVFS table version을 import한다.
5. `CDGM Profile` tab으로 `soc.cdgm_profile` YAML/JSON을 upload/import한다.
6. `/api/v1/cdgm/resolve`로 arch_info row가 기대대로 만들어지는지 확인한다.
7. 이후 CDGM run/persist 기능에서 같은 `scenario + variant + dvfs_version + profile_version` 조합으로 guide를 계산한다.

이 순서를 지키면 DVFS table version, EVT hint, CDGM profile version, physical IP catalog가
서로 섞이지 않는다.
