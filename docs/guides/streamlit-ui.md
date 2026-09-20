# Streamlit UI and archived SPA

The default UI is the existing Streamlit Dashboard with the embedded Scenario Workbench. The review SPA introduced by `feat/modern-web-spa` is preserved remotely on [archive/modern-web-spa-is-v15](https://github.com/younghwan78/SOCIP_Scenario_DB2/tree/archive/modern-web-spa-is-v15), including the IS v15 camera improvements. Its SPA source and API static mount are removed from main. `web/package.json` remains only as a compatibility entry point for the existing CI job and delegates to `frontend/`; it contains no UI server. Ignored local build artifacts must not select a different default UI.

Run from `implementation/` after configuring the existing PostgreSQL connection:

```powershell
.\.venv\Scripts\python.exe -m uvicorn scenario_db.api.app:app --host 127.0.0.1 --port 18000
.\.venv\Scripts\python.exe -m streamlit run dashboard/Home.py --server.address 127.0.0.1 --server.port 18502 --server.headless true
```

Open [Dashboard](http://127.0.0.1:18502/), [Pipeline Viewer](http://127.0.0.1:18502/Pipeline_Viewer), or [Evidence Dashboard](http://127.0.0.1:18502/Evidence_Dashboard). API docs remain at [18000/docs](http://127.0.0.1:18000/docs). Port 5173 is no longer the default UI.

The existing `frontend/` Workbench, committed component assets, ELK viewer, timing integration and node labels remain. To rebuild the Workbench, run `npm ci`, `npm test`, and `npm run build` inside `frontend/`; include the output under `dashboard/components/workbench_frontend/component/`.

This is a selective UI restoration, not a revert of all PR #5 changes. Query/pagination improvements, simulation correctness, API/write fixes, security lock updates, and IS v15 sensors/DMA/timing/evidence stay in main. The existing Evidence Dashboard Timing Table also shows camera SW min/mean/max, source, start delay and included hardware. Measurement comparison remains in the existing dashboard.


## Camera review in DB Explorer

The existing Streamlit cards, colors, filters and tables now include camera review guidance. Camera review panels appear only when Scenario Type is explicitly set to Camera; All retains the general DB overview and variant matrix:

- **Overview** starts with basic recording KPI coverage (FHD30, FHD60, UHD30, UHD60, 8K30), followed by Slow motion, Portrait, Dual and Pro review cards. DB/import counts remain in a collapsed section. The project breakdown keeps coverage scoped to the current filters.
- **Scenario Catalog** explains scenario purpose and stored severity grades. Expand the load detail to choose a grade and inspect an actual variant's conditions and workload factors.
- **Variant Matrix** offers review-group and KPI selection before the table. The selected variant shows why to review it, resource considerations, timing assumptions and a scoped Pipeline Viewer link. The table follows the same group/KPI filters.

Coverage counts only explicit `resolution` and `fps` conditions. Basic recording excludes special modes; combined modes can belong to several review groups. Preview/capture remain separate even when they share a `PRO_VIDEO` driver flag. Missing or partial results mean "unconfirmed in the current scope", not unsupported hardware. Registered variants do not establish KPI pass/fail.

Severity remains the author-assigned value. Explorer does not have a common numeric threshold or grading rationale, so workload explanations must not be represented as the formula that produced a grade. GPU/NPU use is not inferred from Portrait alone: the registered processing source, including VPS/CPU assumptions, is shown. Pro mode alone does not establish that Histogram UI work is modeled.

The guidance is implemented in `dashboard/components/camera_review.py` and `camera_review_view.py`; it does not modify fixture grades, ETL, or API contracts.

## Noncamera category review in DB Explorer

비카메라 카테고리에도 한국어 검토 안내를 제공합니다. `video_playback`, `video`,
`display`, `game`, `audio`, `voice_call`을 지원하며 Camera의 기존 검토 흐름을 유지합니다.

- **Overview**: 카테고리별 목적, 처리 경로, 비교 순서, 부하 요인과 드라이버 계산 한계를
  펼쳐서 확인합니다. All에서는 현재 응답에 포함된 카테고리의 안내를 제공합니다.
  등록 수는 현재 필터와 수신 결과 기준이며 여러 분류의 수치를 단순 합산하지 않습니다.
- **Scenario Catalog**: Exynos2600의 로컬 영상/YouTube, 갤러리, 로컬/스트리밍 게임,
  로컬/스트리밍 오디오, 음성/영상 통화 각각의 검토 목적을 설명합니다.
- **Variant Matrix**: 과제 / 시나리오 / variant를 선택하면 등록된 `design_conditions`의
  값과 한국어 해설을 표시합니다. false와 누락을 구분하고 이름으로 조건을 채우지 않습니다.
  선택은 설명 대상만 바꾸며 아래 전체 비교 표의 필터는 유지합니다.

Exynos2600 컨텍스트에는 **M1S = Galaxy26, M2S = GalaxyS26+**를 안내하고,
기본 모델과 Plus 모델이 같은 Exynos2600을 사용한다는 점을 설명합니다.
세부 하드웨어 구성과 동작 조건은 선택한 과제 기준으로 표시합니다.

커널 근거 패널은 IP fixture에 기록된 UFS/ABOX/MSCL의 DTS와 DPU BTS 함수 출처를
설명합니다. 커널 선언, 계산 입력 가정, 파생 계산, 실측을 구분하고 `calculated`를
실측 성공이나 KPI 통과로 해석하지 않습니다. 상세 계산 계약은
[Driver models](driver-models.md)를 참고하세요. 이 변경에서 커널 원본을 재검증하거나
드라이버 모델의 계산 범위를 확장하지는 않습니다.

구현은 `dashboard/components/category_review.py`, `category_review_view.py`이며
`tests/unit/dashboard/test_category_review.py`에서 현재 비카메라 fixture의 설명 범위,
프로젝트별 선택, 빈 조건, 부분 결과와 SoC 범위를 검증합니다. DB/ETL/API 계약은 변경하지 않습니다.
