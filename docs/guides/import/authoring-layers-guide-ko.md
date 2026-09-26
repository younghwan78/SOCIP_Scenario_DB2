# Layered Authoring Guide

`authoring/`은 사람이 편집하는 SSOT이고, `python -m scenario_db.authoring compile`이 이를
canonical schema v2.2 YAML(기존 ETL 입력)로 변환한다. Excel 없이 text + git diff로 관리한다.

## 레이어

| 레이어 | 위치 | 내용 | 상속 |
| --- | --- | --- | --- |
| Platform | `platforms/<p>/` | IP, SoC, DVFS, sensor, SW catalog | `extends` + id rename + `patches/<id>.yaml` |
| Project | `projects/<k>/project.yaml` | board/project doc, sim config profile | `extends` + `document_patch` + `patches/` |
| Scenario base | `scenarios/<uc>/scenario.yaml` | pipeline, buffers, size anchors, metadata | overlay `scenario_patch`, `pipeline` ops |
| Variants | `scenarios/<uc>/variants.yaml` | root variant 또는 `extends: <id>` + delta | overlay `variants.remove/patch/add` |
| Sizes | `scenarios/<uc>/sizes.yaml` | node → size anchor binding, derived anchor | overlay `sizes` |
| SW timing | `scenarios/<uc>/sw_timing.yaml` | task별 timing group | `sw_timing.measured.yaml` |
| Knobs | `scenarios/<uc>/knobs.yaml` (수작성) | crop 방식, EIS margin, pyramid L0 | overlay `knobs` |

Compile 순서(variant별): `extends` 전개 → knob → derived anchor → size binding → sw_timing → 측정값.
`decompile`이 생성하는 파일은 `scenario/variants/sizes/sw_timing.yaml` 4개뿐이다. `knobs.yaml`, `overlay.yaml`,
`sw_timing.measured.yaml`, 검토한 `sizes.yaml` binding 선택은 decompile 후에도 유지된다.

## Exynos2600 (sm-s947b)과 양방향 전환

- `db_fixtures_Exynos2600_S26Plus`를 decompile한 결과이며, compile 결과가 fixture와 **의미상 동일**하다
  (`tests/unit/authoring` 에서 강제). 00~02 레이어 31,211줄 → authoring 약 10,100줄.
- 전환기에는 양쪽 편집을 모두 허용한다. 편집한 쪽에서 반대쪽으로 `sync` 한다.

| 편집한 쪽 | 명령 | 동작 |
| --- | --- | --- |
| fixture (기존 generator) | `sync sm-s947b --fixture <dir> --to authoring` | root project만 가능. 생성 파일만 갱신 |
| authoring | `sync <project> --fixture <dir> --to fixture` | 의미가 바뀐 파일만 기록. `--prune`: 산출되지 않는 00~02 YAML 삭제 |
| 확인 | `check <project> --against <dir>` 또는 `sync ... --dry-run` | 차이 목록 |

```powershell
uv run python -m scenario_db.authoring sync sm-s947b --fixture db_fixtures_Exynos2600_S26Plus --to authoring
uv run python -m scenario_db.authoring sync sm-s957b --fixture db_fixtures_Exynos2700_SM-S957B --to fixture
```
`03_evidence`, `.etlignore`, report JSON 등 00~02 밖의 파일은 어느 방향에서도 건드리지 않는다.
`--to fixture`로 다시 쓴 파일은 주석이 없어지고 `GENERATED` 헤더가 붙는다.

## Exynos2700 SM-S957B (sm-s957b) — 동일 pipeline, 실측 입력

1. ID: `platforms/exynos2700/platform.yaml` rename — IP `s5e9965 → s5e9975`, SoC/DVFS `exynos2600 → exynos2700`.
2. HW delta: `platforms/exynos2700/patches/<ip id>.yaml` (clock, PPC, DMA, power 계수).
3. SW 실측: `projects/sm-s957b/scenarios/<uc>/sw_timing.measured.yaml`의 `timing: null` 슬롯을 채운다.
   - `group`은 상속된 `sw_timing.yaml`의 group id, `when: {resolution: UHD}`로 범위 축소, 뒤 항목 우선.
   - 비어 있는 슬롯은 baseline(2600 값)을 유지하고 compile report에 `pending`으로 집계된다.
4. Calibration: `projects/sm-s957b/patches/simcfg-proj-sm-s957b-v1.yaml` (현재 `status: draft`).
5. 측정 evidence(Perfetto/전력)는 기존 [Measurement Import Guide](../measurement/measurement-import-guide-ko.md) 경로를 사용.

```powershell
uv run python -m scenario_db.authoring worksheet sm-s957b          # 측정 슬롯 생성(기존 파일 보존)
uv run python -m scenario_db.authoring compile sm-s957b --out output/authoring/sm-s957b --report-json output/authoring/sm-s957b.json
uv run python -m scenario_db.etl.loader output/authoring/sm-s957b --strict
```

ID 규칙
- scenario: `uc-<domain>-<use case>-e<SoC>` (예: `uc-cam-recording-e2600`, `uc-cam-recording-e2700`).
  domain 약어는 `cam`, `vid`, `aud`, `disp`, `call`, `game`.
- `metadata.canonical_usecase` = SoC suffix를 뺀 id (`uc-cam-recording`). 과제 간 비교와 UI의 과제 전환은 이 값으로 매칭한다.
- project: `proj-<board>` (`proj-sm-s947b`, `proj-sm-s957b`). IP/SoC/DVFS는 platform rename 규칙을 따른다.
- `00_sensor/`는 `rename_exclude`로 공유(동일 id, 동일 내용).
- 변경 이력은 `authoring/id-renames.yaml`. 기존 runtime DB는 `python -m scenario_db.etl.rename_ids`로 이관한다(아래).

## Exynos2800 — pipeline 구조 변경

`authoring/examples/exynos2800-pipeline-change/` (가상 예시, 실제 2800 데이터 아님).

- 새 IP: 자식 platform `docs/`에 추가. IP 교체는 overlay `pipeline.set_nodes.<node>.ip_ref`.
- 구조 변경: `remove_nodes`, `add_nodes`, `remove_edges`, `add_edges`, `add/remove_buffers`, `rename_ports`.
- 영향 분석: 제거된 node를 참조하는 variant 설정(node_configs, disabled_nodes, topology edge)을
  compile이 모두 나열한다. `prune_missing_nodes: false`(기본)면 실패, `true`면 제거 후 report `impact`에 기록.
- SW task graph, sw_timing, sensor size, 나머지 variant delta는 그대로 상속된다.

## Architecture knobs — crop 방식 / EIS margin / pyramid L0

`projects/sm-s947b/scenarios/uc-cam-recording-e2600/knobs.yaml`. variant가 `design_conditions`로 값을 고르며,
지정하지 않으면 default가 적용된다. default는 2600 fixture와 동일하다.

| Knob | 값 | 효과 |
| --- | --- | --- |
| `crop_strategy` | `mcsc_crop` (default) | sensor full size로 체인 처리, MCSC가 crop + scale |
| | `byrp_bcrop` | BYRP bcrop → `bcrop_out = sensor_full × (100+eis)/(100+sensor_margin)`. RGBP~MCSC, `mlsc_out`, pyramid L0~L4 모두 `bcrop_out` 기준. MCSC는 scale만 수행 |
| `pyramid_l0` | `use` (default) | L0~L4 모두 사용 |
| | `skip` | `mlsc→mtnr` PYRAMID_L0 edge 제거 (low power) |

- Params: `sensor_margin_pct: 25` (sensor mode에 포함된 FOV margin), `eis_margin_pct`.
  EIS node가 활성이면 15, 비활성이면 25(crop 없음). variant `design_conditions`에서 개별 override 가능.
- non-default를 고른 variant에는 적용된 params가 `design_conditions`에 기록된다.
- 예 (4080x2296, EIS 15%): `bcrop_out` = 3760x2114 → 체인 pixel 수 약 −15%, pyramid L1 = 1880x1057.
- 2700 탐색 variant: `projects/sm-s957b/scenarios/uc-cam-recording-e2600/overlay.yaml`
  (`*-bcrop`, `*-bcrop-l0skip`).
- 한계: L0 skip은 DMA edge만 제거한다. MTNR0 블록 비활성화, reference frame L0 traffic은 아직 모델에 없다.
  front camera 경로(`front_*` anchor)는 knob 적용 대상이 아니다.

## Size anchor

- decompile은 node의 `sim.width/height`가 모든 variant에서 같은 anchor와 일치하면 `sizes.yaml`
  binding으로 바꾼다. 같은 값의 anchor가 여러 개면 첫 anchor를 고르고 `alternatives`에 남긴다 — **검토 필요**.
  사람이 고친 binding은 다음 decompile에서도 유지된다(여전히 유효한 경우).
- knob과 무관한 scenario 공통 규칙은 `sizes.yaml`의 `derived`(형식은 knob derived와 동일)로 작성한다.

## Patch 규칙

- dict는 재귀 merge, list는 통째 교체, `$unset: [key]`는 key 삭제, `$append: {key: [items]}`는 list에 추가(중복 제외).
- variant `extends`는 authoring 전용이다. 런타임 상속 필드 `derived_from_variant`와 별개이며,
  `derived_from_variant` variant에는 size binding을 적용하지 않는다(런타임이 부모에서 해석).

## 검증

`compile`은 kind별 pydantic schema, 문서 간 참조(soc/ip/project/simcfg), pipeline cycle,
variant overlay 참조(`integrity_checks` 엔진 재사용), buffer/anchor 참조를 DB 없이 검사한다.
DB 적재 검증은 기존 `etl.loader --strict`로 한다.
