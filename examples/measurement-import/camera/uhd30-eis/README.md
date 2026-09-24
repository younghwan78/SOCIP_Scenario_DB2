# Exynos2600 UHD30 EIS semantic trace fixture

**합성 데이터**이며 Exynos2600 실측값이 아니다. 15초, 30fps, 450 frame,
HW 14개와 SW 5개 task를 포함한다. OTF HW는 겹쳐 실행하고, EIS 이후
GDC_M(preview)과 GDC_O(video)는 분기한다. LME_PROCESS 이름과 상세 timing은 fixture 가정이다.

r2는 track 순서를 SW → SENSOR → RT → NRT → M2M 및 선언된 하위 순서로 지정한다.
NRT의 MTNR/MSNR/YUVP/MCSC는 OTF와 통합 interrupt를 표현하도록 frame별 시작·종료 시간이 같다.
450개 frame 각각 SENSOR_READOUT부터 두 GDC까지 18개 flow(총 8,100개)를 연결한다.
Perfetto UI에서 `SENSOR_READOUT f0000`을 선택해 해당 frame의 downstream flow를 추적할 수 있다.
화살표는 합성 fixture의 명시적 연결이며 실제 측정 latency를 뜻하지 않는다.

r3는 사용자 제공 대표 시간을 적용한다: wide sensor valid 11.8ms, IRTA 4ms,
EIS 3.2ms, NRT 4개 HW 각각 동일한 8ms, preview GDC 2.3ms, video GDC 8.6ms.
IRTA는 PRE_LME_IRTA에 적용했으며 RT HW duration은 sensor valid와 같다고 가정한다.
그 밖의 SW 시간, 시작 offset 및 min/max용 ±2% 변동은 합성 가정이다.
Video GDC는 다음 frame의 sensor와 겹친다. 정확히 15초에서 캡처를 종료하므로
마지막 video warp는 미완료이며 집계에서 제외된다(video 449개, 나머지 task 450개).
기본 100ms preview에는 완전한 이벤트 56개와 flow 53개가 포함된다.

- `uhd30-eis-15s.pftrace`: 계층 track을 포함하는 Perfetto protobuf binary.
- `mapping-template.md`: capture 조건, task/track 매핑과 논리 topology.
- `scenario-statistics.md`: TraceProcessor로 계산한 min/mean/max/samples와 추출 보고서.
- 통계는 15초 전체, DB timing preview는 기본 첫 100ms의 3 frame을 사용한다.
- 추가 CAM_DRIVER 이벤트와 capture marker는 무시한 개수로 보고한다.
- VPS/DOF는 이 LME 경로에서 실행하지 않는다. 다른 경로는 template과 canonical variant를 함께 변경한다.
- 8K30/UHD60 power saving의 GDC 생략은 별도 경로로 선택하며 fps만으로 추정하지 않는다.

## 생성과 import

`implementation/`에서 profiling extra가 설치된 환경으로 실행한다.

```powershell
uv run python scripts/generate_camera_scenario_fixture.py
uv run python -m scenario_db.meas_import.camera --markdown examples/measurement-import/camera/uhd30-eis/scenario-statistics.md --out examples/measurement-import/_generated/uhd30-eis/evidence-r3.yaml
```

생성 YAML을 Camera Profiling의 Import / Review에 올려 Preview/Save한다.
파일 변환만으로 DB에 저장되지는 않는다. API로 저장하려면 다음을 실행한다.

```powershell
uv run python -m scenario_db.meas_import.camera --markdown examples/measurement-import/camera/uhd30-eis/scenario-statistics.md --commit --api-base http://127.0.0.1:18000/api/v1
```

DB에는 Exynos2600 fixture와 migration이 필요하다. 인증은
[camera profiling 가이드](../../../../docs/guides/camera-semantic-profiling.md)를 따른다.
timing 이벤트에는 frame_index, 원본 slice 이름과 track 이름이 보존된다.
같은 ID의 다른 데이터는 덮어쓰지 않는다. 새 capture는 ID/revision을 변경한다.

## 사내 trace 확장

사내 raw parser와 importer 사이의 경계는 **Perfetto slice**다.
vendor별 kernel begin/end 이벤트를 추측해 복원하지 않는다.
TraceProcessor가 읽을 수 있는 `.ftrace`/`.pftrace` 입력을 받으며 확장자만 바꾸어 변환하지 않는다.

1. 별도 bundle 디렉터리에 trace와 template을 둔다.
2. template의 식별자, 측정 시각, 실행 조건, workload와 synthetic 설명을 실제 capture에 맞춘다.
3. task별 `trace_slice_name`(예: `~CRTA_3A`)과 `trace_track_name`(예: `Scenario / SW / ICPU`)을 함께 선언한다.
   이름은 정확한 prefix 뒤에 ` f`와 십진 frame 번호가 오는 형식이다.
4. 새 task를 tasks/enabled_task_ids에 추가하고 canonical node_refs를 지정한다.
   대응 노드가 없는 SW는 빈 node_refs와 `observation_only: true`로 통계·표시만 보존한다.
5. 전체 통계를 추출한 뒤 기존 import를 사용한다.

```powershell
uv run python -m scenario_db.meas_import.camera_scenario_trace --trace capture/semantic.ftrace --template capture/mapping-template.md --out capture/scenario-statistics.md
uv run python -m scenario_db.meas_import.camera --markdown capture/scenario-statistics.md --out capture/evidence.yaml
```

미매핑 이벤트와 종료되지 않은 slice는 제외 건수를 남긴다. 중복 매핑, 같은 task/frame의
중복 실행, 비활성 task 관측, 필수 task 표본 누락은 실패한다. 여러 stream이 frame 번호를
재사용하면 logical task/track을 분리한다. 새로운 이름 규격이나 반복 invocation은
producer adapter를 명시적으로 확장한다. 추가 metadata를 자동으로 dependency로 해석하지 않는다.

## 검증과 exploration

CRTA_3A는 현재 독립 canonical 노드가 없어 관측 전용이며 projection에서는 거부한다.
PRE_LME_IRTA는 pre_me_rta에 대응하지만 현재 target stage에는 HW가 포함되어 있어
exclusive SW projection을 하려면 target stage 분리가 먼저 필요하다.
EIS, POST_CRTA, POST_IRTA 등 지원하는 SW를 선택해 min/mean/max와 scale/delta를 적용한다.
GDC clock 후보는 기존 SW Projection/Exploration 화면과 API를 사용한다.
HW 실측 통계는 검증용이며 차기 SoC HW 시간은 target 모델로 계산한다.

importer는 frame 번호와 timestamp 순서에서 flow/latency를 추정하지 않는다. 선언된 graph는 논리 순서이며
trace에 flow가 있을 때만 preview predecessor를 연결한다. OTF HW 시간을 합산해 stage span으로
취급하지 않는다. 모든 task의 max를 선택한 결과는 실제 관측 worst frame이 아니다.

```powershell
uv run pytest tests/unit/meas_import/test_camera_scenario_trace.py tests/unit/meas_import/test_camera_semantic.py
uv run pytest tests/integration/test_camera_semantic.py
```

통합 테스트는 격리 PostgreSQL에서 strict Exynos2600 ETL, trace evidence 저장/조회,
min/mean/max SW projection과 GDC clock 300/400MHz 후보 탐색을 검증한다.
