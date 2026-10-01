# BW(메모리) 전력 모델: `mif-linear` + 실측 fit

GB당 mW 단일 계수 대신, 실측으로 SoC별 계수를 fit하고 MIF level을 명시적으로 둔다.

```
P_mem = base(MIF level) + e_rd × RD[GB/s] + e_wr × WR[GB/s]
MIF level = max(QoS lock(dvfs_sn), governor: capacity × governor_util ≥ DRAM traffic + other masters)
DRAM traffic = Σ DMA × LLC 반영 + CPU BW(profile) ; other_masters_mbs = 모델 밖 master(GPU/DPU/modem)
```

## 1. fit (`python -m scenario_db.sim.bw_fit`)

- CSV: `label, read_mbs, write_mbs, mem_power_mw` + `mif_mhz` 또는 residency 컬럼 `mif@<MHz>` (예시 `examples/bw-fit/mem_rows.csv`, SYNTHETIC).
- 측정 evidence 폴더: `--evidence-dir <db>/03_evidence --rails BUCK_MIF,BUCK_DRAM --mif-ref MIF`
  - BW: `bandwidth.mem_read/mem_write`(PMU digest `mem_bw_*_mbs`, DMC 전체 master)
  - 전력: `vdd_power`의 지정 rail 합
  - MIF level: `clock.ip_residency`(`MIF@<MHz>`) 또는 `clock.ip_dominant` (PMU digest에서 `ip_map`으로 MIF 이름 지정)
- 출력: `bw` 블록(e_rd, e_wr, level별 base_mw, fit r²/rmse) + scenario별 잔차. `--capacity 845=6000,...`로 governor capacity를 함께 기록, `--out`으로 YAML 저장.
- 경고: 행 수 < 미지수+2(under-determined), 음수 계수(level/방향 분리 안 됨 → `--same-rw` 또는 더 다양한 scenario).

## 2. 적용 (`power_model_params`)

```yaml
bw_model: mif-linear
bw:
  e_read_mw_per_gbps: 54.3
  e_write_mw_per_gbps: 69.5
  governor_util: 0.6
  other_masters_mbs: 0          # 모델 밖 traffic
  qos_lock_mhz_by_dvfs_sn: {IS_DVFS_SN_REAR_SINGLE_VIDEO_UHD60: 1539}
  mif_opps:
    - {mhz: 845, base_mw: 44.3, capacity_mbs: 6000}
    - {mhz: 1539, base_mw: 88.7, capacity_mbs: 12000}
```

결과: `power_breakdown.memory.mif` = {mif_mhz, reason(governor/qos_lock/saturated), dram_mbs, load_mbs, utilization, base_mw, other_masters_mw}. 예측↔실측 비교에서 `bandwidth.mem_read/write` delta는 모델 밖 master traffic을 뜻한다.

한계: 선형(주파수별 DRAM 에너지 차이는 base에만 반영), refresh/self-refresh 상태 미분리 → LPDDR5X 상세 모델은 같은 aggregate hook으로 교체 가능.
