# 벤치 export → rail_long CSV 어댑터

> **상태: 구현 완료 (2026-08-29)** — `src/scenario_db/meas_import/bench_adapter.py`.
> 단독 CLI(`python -m scenario_db.meas_import.bench_adapter --in <dir|files> --out <csv>`)와
> `meas_import.cli --bench-in <dir|files>`(변환+canonical 생성 원커맨드) 두 경로 제공.
> 예제 입력: `bench-export/power_run{1,2,3}.txt` (path-a CSV와 값 동일 — 등가성 테스트로 고정).
> 테스트: `tests/unit/meas_import/test_bench_adapter.py`.
>
> 아래 "확정 필요"였던 항목은 파서 유연성으로 흡수됨 — 구분자(공백/콤마/탭) 자동 감지,
> 헤더 대소문자/괄호 표기 무관, 단위는 헤더 접미(`(mV)`/`[W]`/`_ma` 등)에서 읽고 V/mA/mW로
> 정규화(기본값 V/mA/mW), run은 파일명 숫자 → 정렬 순서 폴백, 단일 파일 `run` 컬럼 지원.
> **실제 벤치 파일 1개를 받으면 그대로 넣어 파싱되는지만 확인하면 된다** — 안 되면
> `_COLUMN_KINDS`/`_UNIT_SCALES`에 표기 하나 추가로 끝나는 구조.

이 문서는 원래 재개 앵커용 명세였습니다. 이력 보존을 위해 원문 유지:
관련 memory(같은 경로일 때만 로드): `measurement-realdata-ingestion.md`.

## 목표 (한 줄)
실제 측정 벤치의 **per-run wide 표**(rail이 행, Voltage/Current/Power가 열)를
`meas_import`(rail_long)이 먹는 **long CSV**로 합쳐주는 변환기.
이거 하나면 전력 실데이터 적재가 turnkey가 됨.

## 현재 준비 상태 (이미 됨)
- `meas_import` rail_long 경로는 완성·검증됨: `meta.yaml`(power.format=rail_long) + long CSV
  → canonical `evidence.measurement` 자동 생성(run 간 mean/std/ci, per-rail V/mA/mW, total,
  cpu cluster, domain). `examples/measurement-import/` 참고.
- **막는 지점 = 입력 포맷 불일치뿐.** 도구는 long을 먹는데 벤치는 wide per-run을 뱉음.

## 입력 (실제 벤치 export) — ⚠️ 실제 형식 확인 후 확정
대표 샘플(사용자 제공, run 1개분):
```
rail                          Voltage  Current(mA)  Power(mW)
B5S4_VDDMIF_AP_L              0.5687   70.3296      42.6975
B3_4_5S2_VDD_CPUCL3_BIG_L     0.0132   30.5006      26.9486
...                           ...      ...          ...
```
- 한 파일 = 한 run(추정). 보통 3 run(특이 시나리오 1).
- rail 명/개수는 과제마다 다름.

**확정 필요(사용자 확인 대기):**
- [ ] 파일 형식: 공백구분 txt? CSV? xlsx? 헤더 줄 수/위치?
- [ ] run 구분: 파일당 1 run인가, 한 파일에 run 컬럼? 파일명 규칙?
- [ ] 단위: Voltage가 V인가 mV인가? Current mA? Power mW?
- [ ] 컬럼명 정확한 표기(대소문자/괄호).

## 출력 (목표) — 고정
`meas_import` rail_long CSV:
```
run,rail,voltage_v,current_ma,power_mw
1,B5S4_VDDMIF_AP_L,0.5687,70.3296,42.6975
2,B5S4_VDDMIF_AP_L,...
```
- N개 run의 wide 표 → 이 long CSV 1개로 concat. voltage는 V 단위로 정규화.

## Plug point (구현 위치 제안)
- 새 모듈 `src/scenario_db/meas_import/bench_adapter.py`:
  `bench_files_to_rail_long(paths|dir) -> long CSV 경로` (순수 파싱+concat, 단위 정규화).
- CLI: `python -m scenario_db.meas_import.bench_adapter --in <dir|files> --out rail_power_by_run.csv`
  (또는 `cli.py`에 `--bench-in`을 받아 내부에서 변환 후 rail_long 파이프라인 연결).
- 파싱은 포맷 가변성을 흡수하도록 컬럼명/단위/run규칙을 인자나 작은 spec으로.

## 통과 기준 (acceptance)
1. 대표 벤치 파일 N개 → long CSV 생성, 행수 = Σ(run × rail).
2. 그 CSV로 `meas_import.cli`(rail_long) 실행 → canonical 생성 → `MeasurementEvidence` 검증 통과.
3. total_power_mw = 기존 sim과 정합 범위(데모는 ~681mW). 단위 오변환 없음(V/mA/mW).
4. 단위 테스트: wide 샘플(2 run × 3 rail) → 기대 long rows; 단위/run 매핑 검증.
5. **실제 익명 샘플 1개를 `examples/measurement-import/`에 커밋**(어댑터 fixture 겸 형식 명세).

## 작업 규칙 (이번 세션 사고 방지)
- worktree에서: `git worktree add ../sb-adapter -b feat/bench-adapter`.
- **`git add -A` 금지** — 경로 명시 staging (b8ae88d가 기능 커밋에 무관 fixture 삭제를 동반한 사고).
- 작은 스코프 커밋. 그린 확인 후 머지.

## 재개 킥오프 (복붙용)
> "벤치 export → rail_long CSV 어댑터 구현. 명세는 `examples/measurement-import/BENCH-ADAPTER.md`,
> rail_long 계약은 `examples/measurement-import/README.md` + `src/scenario_db/meas_import/`.
> 실제 벤치 형식은 위 '확정 필요' 항목을 내게 물어보고 시작. `feat/bench-adapter` worktree에서 작업."
