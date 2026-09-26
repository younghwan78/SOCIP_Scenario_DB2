# Authoring Guide — 편집 원본부터 DB 반영까지

`authoring/`은 사람이 편집하는 원본(SSOT)이다. `python -m scenario_db.authoring`이 이를 canonical v2.2 YAML
(`db_fixtures_*`)로 만들고, `scripts/dev_up.ps1`이 DB에 반영한다. 모든 명령은 `implementation\`에서 실행한다.

```
편집(authoring/) ─▶ compile·검증 ─▶ sync --to fixture ─▶ dev_up.ps1 ─▶ API/UI 확인
                                        ▲                 (rename → retire → ETL --strict)
          기존 generator로 fixture 수정 ─┘ sync --to authoring
```

---

## 1. 현재 scope (2026-09-27)

| 과제 | authoring | 적재 범위 |
| --- | --- | --- |
| Exynos2600 · SM-S947B (`proj-sm-s947b`) | `projects/sm-s947b` (root) ≡ `db_fixtures_Exynos2600_S26Plus` | **fixture 전체 그대로**: scenario 13개, camera recording variant 75개, APV scenario 별도, evidence 전체 |
| Exynos2700 · SM-S957B (`proj-sm-s957b`) | `projects/sm-s957b` (extends sm-s947b, platform exynos2700) | **rear camera recording만**: `uc-cam-recording-e2700` 하나, rear KPI 16개 + 탐색 3개 (dual wide+front 제외) |

Exynos2700의 범위 축소는 `projects/sm-s957b/project.yaml`의 `scenarios.include`와
`scenarios/uc-cam-recording-e2600/overlay.yaml`의 `variants.keep`으로만 한다. 2600 fixture와 authoring은 건드리지 않는다.

Exynos2700 KPI variant (`uc-cam-recording-e2700`):

| KPI | variant id | EIS | 비고 |
| --- | --- | --- | --- |
| FHD30 | `cam-rec-r1-fhd30-vdis` | on | |
| FHD60 | `cam-rec-r1-fhd60-supersteady` | on | |
| UHD30 | `cam-rec-r1-uhd30-vdis` | on | 기준(★) variant |
| UHD60 | `cam-rec-r1-uhd60-psm` | PSM | motion 없으면 EIS 짧게, GDC warping 생략 |
| 8K30 | `cam-rec-r1-8k30-psm` | PSM | 〃 |
| FHD120 / FHD240 / UHD120 | `cam-rec-r1-fhd120` / `-fhd240` / `-uhd120` | | high speed |
| UHD30/60/120 Pro video | `cam-rec-r1-uhd30-pro` / `-uhd60-pro` / `-uhd120-pro` | 부모와 동일 | 2700 overlay에서 추가. pipeline 동일 + CPU task `pro_scope` (histogram·equalizer, assumed) |
| FHD30/UHD30 Portrait | `cam-rec-r1-fhd30-portrait` / `-uhd30-portrait` | | |
| UHD30/60/120 APV | `cam-rec-apv-uhd30-422-sdr` / `-uhd60-` / `-uhd120-` | | 2700 overlay에서 추가. `apv_enc` 주입, `mfc_enc` disable. UHD120 bitrate assumed |
| 탐색 | `cam-rec-r1-uhd30-vdis-bcrop` / `-bcrop-l0skip` / `cam-rec-r1-fhd30-vdis-bcrop` | | knob 조건 비교용 (예제 5) |

KPI variant 값은 2600 variant를 그대로 상속한다 (id의 SoC suffix와 IP id만 rename). 2700 실측은 `sw_timing.measured.yaml`,
HW 차이는 `platforms/exynos2700/patches/`로 넣는다.

EIS on/off, pyramid L0 bypass, bcrop 크기처럼 **power diff를 보기 위한 조건**은 variant로 나누지 않는다.
`knobs.yaml`의 조건으로 두고 필요한 비교에서만 적용한다(§5 예제 5).

---

## 2. 디렉터리와 파일 역할

```
authoring/
  platforms/exynos2600/            root platform
    platform.yaml
    docs/00_hw/*.yaml              IP · SoC · DVFS · sim config (canonical 그대로)
    docs/00_sensor/**              sensor DT catalog
    docs/01_sw/*.yaml              SW profile
  platforms/exynos2700/            extends exynos2600: s5e9965 → s5e9975 rename + patches/
  projects/sm-s947b/               root project (Exynos2600, fixture와 1:1)
    project.yaml                   document: 과제 doc
    docs/00_hw/simcfg-*.yaml       과제별 sim config profile
    scenarios/uc-cam-recording-e2600/
      scenario.yaml                base pipeline · buffer · size anchor   (생성 → 편집 가능)
      variants.yaml                variant (root 또는 extends + 차이)      (생성 → 편집 가능)
      sizes.yaml                   node → size anchor 연결                (생성 → 편집 가능)
      sw_timing.yaml               SW task timing group                  (생성 → 편집 가능)
      knobs.yaml                   architecture 조건 (crop/EIS/pyramid)   (수작성, decompile에도 유지)
  projects/sm-s957b/               파생 project (Exynos2700 SM-S957B)
    project.yaml                   extends sm-s947b, scenarios.include: [uc-cam-recording-e2600]
    patches/simcfg-proj-sm-s957b-v1.yaml
    scenarios/uc-cam-recording-e2600/   (부모 scenario id 디렉터리)
      overlay.yaml                 variants.keep (KPI 범위) + add (Pro/APV/탐색 variant)
      sw_timing.measured.yaml      2700 실측 SW timing 칸
  examples/exynos2800-pipeline-change/   pipeline 변경 예시 (가상, 적재 안 됨)
  id-renames.yaml                  id 변경 이력 → DB in-place rename
  retired.yaml                     DB에서 지울 범위 → DB retire
```

| 파일 | 필수 key | 선택 key | 상세 |
| --- | --- | --- | --- |
| `platform.yaml` | `kind`, `id`, (파생) `extends`, `rename` | `soc_id`, `description`, `rename_exclude`, `remove_docs` | 예시 파일 주석 참고 |
| `project.yaml` | `kind`, `key`, `platform`, (root) `document` / (파생) `extends` | `rename`, `document_patch`, `scenarios.include/exclude` | 〃 |
| `overlay.yaml` (파생 과제) | — | `scenario_patch`, `pipeline`, `variants`, `sizes`, `sw_timing`, `knobs`, `prune_missing_nodes` | §6 |
| `sw_timing.measured.yaml` | `entries[].task`, `entries[].timing` | `group`, `variants`, `when`, `mode` | 예제 4 |
| `retired.yaml` | `retire[]` | `projects`, `socs`, `ips`, `scenarios`, `variants` | 예제 3 |
| `id-renames.yaml` | `renames: {old: new}` | — | 예제 8 |

Patch 규칙 (variants `extends`, overlay, patches 공통):

- dict는 재귀 merge, list는 통째 교체
- `$unset: [key]`는 key 삭제
- `$append: {key: [items]}`는 list에 추가 (중복 제외)

---

## 3. 공통 절차와 명령

| 단계 | 명령 | 성공 기준 |
| --- | --- | --- |
| ① 차이 확인 | `uv run python -m scenario_db.authoring check sm-s947b --against db_fixtures_Exynos2600_S26Plus` | 편집 전 `0 difference(s)` |
| ② 편집 | authoring 파일 수정 | |
| ③ compile·검증 | `uv run python -m scenario_db.authoring compile sm-s947b --out output\authoring\sm-s947b` | `"errors": []`, `impact` 확인 |
| ④ fixture 반영 | `uv run python -m scenario_db.authoring sync sm-s947b --fixture db_fixtures_Exynos2600_S26Plus --to fixture --prune` | `updated`/`removed` 목록이 의도와 일치 |
| ⑤ DB 반영 | API 창 닫기 → `powershell -ExecutionPolicy Bypass -File scripts\dev_up.ps1 -NoUi` | `output\etl\etl-exynos2600.json`에서 `ok: true`, `warnings: []` |
| ⑥ 확인 | 브라우저 새로고침, 아래 확인 쿼리 | |
| ⑦ commit | `git add authoring db_fixtures_Exynos2600_S26Plus` 후 commit | unit test 통과 |

`dev_up.ps1`의 DB 단계 (모두 멱등, 변경이 없으면 no-op):

1. `scenario_db.etl.rename_ids --apply --backup output\etl\rename-backup-<시각>.json`: `id-renames.yaml` 적용 (PK/FK/JSON)
2. `scenario_db.etl.retire --apply --backup output\etl\retire-backup-<시각>.json`: `retired.yaml` 범위의 행 삭제 (현재 id 기준)
3. `etl.loader db_fixtures_Exynos2600_S26Plus --strict`, 그다음 `-AuthoringProjects`(기본 `sm-s957b`)의 파생 과제를 compile해서 적재
4. API(:18000), UI(:3000) 실행 (`-NoUi`, `-SkipLoad`, `-Streamlit` 옵션)

DB 확인 쿼리:

```powershell
docker compose exec postgres psql -U scenario_user -d scenario_db
```
```sql
select id, metadata->>'board_type' from projects;
select id, project_ref, metadata->>'canonical_usecase' from scenarios;
select scenario_id, count(*) from scenario_variants group by 1;
select variant_ref, kind, count(*) from evidence group by 1,2 order by 1;
select id, design_conditions->>'crop_strategy' from scenario_variants where id like '%bcrop%';
```

API 확인: `http://127.0.0.1:18000/api/v1/explorer/scenario-catalog`, `.../scenarios/uc-cam-recording-e2600/variants`

---

## 4. 명령 레퍼런스

| 명령 | 설명 |
| --- | --- |
| `authoring compile <key> --out <dir> [--report-json f]` | 생성 + 검증 (DB 불필요) |
| `authoring check <key> --against <fixture>` | authoring과 fixture의 의미상 차이 |
| `authoring sync <key> --fixture <dir> --to fixture [--prune] [--dry-run]` | 바뀐 파일만 기록. `--prune`은 산출되지 않는 00~02 YAML 삭제 |
| `authoring sync <root key> --fixture <dir> --to authoring` | fixture → authoring (root 과제만). 수작성 파일과 검토한 binding은 유지 |
| `authoring worksheet <key>` | `sw_timing.measured.yaml` 빈 칸 생성 (기존 파일 보존) |
| `etl.retire [--spec] [--apply --backup f]` | DB에서 범위 삭제 (dry run 기본) |
| `etl.rename_ids [--map] [--apply --backup f]` | DB id in-place 변경 (dry run 기본) |

---

## 5. 예제

### 예제 1 — 기존 variant의 SW timing 수정 (2600)

`eis` task의 UHD30 평균을 3.0에서 3.4 ms로 바꾸는 경우.

1. `authoring/projects/sm-s947b/scenarios/uc-cam-recording-e2600/sw_timing.yaml`에서 task와 group을 찾는다.
   ```yaml
   tasks:
     eis:
       groups:
       - id: eis-a
         variants: '*'            # 다른 group에 없는 모든 variant
         timing: {min_ms: 2.5, mean_ms: 3.0, max_ms: 6.0, value_source: assumed, ...}
   ```
2. UHD30만 바꾸려면 group을 추가한다. 목록에 나열된 variant는 `'*'`에서 빠진다.
   ```yaml
       - id: eis-uhd30
         variants: [cam-rec-r1-uhd30-vdis, cam-rec-r1-uhd30-portrait]
         timing: {min_ms: 2.8, mean_ms: 3.4, max_ms: 6.0, value_source: assumed, source_note: 2026-09 재추정}
   ```
3. §3 ③~⑤ 실행. `sync` 결과 `updated: [02_definition/uc-cam-recording-e2600.yaml]`
   2700은 이 group을 상속하므로 `uc-cam-recording-e2700`의 같은 variant(Pro video 포함, 부모 group을 따름)도 바뀐다.
4. 확인:
   ```sql
   select id, node_configs->'eis'->'sw_timing'->>'mean_ms'
   from scenario_variants where scenario_id='uc-cam-recording-e2600' and id like '%uhd30%';
   ```

### 예제 2 — variant 추가 (FHD30 HDR10)

1. `variants.yaml` 끝에 추가한다. `extends`로 부모 variant를 지정하고 차이만 적는다.
   ```yaml
   - id: cam-rec-r1-fhd30-hdr10
     extends: cam-rec-r1-fhd30-vdis
     design_conditions:
       hdr: HDR10
       subscenario: HDR10_FHD_VIDEO
     tags: [is-v15, hdr]
   ```
   - node 처리 크기(sim width/height)는 `sizes.yaml` binding이 자동으로 채운다. 넣지 않는다.
   - SW timing은 `sw_timing.yaml`의 `'*'` group이 적용된다. 새 variant가 표에 없으면 부모의 group을 따른다.
2. compile: `errors: []` 확인. 없는 node를 참조하면 `unknown_node_config` 오류가 난다.
3. sync → dev_up. 2600 camera recording variant가 76개로 보이면 성공.
4. 2700에는 자동으로 나타나지 않는다 (`variants.keep`). 2700 KPI에도 넣으려면
   `projects/sm-s957b/scenarios/uc-cam-recording-e2600/overlay.yaml`의 `keep`에 id를 추가하고
   `tests/unit/authoring/test_authoring_roundtrip.py`의 `E2700_KPI`도 맞춘다.
5. 이 variant의 evidence는 측정/예측 import 경로로 추가한다 (예제 9).

### 예제 3 — variant 삭제 (DB 포함)

1. `variants.yaml`에서 항목을 지운다. 다른 variant가 이 variant를 `extends`하면 compile이 실패하므로 부모를 바꿔준다.
2. `sync --to fixture --prune`
3. 이 variant의 evidence 파일(`03_evidence/`)이 있으면 같이 지운다 (git history로 복구 가능).
   2700 KPI에 있던 variant라면 overlay `keep`에서도 뺀다.
4. **DB에서 지울 범위를 `authoring/retired.yaml`에 추가한다.** ETL은 upsert만 하므로 지운 variant가 DB에 남는다.
   ```yaml
   retire:
   - date: 2026-10-02
     reason: FHD30 HDR10 제외
     variants:
       uc-cam-recording-e2600: [cam-rec-r1-fhd30-hdr10]
   ```
5. dry run으로 먼저 확인한다.
   ```powershell
   uv run python -m scenario_db.etl.retire
   ```
   ```json
   {"applied": false, "rows": {"evidence": 2, "scenario_variants": 1}}
   ```
6. `dev_up.ps1 -NoUi`. `output\etl\retire-backup-*.json`에 삭제된 행이 남는다.

`retire` 적용 범위:

| 지정 | 삭제 대상 |
| --- | --- |
| `projects` | 과제, 그 scenario·variant·evidence·prediction·탐색 run·보고서·sim config |
| `socs` / `ips` | SoC 문서, 그 DVFS/CDGM table / 지정한 glob의 IP catalog |
| `scenarios` | scenario와 그것을 참조하는 행 |
| `variants` | variant 단위 행 (variants, evidence, predictions, reviews, sweep_jobs) |

여러 variant를 함께 담은 탐색 run 이력은 과제 전체를 retire할 때만 지운다.

### 예제 4 — SW timing 실측 입력 (Perfetto)

root 과제에는 `sw_timing.yaml`을 직접 고치거나(예제 1), 파생 과제에서 `measured` 파일을 쓴다(예제 6).

```powershell
uv run python -m scenario_db.authoring worksheet sm-s957b
```
```yaml
# projects/sm-s957b/scenarios/uc-cam-recording-e2600/sw_timing.measured.yaml
entries:
- task: eis
  group: eis-a                       # 상속된 sw_timing.yaml의 group
  when: {resolution: UHD}            # design_conditions로 범위 축소
  timing: {min_ms: 2.6, mean_ms: 3.1, max_ms: 5.2, value_source: measured,
           source_note: 'perfetto uhd30-eis 2026-10-05'}
- task: post_crta
  group: post_crta-a
  baseline: {min_ms: 0.1, mean_ms: 0.3, max_ms: 0.5}
  timing: null                       # 아직 미측정 → 부모 값 유지, compile report에 pending으로 집계
```

- 뒤에 있는 항목이 앞 항목보다 우선한다.
- `mode: merge`(기본)는 지정한 key만 바꾸고, `replace`는 전체를 교체한다.

### 예제 5 — Architecture 조건 비교 (bcrop, L0 skip, EIS)

`knobs.yaml`에 조건을 정의하고, variant의 `design_conditions`로 조건 값을 선택한다.

| knob | 값 | 효과 |
| --- | --- | --- |
| `crop_strategy` | `mcsc_crop` (default) / `byrp_bcrop` | bcrop: `bcrop_out = sensor_full × (100+eis)/(100+sensor_margin)`, RGBP~MCSC·mlsc_out·pyramid가 bcrop_out 기준 |
| `pyramid_l0` | `use` (default) / `skip` | `mlsc→mtnr` PYRAMID_L0 edge 제거 |
| params | `sensor_margin_pct: 25`, `eis_margin_pct` | EIS node 활성 시 15, 아니면 25 (crop 없음) |

비교용 variant를 **파생 과제 overlay**에 두면 2600 reference를 그대로 유지할 수 있다.
Exynos2700(`sm-s957b`) overlay에는 아래 bcrop 탐색 variant 3개가 이미 들어 있다. 별도 탐색 과제를 만들 때:

```yaml
# projects/explore-2600/project.yaml
kind: authoring.project
key: explore-2600
platform: exynos2600
extends: sm-s947b
rename:
- {from: proj-sm-s947b, to: proj-explore-2600}
- {from: -e2600, to: -e2600x}
document_patch: {metadata: {name: 2600 arch exploration, board_type: EXPLORE-2600}}
scenarios: {include: [uc-cam-recording-e2600]}
```
```yaml
# projects/explore-2600/scenarios/uc-cam-recording-e2600/overlay.yaml
variants:
  add:
  - id: cam-rec-r1-uhd30-vdis-bcrop
    extends: cam-rec-r1-uhd30-vdis
    design_conditions: {crop_strategy: byrp_bcrop}
  - id: cam-rec-r1-uhd30-vdis-bcrop-l0skip
    extends: cam-rec-r1-uhd30-vdis-bcrop
    design_conditions: {pyramid_l0: skip}
```
```powershell
powershell -ExecutionPolicy Bypass -File scripts\dev_up.ps1 -NoUi -AuthoringProjects explore-2600
```

Compare에서 `2600 · uhd30-vdis` ★ + `explore · vdis-bcrop` + `vdis-bcrop-l0skip`을 고르고 "Simulation 통일" → 예측 실행을
누르면 같은 모델 기준 Δ가 나온다 (2026-09-26 검증: 총 전력 −9.3% / −19.5%, BW −9.5% / −22.8%).

> 조합 탐색 화면에서 knob을 축으로 직접 sweep하는 기능은 아직 없다. 지금은 variant를 추가해서 비교한다.

### 예제 6 — Exynos2700 과제 범위 관리 (rear camera recording KPI)

현재 구성 (§1):

```yaml
# projects/sm-s957b/project.yaml
kind: authoring.project
key: sm-s957b
platform: exynos2700
extends: sm-s947b
rename:
- {from: proj-sm-s947b, to: proj-sm-s957b}
- {from: -e2600, to: -e2700}
scenarios:
  include: [uc-cam-recording-e2600]      # → uc-cam-recording-e2700
```
```yaml
# projects/sm-s957b/scenarios/uc-cam-recording-e2600/overlay.yaml
variants:
  keep: [cam-rec-r1-fhd30-vdis, ..., cam-rec-apv-uhd120-422-sdr, cam-rec-r1-uhd30-vdis-bcrop, ...]
  add:
  - id: cam-rec-r1-uhd30-pro
    extends: cam-rec-r1-uhd30-vdis        # keep에 없는 2600 variant도 부모(template)로 쓸 수 있다
    design_conditions: {camera_mode: pro_video, ...}
    ...
```

- `keep`: compile 산출물에 남길 variant (이 순서). 나머지 상속 variant는 `extends` 부모로만 쓰이고 출력되지 않는다.
  `remove`와 달리 자식 variant가 남아 있어도 실패하지 않는다. 없는 id를 적으면 compile이 실패한다.
- KPI 추가: 2600에 있는 variant면 `keep`에 id만 추가, 없는 variant면 `add` + `keep`.
- KPI 제외: `keep`에서 빼고, DB에 남은 행은 `retired.yaml`의 `variants.uc-cam-recording-e2700`에 추가한다.
- 다른 scenario를 2700에 다시 넣으려면 `scenarios.include`에 부모 id를 추가하고, `retired.yaml`의 해당 `-e2700` scenario를 지운다.
  남겨두면 dev_up이 새로 적재한 행을 매번 다시 지운다.
- 실측 입력 (예제 4), HW 차이 `platforms/exynos2700/patches/ip-*-s5e9975.yaml`,
  calibration `projects/sm-s957b/patches/simcfg-proj-sm-s957b-v1.yaml` (`status: draft`).

반영과 확인:

```powershell
uv run python -m scenario_db.authoring compile sm-s957b --out output\authoring\sm-s957b   # scenarios: {uc-cam-recording-e2700: 19}
powershell -ExecutionPolicy Bypass -File scripts\dev_up.ps1 -NoUi                           # 기본 -AuthoringProjects sm-s957b
```
```sql
select s.project_ref, s.id, count(v.id) from scenarios s join scenario_variants v on v.scenario_id=s.id group by 1,2 order by 1,2;
-- proj-sm-s947b: 13 scenario (uc-cam-recording-e2600 75, apv 9, ...)
-- proj-sm-s957b: uc-cam-recording-e2700 19
```

UI 상단 과제 선택에 `Exynos2700 · SM-S957B`가 나타나고, Compare에서 2600 ↔ 2700 같은 variant를 비교할 수 있다.

### 예제 7 — pipeline 구조가 바뀌는 과제 (Exynos2800 가상 예시)

`authoring/examples/exynos2800-pipeline-change/` (MTNR+MSNR → NR v2)

| 파일 | 내용 |
| --- | --- |
| `platforms/exynos2800-concept/platform.yaml` | exynos2600 상속, id rename (필수/선택 주석) |
| `platforms/exynos2800-concept/docs/00_hw/ip-nr-v2-exynos2800c.yaml` | 새 IP 문서 (필수 key와 규칙 R1~R7 주석) |
| `projects/e2800-concept/project.yaml` | sm-s947b 상속 |
| `projects/e2800-concept/scenarios/uc-cam-recording-e2600/overlay.yaml` | `remove_nodes: [msnr]`, `set_nodes.mtnr.ip_ref`, `add_edges` |

```powershell
Copy-Item -Recurse authoring $env:TEMP\auth2800
Copy-Item -Recurse authoring\examples\exynos2800-pipeline-change\* $env:TEMP\auth2800 -Force
uv run python -m scenario_db.authoring --root $env:TEMP\auth2800 compile e2800-concept --out $env:TEMP\c2800
```

compile report의 `impact`에는 삭제된 `msnr`을 참조하던 variant 설정이 모두 나열된다 (현재 71건).
`prune_missing_nodes: false`로 두면 실패하므로, 목록을 검토한 뒤 overlay를 수정하거나 `true`로 자동 제거한다.
실제 과제로 쓸 때는 `examples/`가 아니라 `platforms/`, `projects/`로 옮긴다.

### 예제 8 — id 변경

1. authoring에서 id를 바꾼다 (디렉터리 이름, `scenario.yaml`의 `id`).
2. `authoring/id-renames.yaml`에 `old: new`를 추가한다. 연쇄 변경(a→b, b→c)은 자동으로 a→c로 합쳐지고, 순환은 오류로 처리된다.
3. evidence YAML의 `scenario_ref`를 수정하고 `sync --to fixture --prune`
4. `dev_up`: DB의 PK/FK/JSON 참조를 in-place로 바꾸므로 prediction, 탐색 run, 보고서가 유지된다.
   새 id가 이미 있으면 기존 행으로 합쳐진다.
   현재 fixture에 있는 id를 old로 적으면 dev_up마다 그 scenario가 합쳐지므로 금지 (unit test가 확인).
5. 저장해 둔 UI URL(`items=`)은 다시 만든다. 옛 id는 UI에서 canonical로 매핑된다.

### 예제 9 — 측정 evidence 추가

- 측정 bundle import는 [Measurement Import Guide](../measurement/measurement-import-guide-ko.md)를 따른다.
- 대상 참조: 2600 `project=proj-sm-s947b`, `scenario=uc-cam-recording-e2600` / 2700 `proj-sm-s957b`, `uc-cam-recording-e2700`
- 2600 evidence를 fixture에 보관하려면 `db_fixtures_Exynos2600_S26Plus/03_evidence/`에 저장한다.

### 예제 10 — 기존 generator로 fixture를 고친 경우

```powershell
uv run python scripts\enrich_priority_recording.py        # fixture 직접 수정
uv run python -m scenario_db.authoring sync sm-s947b --fixture db_fixtures_Exynos2600_S26Plus --to authoring
git diff authoring/                                     # 변경을 authoring 기준으로 검토
```

`knobs.yaml`, `overlay.yaml`, `sw_timing.measured.yaml`, 사람이 고친 `sizes.yaml` binding은 decompile에도 유지된다.

---

## 6. overlay.yaml (파생 과제)

```yaml
kind: authoring.scenario_overlay
scenario_patch: {metadata: {name: ...}}            # base 문서 merge (variants 제외)
pipeline:
  remove_nodes: [msnr]                             # 해당 edge도 함께 제거
  add_nodes: [{id: nr2, ip_ref: ip-..., role: nr}]
  set_nodes: {mtnr: {ip_ref: ip-nr-v2-...}}        # IP 교체
  remove_edges: [{from: mtnr, to: msnr}]
  add_edges: [{from: mtnr, to: yuvp, type: OTF, port_pairs: [{src: COUTFIFO, dst: CINFIFO}]}]
  add_buffers: {NAME: {size_ref: ..., format: ...}}
  remove_buffers: [NAME]
  rename_ports: {OLD: NEW}                         # edge, variant topology, active port 전체
variants:
  remove: [ids]
  patch: {id: {...}}                               # compact 항목에 merge (자식 variant도 영향)
  add: [{id: ..., extends: ..., ...}]
  keep: [ids]                                      # 출력 범위 (순서 유지). 나머지는 extends 부모로만 사용
sizes: {bindings: {...}, derived: {...}}
sw_timing: {tasks: {...}}
knobs: {params: {...}, knobs: {...}}
prune_missing_nodes: false
```

---

## 7. 검증 단계와 문제 해결

| 단계 | 검사 | 실패 예 → 조치 |
| --- | --- | --- |
| compile | kind별 pydantic schema, 문서 간 참조 (soc/ip/project/simcfg), pipeline cycle, variant overlay 참조, buffer size anchor | `schema: design_conditions.x: Input should be a valid string` → `design_conditions` 값은 scalar만 허용 |
| compile impact | 삭제된 node를 참조하는 variant | overlay 수정 또는 `prune_missing_nodes: true` |
| unit test | authoring ≡ 2600 fixture, 2600 전체 유지(13 scenario / 75 variant), 2700 scope(rear KPI 16 + 탐색 3), retired.yaml이 적재 대상과 겹치지 않음 | `check`로 차이 확인 → 한쪽으로 sync |
| ETL `--strict` | DB 적재, 적재 후 참조, `canonical_usecase` | `output\etl\etl-*.json`의 `validation.errors` |
| UI | 과제 전환, Compare, 즉석 simulation | API 재시작 여부 확인 |

| 증상 | 원인 | 조치 |
| --- | --- | --- |
| 지운 variant가 UI에 계속 보임 | ETL은 삭제하지 않음 | `retired.yaml`에 추가 → dev_up |
| 새로 만든 과제가 dev_up 후 사라짐 | `retired.yaml`에 같은 id가 남아 있음 | 해당 항목 제거 |
| 같은 scenario가 두 개 보임 | id를 바꿨지만 `id-renames.yaml`에 기록하지 않음 | 기록 후 dev_up (merge) |
| 포트 18000 사용 중 | 이전 API 창이 떠 있음 | 창을 닫고 dev_up |
| rename 결과에 `post_rename_validation.ok=false` | scenario 병합 직후의 일시적 불일치 | 이어지는 ETL `--strict`가 통과하면 정상 |
| ETL warning `canonical_usecase 'uc-game-play-e2600' ... not project-qualified` | 예전 rename이 old id(`uc-game-play`)와 같은 canonical key까지 바꿨고, ETL은 sha가 같아 재적재를 건너뜀 | 수정됨: rename은 `canonical_usecase`를 건드리지 않고, 손상된 scenario는 다음 dev_up에서 fixture로 재적재 |
| 2600 scenario/variant가 줄어듦 | 2600 fixture·`sm-s947b`를 직접 줄였거나 `retired.yaml`에 2600 id가 들어감 | 2700 범위는 `sm-s957b` overlay `keep`으로만 조정. unit test가 둘 다 검사 |
| 잘못 지움 | — | `output\etl\*-backup-*.json`(삭제 행), git history로 복구 후 dev_up |
