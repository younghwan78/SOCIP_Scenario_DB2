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

Compile 순서(variant별): `extends` 전개 → derived anchor → size binding → sw_timing → 측정값 적용.

## Exynos2600 (sm-s947b)

- `db_fixtures_Exynos2600_S26Plus`를 decompile한 결과이며, compile 결과가 fixture와 **의미상 동일**하다
  (`tests/unit/authoring` 에서 강제). 00~02 레이어 31,211줄 → authoring 10,101줄.
- 전환기 규칙: fixture를 기존 generator로 수정했다면 decompile을 다시 실행해 동기화한다.

```powershell
uv run python -m scenario_db.authoring decompile db_fixtures_Exynos2600_S26Plus --platform exynos2600 --project sm-s947b
uv run python -m scenario_db.authoring check sm-s947b --against db_fixtures_Exynos2600_S26Plus
```

## Exynos2700 (e2700-ref) — 동일 pipeline, 실측 입력

1. `platforms/exynos2700/platform.yaml`의 `rename` 태그(`s5e9965 → exynos2700`)를 실제 제품 태그로 교체.
2. HW delta: `platforms/exynos2700/patches/<ip id>.yaml` (clock, PPC, DMA, power 계수).
3. SW 실측: `projects/e2700-ref/scenarios/<uc>/sw_timing.measured.yaml`의 `timing: null` 슬롯을 채운다.
   - `group`은 상속된 `sw_timing.yaml`의 group id, `when: {resolution: UHD}`로 범위 축소, 뒤 항목 우선.
   - 비어 있는 슬롯은 baseline(2600 값)을 유지하고 compile report에 `pending`으로 집계된다.
4. Calibration: `projects/e2700-ref/patches/simcfg-proj-e2700-ref-v1.yaml` (현재 `status: draft`).
5. 측정 evidence(Perfetto/전력)는 기존 [Measurement Import Guide](../measurement/measurement-import-guide-ko.md) 경로를 사용.

```powershell
uv run python -m scenario_db.authoring worksheet e2700-ref          # 측정 슬롯 생성(기존 파일 보존)
uv run python -m scenario_db.authoring compile e2700-ref --out output/authoring/e2700 --report-json output/authoring/e2700.json
uv run python -m scenario_db.etl.loader output/authoring/e2700 --strict
```

ID 규칙: IP/SoC/DVFS는 rename 규칙, 시나리오는 `-e2700` suffix, `metadata.canonical_usecase`에
원래 시나리오 id가 기록되어 2600↔2700 비교 join key로 쓰인다. `00_sensor/`는 `rename_exclude`로
공유(동일 id, 동일 내용)된다.

## Exynos2800 — pipeline 구조 변경

`authoring/examples/exynos2800-pipeline-change/` (가상 예시, 실제 2800 데이터 아님).

- 새 IP: 자식 platform `docs/`에 추가. IP 교체는 overlay `pipeline.set_nodes.<node>.ip_ref`.
- 구조 변경: `remove_nodes`, `add_nodes`, `remove_edges`, `add_edges`, `add/remove_buffers`, `rename_ports`.
- 영향 분석: 제거된 node를 참조하는 variant 설정(node_configs, disabled_nodes, topology edge)을
  compile이 모두 나열한다. `prune_missing_nodes: false`(기본)면 실패, `true`면 제거 후 report `impact`에 기록.
- SW task graph, sw_timing, sensor size, 나머지 variant delta는 그대로 상속된다.

## Size anchor와 EIS margin

- decompile은 node의 `sim.width/height`가 모든 variant에서 같은 anchor와 일치하면 `sizes.yaml`
  binding으로 바꾼다. 같은 값의 anchor가 여러 개면 첫 anchor를 고르고 `alternatives`에 남긴다 — **검토 필요**.
- derived anchor로 margin 규칙을 표현한다(2600에는 미적용):

```yaml
# projects/<k>/scenarios/<uc>/overlay.yaml
sizes:
  derived:
    eis_in: {from: record_out, scale: 1.15, align: 16}   # variable EIS 15%
  bindings:
    mcsc: eis_in
```
  `scale`만 바꿔 25% ↔ 15% 비교가 가능하다. EIS crop이 적용되는 node 경계는 pipeline별로 정해야 한다.

## Patch 규칙

- dict는 재귀 merge, list는 통째 교체, `$unset: [key]`는 key 삭제.
- variant `extends`는 authoring 전용이다. 런타임 상속 필드 `derived_from_variant`와 별개이며,
  `derived_from_variant` variant에는 size binding을 적용하지 않는다(런타임이 부모에서 해석).

## 검증

`compile`은 kind별 pydantic schema, 문서 간 참조(soc/ip/project/simcfg), pipeline cycle,
variant overlay 참조(`integrity_checks` 엔진 재사용), buffer/anchor 참조를 DB 없이 검사한다.
DB 적재 검증은 기존 `etl.loader --strict`로 한다.
