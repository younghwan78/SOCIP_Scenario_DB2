"""SYNTHETIC full-stack timing + hand-off flow fixtures for the Behavior page (Exynos2600).

Writes one measurement evidence per scenario into ``db_Exynos2600_SM-S947B/03_evidence``:

  camrec    uc-cam-recording-e2600 / cam-rec-r1-uhd30-vdis   (frame 30 Hz, vsync 60, VPS OD ÷5, ABOX 20 ms, AAC, 1 s chunk)
  youtube   uc-vid-youtube-e2600 / yt-1080p30-h264-sdr        (video frame 30 Hz, ExoPlayer tick 10 ms, vsync, AudioFlinger 20 ms, ABOX 10 ms, segment fetch)
  playback  uc-vid-playback-local-e2600 / vplay-local-h264-fhd30-sdr (video frame 30 Hz, vsync, UFS readahead)
  game      uc-game-play-e2600 / game-fhd-60fps-sdr           (game frame 60 Hz, vsync, touch 240 Hz)

Each evidence carries a representative 250 ms window of App / Framework / HAL / Kernel / FW / HW slices with
hand-off flows (the shape ``scenario_db.meas_import.fullstack`` produces) and ``handoff_flows`` (sdb.handoff/1,
docs/design/handoff-flow-ko.md) derived from the same task table, so every flow step points at a real slice.

Timeline event fields
  task_id            unique instance id (``<common name>#f<frame>`` or ``#c<n>``)
  logical_task_id    common name shared with the in-house timing perfetto
  node_id            pipeline node when the task is a Pipeline timing item
  layer              app | framework | hal | kernel | fw | hw
  process / thread   execution context (resource_name = fullstack/<LAYER>/<process · thread>)
  frame_index        frame the work belongs to; null for own-cadence work
  predecessors       hand-off sources (task_id), ``handoff`` = kick | complete | ipc | irq | data
  cadence_period_ms  period over the full capture for own-cadence work

Values are fixture assumptions, not silicon data (provenance.collection_method: synthetic_fixture,
data_origin: synthetic). Camera EIS / HAL request / encoder feed means follow
meas-cam-rec-r1-uhd30-vdis-evt1-sw123-20260614. Replace with in-house captures.

Run from implementation/:  uv run python scripts/generate_fullstack_trace_fixture.py [--write] [--only camrec,game]
"""
from __future__ import annotations

import argparse
import hashlib
import math
import re
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_DIR = ROOT / "db_Exynos2600_SM-S947B" / "03_evidence"
WINDOW_MS = 250.0
GROUP = {"app": "APP", "framework": "FRAMEWORK", "hal": "HAL", "kernel": "KERNEL", "fw": "FW", "hw": "HW"}


def T(tid, lane, loop, dur, **kw):  # noqa: N802 - table constructor
    return {"id": tid, "lane": lane, "loop": loop, "dur": dur, **kw}


def F(fid, name, cadence, seed, k, direction, **kw):  # noqa: N802 - table constructor
    return {"id": fid, "name": name, "cadence": cadence, "seed": seed, "k": k, "dir": direction, **kw}


# ------------------------------------------------------------------ shared lanes / tasks
DISPLAY_LANES = {
    "fwk.sf": ("framework", "surfaceflinger", "main"),
    "hal.hwc": ("hal", "composer HAL", "present"),
    "k.drm": ("kernel", "exynos-drm", "commit · frame done"),
    "hw.dpu": ("hw", "DPU", "scan"),
}


def display_tasks(after: str, loop: str = "frame") -> list[dict]:
    return [
        T("sf.commit", "fwk.sf", loop, 1.4, after=[after], snap="vsync", type="ipc", jit=0.15, call="queueBuffer → commit"),
        T("hwc.present", "hal.hwc", loop, 0.9, after=["sf.commit"], type="ipc", call="presentDisplay"),
        T("drm.commit", "k.drm", loop, 0.4, after=["hwc.present"], type="kick", call="atomic commit"),
        T("dpu.scan", "hw.dpu", "vsync", 15.5, at=0.0, node="dpu", jit=0.002, src=[dict(id="drm.commit", cross=True, type="kick")],
          call="scanout"),
        T("decon.done", "k.drm", "vsync", 0.04, after=["dpu.scan"], type="irq", call="frame done IRQ"),
    ]


def mfc_decode_tasks(feed_after: str, feed_lane: str, codec: str) -> list[dict]:
    return [
        T("vdec.feed", feed_lane, "frame", 0.15, after=[feed_after], type="ipc", call="queueInputBuffer"),
        T("vdec.c2_queue", "hal.c2", "frame", 0.2, after=["vdec.feed"], type="ipc", call="C2 queue"),
        T("vdec.drv", "k.mfc", "frame", 0.08, after=["vdec.c2_queue"], type="kick", call="V4L2 QBUF"),
        T("vdec.fw", "fw.mfc", "frame", 0.1, after=["vdec.drv"], type="kick", call="FW run"),
        T("vdec.hw", "hw.mfc", "frame", 6.0, after=["vdec.fw"], node="mfc_dec", type="kick", call=f"{codec} decode"),
        T("vdec.irq", "k.mfc", "frame", 0.05, after=["vdec.hw"], type="irq", call="IRQ"),
        T("vdec.done", "hal.c2", "frame", 0.2, after=["vdec.irq"], type="complete", call="DQBUF"),
        T("vdec.out", feed_lane, "frame", 0.5, after=["vdec.done"], type="ipc", call="onWorkDone"),
    ]


# ------------------------------------------------------------------ Camera recording UHD30 VDIS
CAMREC = {
    "key": "camrec",
    "evidence_id": "meas-synth-fullstack-cam-rec-r1-uhd30-vdis-evt1-20261031",
    "scenario": "uc-cam-recording-e2600", "variant": "cam-rec-r1-uhd30-vdis",
    "derived_from": ["meas-cam-rec-r1-uhd30-vdis-evt1-sw123-20260614"],
    "lanes": {
        "app.cam": ("app", "Camera app", "CameraDevice callback"),
        "app.main": ("app", "Camera app", "main (UI)"),
        "app.ui": ("app", "Camera app", "RenderThread"),
        "fwk.csreq": ("framework", "cameraserver", "RequestThread"),
        "fwk.cs": ("framework", "cameraserver", "buffer return"),
        "fwk.enc": ("framework", "mediaserver", "encoder input feed"),
        "fwk.mux": ("framework", "mediaserver", "MPEG4Writer"),
        "fwk.aud": ("framework", "audioserver", "RecordThread"),
        "fwk.sf": ("framework", "surfaceflinger", "main"),
        "hal.req": ("hal", "camera.provider", "request"),
        "hal.vdis": ("hal", "camera.provider", "VDISCore"),
        "hal.res": ("hal", "camera.provider", "result"),
        "hal.c2": ("hal", "media.codec", "C2 HEVC enc"),
        "hal.aac": ("hal", "media.swcodec", "C2 AAC enc"),
        "hal.aud": ("hal", "audio HAL", "input stream"),
        "hal.hwc": ("hal", "composer HAL", "present"),
        "k.is": ("kernel", "pablo-is", "shot · IRQ"),
        "k.mfc": ("kernel", "exynos-mfc", "ioctl · IRQ"),
        "k.drm": ("kernel", "exynos-drm", "commit · frame done"),
        "k.abox": ("kernel", "abox", "period IRQ"),
        "k.ufs": ("kernel", "ufs", "blk · IRQ"),
        "fw.rta": ("fw", "RTA", "executor unconfirmed (AP/ICPU)"),
        "hw.sensor": ("hw", "Sensor", "rear readout"),
        "hw.rt": ("hw", "ISP RT", "CSIS → MLSC"),
        "hw.nrt": ("hw", "ISP NRT", "MTNR → MCSC"),
        "hw.lme": ("hw", "LME", "motion estimation"),
        "hw.vps": ("hw", "VPS", "object detection"),
        "hw.gdc": ("hw", "GDC", "M · O"),
        "hw.mfc": ("hw", "MFC", "HEVC enc"),
        "hw.dpu": ("hw", "DPU", "scan"),
        "hw.abox": ("hw", "ABOX", "capture"),
        "hw.ufs": ("hw", "UFS", "write"),
    },
    # loop id -> period, phase, frame-indexed?, frame shift
    "loops": {
        "frame": dict(period=100 / 3, phase=0.0, frame=True),
        "req": dict(period=100 / 3, phase=2.0, frame=True, shift=4),
        "vsync": dict(period=1000 / 60, phase=5.0),
        "abox": dict(period=20.0, phase=3.0),
        "aac": dict(period=64 / 3, phase=7.0),
        "mux": dict(period=1000.0, phase=170.0),
        "ui": dict(period=1000.0, phase=120.0),
    },
    "cadences": [
        dict(id="frame", name="Sensor frame", kind="frame", period_ms=100 / 3, loops=["frame", "req"]),
        dict(id="vsync", name="Display vsync", kind="vsync", period_ms=1000 / 60, loops=["vsync"]),
        dict(id="od", name="VPS OD", kind="divided", of="frame", every=5, note="object detection every 5th frame"),
        dict(id="abox", name="ABOX period", kind="period", period_ms=20.0, loops=["abox"], note="48 kHz · 960 samples"),
        dict(id="aac", name="AAC frame", kind="period", period_ms=64 / 3, loops=["aac"], note="1024 samples @ 48 kHz"),
        dict(id="mux", name="MPEG4 chunk", kind="chunk", period_ms=1000.0, loops=["mux"], note="interleave chunk write"),
        dict(id="ui", name="Camera UI", kind="period", period_ms=1000.0, loops=["ui"], note="recording timer / OSD · 애니메이션 중에는 vsync마다"),
    ],
    # Order inside a loop is topological. after = timing + flow, src = flow only (df = frame offset, cross = latest before).
    "tasks": [
        T("sensor.readout", "hw.sensor", "frame", 10.18, at=0.0, node="sensor_rear", jit=0.004, src=[dict(id="is.shot", df=-4, type="kick")],
          call="SOF · readout"),
        *[T(ip, "hw.rt", "frame", d, at=a, node=ip, jit=0.01, src=[dict(id=p)], thread=ip.upper(), call=f"{ip.upper()} OTF")
          for ip, d, a, p in (("csis", 10.2, 0.15, "sensor.readout"), ("pdp", 10.15, 0.25, "csis"), ("byrp", 10.1, 0.35, "pdp"),
                              ("rgbp", 10.1, 0.45, "byrp"), ("yuvsc", 10.1, 0.55, "rgbp"), ("mlsc", 10.1, 0.65, "yuvsc"))],
        T("is.irq", "k.is", "frame", 0.03, after=["mlsc"], type="irq", call="MLSC done IRQ"),
        T("rta.post_crta", "fw.rta", "frame", 0.3, after=["is.irq"], node="post_crta", type="kick", call="stats → CRTA"),
        T("rta.pre_me", "fw.rta", "frame", 3.0, after=[dict(id="rta.post_crta", gap=0.1)], node="pre_me_rta", type="kick", call="preME"),
        T("lme", "hw.lme", "frame", 2.0, after=[dict(id="rta.pre_me", anchor="start", gap=0.4)], node="lme", type="kick", call="LME kick"),
        T("rta.post_irta", "fw.rta", "frame", 4.0, after=["rta.pre_me"], node="post_irta", type="data", call="IRTA"),
        T("mtnr", "hw.nrt", "frame", 9.0, after=["rta.post_irta"], node="mtnr", type="kick", thread="MTNR", call="NRT kick"),
        T("msnr", "hw.nrt", "frame", 8.9, after=[dict(id="mtnr", anchor="start", gap=0.2)], node="msnr", thread="MSNR", call="MSNR OTF"),
        T("yuvp", "hw.nrt", "frame", 8.8, after=[dict(id="msnr", anchor="start", gap=0.2)], node="yuvp", thread="YUVP", call="YUVP OTF"),
        T("mcsc", "hw.nrt", "frame", 8.8, after=[dict(id="yuvp", anchor="start", gap=0.2)], node="mcsc", thread="MCSC", call="MCSC OTF"),
        T("vps.od", "hw.vps", "frame", 1.8, after=[dict(id="mlsc", gap=0.6)], every=5, every_at=4, cadence="od", node="vps_od", type="kick",
          call="OD kick"),
        T("nrt.irq", "k.is", "frame", 0.03, after=["mcsc"], type="irq", call="MCSC done IRQ"),
        T("eis.warp", "hal.vdis", "frame", 7.8, after=["nrt.irq"], node="eis", type="complete", jit=0.15, call="EIS + gyro"),
        T("gdc.m", "hw.gdc", "frame", 2.0, after=[dict(id="eis.warp", gap=0.2)], node="gdc_m", type="kick", thread="GDC_M",
          call="GDC_M warp"),
        T("gdc.o", "hw.gdc", "frame", 4.5, after=[dict(id="eis.warp", gap=0.25)], node="gdc_o", type="kick", thread="GDC_O",
          call="GDC_O warp"),
        T("gdc.irq", "k.is", "frame", 0.03, after=["gdc.o"], type="irq", call="GDC done IRQ"),
        T("hal.result", "hal.res", "frame", 0.5, after=["gdc.irq"], type="complete", call="processCaptureResult"),
        T("cs.return", "fwk.cs", "frame", 0.3, after=["hal.result"], type="ipc", call="returnBuffer"),
        T("app.result", "app.cam", "frame", 0.4, after=[dict(id="cs.return", gap=0.2)], type="ipc", call="onCaptureCompleted"),
        T("enc.feed", "fwk.enc", "frame", 1.1, after=["cs.return"], type="ipc", jit=0.15, call="encoder input surface"),
        T("enc.c2_queue", "hal.c2", "frame", 0.2, after=["enc.feed"], type="ipc", call="C2 queue"),
        T("enc.drv", "k.mfc", "frame", 0.08, after=["enc.c2_queue"], type="kick", call="V4L2 QBUF"),
        T("enc.hw", "hw.mfc", "frame", 7.5, after=["enc.drv"], node="mfc_enc", type="kick", call="HEVC encode"),
        T("enc.irq", "k.mfc", "frame", 0.05, after=["enc.hw"], type="irq", call="IRQ"),
        T("enc.done", "hal.c2", "frame", 0.2, after=["enc.irq"], type="complete", call="bitstream"),
        T("mux.queue", "fwk.mux", "frame", 0.3, after=["enc.done"], type="ipc", call="writeSampleData"),
        T("sf.commit", "fwk.sf", "frame", 1.4, after=["cs.return"], snap="vsync", type="ipc", jit=0.15, call="SurfaceView queueBuffer"),
        T("hwc.present", "hal.hwc", "frame", 0.9, after=["sf.commit"], type="ipc", call="presentDisplay"),
        T("drm.commit", "k.drm", "frame", 0.4, after=["hwc.present"], type="kick", call="atomic commit"),
        T("cs.request", "fwk.csreq", "req", 0.3, at=0.0, type="kick", call="processCaptureRequest"),
        T("hal.request", "hal.req", "req", 2.3, after=["cs.request"], type="ipc", jit=0.2, call="request"),
        T("is.shot", "k.is", "req", 0.05, after=["hal.request"], type="kick", call="shot · QBUF"),
        T("dpu.scan", "hw.dpu", "vsync", 15.5, at=0.0, node="dpu", jit=0.002, src=[dict(id="drm.commit", cross=True, type="kick")],
          call="scanout"),
        T("decon.done", "k.drm", "vsync", 0.04, after=["dpu.scan"], type="irq", call="frame done IRQ"),
        T("abox.dsp", "hw.abox", "abox", 0.8, at=0.0, node="abox", call="capture period"),
        T("abox.irq", "k.abox", "abox", 0.03, after=["abox.dsp"], type="irq", call="period IRQ"),
        T("aud.hal_read", "hal.aud", "abox", 0.2, after=["abox.irq"], type="complete", call="pcm read"),
        T("aud.record", "fwk.aud", "abox", 0.3, after=["aud.hal_read"], type="ipc", call="AudioRecord read"),
        T("aud.aac", "hal.aac", "aac", 0.6, at=0.0, src=[dict(id="aud.record", cross=True, type="ipc")], call="AAC encode"),
        T("mux.chunk", "fwk.mux", "mux", 4.0, at=0.0, node="mpeg_writer", src=[dict(id="mux.queue", cross=True), dict(id="aud.aac", cross=True)],
          call="chunk interleave"),
        T("ufs.blk", "k.ufs", "mux", 0.1, after=["mux.chunk"], type="kick", call="blk submit"),
        T("ufs.write", "hw.ufs", "mux", 8.0, after=["ufs.blk"], node="storage_write", type="kick", call="UFS write"),
        T("ui.tick", "app.main", "ui", 0.3, at=0.0, call="timer tick · invalidate"),
        T("ui.draw", "app.ui", "ui", 1.2, after=["ui.tick"], type="ipc", call="draw OSD (HWUI)"),
        T("sf.ui_latch", "fwk.sf", "ui", 0.3, after=["ui.draw"], snap="vsync", type="ipc", call="latch UI layer"),
    ],
    "flows": [
        F("sensor-frame", "Sensor frame", "frame", "sensor.readout", 4, "both",
          summary="request (n−4) → sensor → ISP RT → RTA → ISP NRT → EIS → GDC → preview / encode / app",
          branches={"sf.commit": "preview", "enc.feed": "encode", "app.result": "app result"},
          stop={"dpu.scan"},
          notes={"sensor.readout": "request는 4 frame 앞서 들어감 · 영상 buffer는 app을 거치지 않음",
                 "vps.od": "VPS OD는 5 frame에 한 번 (6 Hz)", "eis.warp": "VDISCore가 gyro와 함께 warp matrix 계산"}),
        F("audio-period", "Audio period", "abox", "aud.aac", 3, "up", notes_first="App은 MediaRecorder start / stop 제어만 · 주기 처리는 audioserver · mediaserver",
          summary="ABOX 20 ms period → audio HAL → AudioRecord → AAC (1024 sample)",
          notes={"abox.dsp": "frame과 무관한 독립 주기 · muxer에서 timestamp로 합류"}),
        F("camera-ui", "Camera UI", "ui", "sf.ui_latch", 0, "up",
          summary="App main (timer) → RenderThread → SurfaceFlinger: preview와 별개 layer, 다음 vsync에 함께 합성",
          notes={"ui.tick": "frame과 무관한 App loop · OSD 변화가 있을 때만 그림"}),
        F("chunk", "MPEG4 chunk", "mux", "ufs.write", 0, "up", stop={"mux.queue", "aud.aac"},
          summary="frame마다 쌓인 video sample + AAC frame → 약 1 s chunk → UFS write",
          notes={"mux.chunk": "video (30 Hz)와 audio (46.9 Hz)가 여기서 만남"}),
    ],
}

# ------------------------------------------------------------------ YouTube 1080p30 H.264
YOUTUBE = {
    "key": "youtube",
    "evidence_id": "meas-synth-fullstack-yt-1080p30-h264-sdr-evt1-20261031",
    "scenario": "uc-vid-youtube-e2600", "variant": "yt-1080p30-h264-sdr",
    "derived_from": [],
    "lanes": {
        "app.exo": ("app", "YouTube", "ExoPlayer:Playback"),
        "hal.swc": ("hal", "media.swcodec", "C2 Opus dec"),
        "fwk.af": ("framework", "audioserver", "AudioFlinger MixerThread"),
        "hal.aud": ("hal", "audio HAL", "output stream"),
        "k.abox": ("kernel", "abox", "period IRQ"),
        "hw.abox": ("hw", "ABOX", "RDMA · SRC"),
        "app.load": ("app", "YouTube", "ExoPlayer:Loader"),
        "app.net": ("app", "YouTube", "Cronet network"),
        "fwk.codec": ("framework", "MediaCodec", "CodecLooper"),
        "hal.c2": ("hal", "media.codec", "C2 AVC dec"),
        "k.mfc": ("kernel", "exynos-mfc", "ioctl · IRQ"),
        "k.net": ("kernel", "net", "wlan rx"),
        "fw.mfc": ("fw", "MFC FW", "codec scheduler"),
        "hw.mfc": ("hw", "MFC", "H.264 dec"),
        **DISPLAY_LANES,
    },
    "loops": {
        "frame": dict(period=100 / 3, phase=0.0, frame=True),
        "tick": dict(period=10.0, phase=1.0),
        "vsync": dict(period=1000 / 60, phase=5.0),
        "seg": dict(period=5000.0, phase=60.0),
        "adec": dict(period=20.0, phase=4.0),
        "amix": dict(period=20.0, phase=9.0),
        "abox": dict(period=10.0, phase=2.0),
    },
    "cadences": [
        dict(id="frame", name="Video frame", kind="frame", period_ms=100 / 3, loops=["frame"]),
        dict(id="tick", name="ExoPlayer tick", kind="period", period_ms=10.0, loops=["tick"], note="doSomeWork 10 ms"),
        dict(id="adec", name="Opus frame", kind="period", period_ms=20.0, loops=["adec"], note="20 ms Opus packet decode"),
        dict(id="amix", name="AudioFlinger mix", kind="period", period_ms=20.0, loops=["amix"], note="MixerThread period"),
        dict(id="abox", name="ABOX period", kind="period", period_ms=10.0, loops=["abox"], note="48 kHz · 480 samples"),
        dict(id="vsync", name="Display vsync", kind="vsync", period_ms=1000 / 60, loops=["vsync"]),
        dict(id="seg", name="Network segment", kind="chunk", period_ms=5000.0, loops=["seg"], note="buffer 상태에 따라 가변"),
    ],
    "tasks": [
        T("demux.read", "app.load", "frame", 0.6, at=0.0, node="sw_demux", call="readSample (fMP4)"),
        *mfc_decode_tasks("demux.read", "fwk.codec", "H.264"),
        T("play.release", "app.exo", "frame", 0.15, after=[dict(id="vdec.out", gap=1.5)], type="ipc", call="releaseOutputBuffer (AV sync)",
          src=[dict(id="aud.write", cross=True, type="ipc")]),
        *display_tasks("play.release"),
        T("play.work", "app.exo", "tick", 0.6, at=0.0, call="doSomeWork"),
        T("aud.dec", "hal.swc", "adec", 0.25, at=0.0, call="Opus decode"),
        T("aud.write", "app.exo", "tick", 0.15, after=["play.work"], src=[dict(id="aud.dec", cross=True, type="complete")], call="AudioTrack.write"),
        T("af.mix", "fwk.af", "amix", 0.45, at=0.0, src=[dict(id="aud.write", cross=True, type="ipc")], call="mix (shared buffer)"),
        T("aud.hal", "hal.aud", "amix", 0.2, after=["af.mix"], type="ipc", call="out_write"),
        T("abox.dma", "hw.abox", "abox", 0.6, at=0.0, src=[dict(id="aud.hal", cross=True, type="kick")], node="abox", call="RDMA · SRC"),
        T("abox.irq", "k.abox", "abox", 0.03, after=["abox.dma"], type="irq", call="period IRQ"),
        T("net.rx", "k.net", "seg", 0.4, at=0.0, call="wlan rx"),
        T("net.fetch", "app.net", "seg", 3.0, after=["net.rx"], node="network", type="irq", call="segment fetch"),
    ],
    "flows": [
        F("video-frame", "Video frame", "frame", "demux.read", 2, "down",
          summary="sample read → MediaCodec → C2 → MFC decode → AV sync → SurfaceFlinger → DPU",
          notes={"play.release": "audio clock 기준으로 present 시각 결정", "dpu.scan": "다음 vsync부터 scanout"}),
        F("player-tick", "Player tick", "tick", "aud.write", 4, "up",
          summary="ExoPlayer playback loop: buffer 확인 · decoder feed · decoded audio를 AudioTrack에 write",
          notes={"play.work": "10 ms마다 깨어남 (video frame과 무관)"}),
        F("audio", "Audio playback", "amix", "abox.irq", 6, "up", stop={"aud.write"},
          summary="AudioTrack shared buffer → AudioFlinger mix (20 ms) → audio HAL → ABOX (10 ms) → speaker",
          notes={"af.mix": "audio clock이 video present 시각의 기준 (AV sync)", "abox.dma": "Pipeline ABOX node · 독립 10 ms 주기 · video frame과 무관"}),
        F("segment", "Network segment", "seg", "net.fetch", 0, "up",
          summary="wlan rx → Cronet segment fetch → buffer (수 초 앞서 채움)",
          notes={"net.fetch": "DB는 network를 frame마다(30 Hz) 모델링 · 실제는 segment 단위"}),
    ],
}

# ------------------------------------------------------------------ Local playback FHD30 H.264
PLAYBACK = {
    "key": "playback",
    "evidence_id": "meas-synth-fullstack-vplay-local-h264-fhd30-sdr-evt1-20261031",
    "scenario": "uc-vid-playback-local-e2600", "variant": "vplay-local-h264-fhd30-sdr",
    "derived_from": [],
    "lanes": {
        "app.vp": ("app", "Video player", "main"),
        "fwk.ext": ("framework", "mediaserver", "NuPlayer extractor"),
        "fwk.nu": ("framework", "mediaserver", "NuPlayerDecoder"),
        "fwk.rend": ("framework", "mediaserver", "NuPlayerRenderer"),
        "hal.c2": ("hal", "media.codec", "C2 AVC dec"),
        "k.mfc": ("kernel", "exynos-mfc", "ioctl · IRQ"),
        "k.ufs": ("kernel", "ufs", "blk · IRQ"),
        "fw.mfc": ("fw", "MFC FW", "codec scheduler"),
        "hw.mfc": ("hw", "MFC", "H.264 dec"),
        "hw.ufs": ("hw", "UFS", "read"),
        **DISPLAY_LANES,
    },
    "loops": {
        "frame": dict(period=100 / 3, phase=0.0, frame=True),
        "vsync": dict(period=1000 / 60, phase=5.0),
        "read": dict(period=500.0, phase=40.0),
        "ui": dict(period=1000.0, phase=150.0),
    },
    "cadences": [
        dict(id="frame", name="Video frame", kind="frame", period_ms=100 / 3, loops=["frame"]),
        dict(id="vsync", name="Display vsync", kind="vsync", period_ms=1000 / 60, loops=["vsync"]),
        dict(id="read", name="UFS readahead", kind="chunk", period_ms=500.0, loops=["read"], note="page cache readahead"),
        dict(id="ui", name="Player UI", kind="period", period_ms=1000.0, loops=["ui"], note="seek bar update"),
    ],
    "tasks": [
        T("ext.read", "fwk.ext", "frame", 0.8, at=0.0, call="readSampleData"),
        *mfc_decode_tasks("ext.read", "fwk.nu", "H.264"),
        T("rend.post", "fwk.rend", "frame", 0.3, after=[dict(id="vdec.out", gap=1.2)], type="ipc", call="onRenderBuffer (AV sync)"),
        *display_tasks("rend.post"),
        T("ufs.blk", "k.ufs", "read", 0.1, at=0.0, call="readahead submit"),
        T("ufs.read", "hw.ufs", "read", 2.0, after=["ufs.blk"], node="storage", type="kick", call="UFS read 2 MB"),
        T("ufs.irq", "k.ufs", "read", 0.05, after=["ufs.read"], type="irq", call="completion IRQ"),
        T("ui.draw", "app.vp", "ui", 1.0, at=0.0, call="seek bar draw"),
    ],
    "flows": [
        F("video-frame", "Video frame", "frame", "ext.read", 2, "down",
          summary="extractor read → NuPlayerDecoder → C2 → MFC decode → renderer → SurfaceFlinger → DPU",
          notes={"ext.read": "page cache에서 읽음 · UFS 접근은 readahead 주기에서만", "dpu.scan": "다음 vsync부터 scanout"}),
        F("readahead", "UFS readahead", "read", "ufs.irq", 0, "up",
          summary="readahead submit → UFS read → completion (frame과 무관한 chunk)",
          notes={"ufs.read": "DB는 storage를 frame마다(30 Hz) 모델링 · 실제는 chunk 단위"}),
    ],
}

# ------------------------------------------------------------------ Game FHD 60 fps
GAME = {
    "key": "game",
    "evidence_id": "meas-synth-fullstack-game-fhd-60fps-sdr-evt1-20261031",
    "scenario": "uc-game-play-e2600", "variant": "game-fhd-60fps-sdr",
    "derived_from": [],
    "lanes": {
        "app.main": ("app", "Game", "GameThread"),
        "app.render": ("app", "Game", "RenderThread"),
        "app.input": ("app", "Game", "input receiver"),
        "fwk.choreo": ("framework", "Game (libgui)", "Choreographer"),
        "fwk.input": ("framework", "system_server", "InputDispatcher"),
        "fwk.sf": ("framework", "surfaceflinger", "main"),
        "hal.gpu": ("hal", "GPU UMD", "vkQueueSubmit"),
        "hal.hwc": ("hal", "composer HAL", "present"),
        "k.gpu": ("kernel", "mali kbase", "job · IRQ"),
        "k.input": ("kernel", "input", "touch IRQ"),
        "k.drm": ("kernel", "exynos-drm", "commit · frame done"),
        "fw.gpu": ("fw", "GPU FW", "CSF scheduler"),
        "hw.gpu": ("hw", "GPU", "render"),
        "hw.dpu": ("hw", "DPU", "scan"),
    },
    "loops": {
        "frame": dict(period=1000 / 60, phase=0.0, frame=True),
        "vsync": dict(period=1000 / 60, phase=12.0),
        "touch": dict(period=1000 / 240, phase=0.7),
    },
    "cadences": [
        dict(id="frame", name="Game frame", kind="frame", period_ms=1000 / 60, loops=["frame"]),
        dict(id="vsync", name="Display vsync", kind="vsync", period_ms=1000 / 60, loops=["vsync"]),
        dict(id="touch", name="Touch report", kind="period", period_ms=1000 / 240, loops=["touch"], note="240 Hz · 터치 중에만"),
    ],
    "tasks": [
        T("choreo.frame", "fwk.choreo", "frame", 0.1, at=0.0, call="doFrame"),
        T("game.update", "app.main", "frame", 4.0, after=["choreo.frame"], node="cpu", type="ipc", jit=0.15,
          src=[dict(id="app.touch", cross=True, type="data")], call="update · input 반영"),
        T("render.record", "app.render", "frame", 2.0, after=["game.update"], type="ipc", jit=0.1, call="command record"),
        T("gpu.submit", "hal.gpu", "frame", 0.3, after=["render.record"], type="ipc", call="vkQueueSubmit"),
        T("gpu.job", "k.gpu", "frame", 0.05, after=["gpu.submit"], type="kick", call="job submit"),
        T("gpu.sched", "fw.gpu", "frame", 0.05, after=["gpu.job"], type="kick", call="CSF schedule"),
        T("gpu.render", "hw.gpu", "frame", 9.0, after=["gpu.sched"], node="gpu", type="kick", jit=0.08, call="render pass"),
        T("gpu.irq", "k.gpu", "frame", 0.05, after=["gpu.render"], type="irq", call="job done IRQ"),
        T("present", "app.render", "frame", 0.2, after=["gpu.irq"], type="complete", call="vkQueuePresent"),
        *display_tasks("present"),
        T("touch.irq", "k.input", "touch", 0.05, at=0.0, call="touch IRQ"),
        T("input.dispatch", "fwk.input", "touch", 0.3, after=["touch.irq"], type="irq", call="InputDispatcher"),
        T("app.touch", "app.input", "touch", 0.2, after=["input.dispatch"], type="ipc", call="onTouchEvent"),
    ],
    "flows": [
        F("game-frame", "Game frame", "frame", "choreo.frame", 3, "down",
          summary="Choreographer → GameThread → RenderThread → GPU → SurfaceFlinger → DPU",
          notes={"game.update": "가장 최근 touch 입력을 반영", "dpu.scan": "다음 vsync부터 scanout"}),
        F("touch", "Touch input", "touch", "touch.irq", 10, "down", stop={"game.update"}, require="game.update",
          summary="touch IRQ → InputDispatcher → app → 다음 game frame update",
          notes={"touch.irq": "240 Hz로 들어오지만 game은 60 Hz로 소비"}),
    ],
}

SPECS = {s["key"]: s for s in (CAMREC, YOUTUBE, PLAYBACK, GAME)}


# ------------------------------------------------------------------ engine
def _jitter(tid: str, k: int, amp: float) -> float:
    h = int(hashlib.sha256(f"{tid}#{k}".encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
    return 1.0 + amp * (h * 2.0 - 1.0)


def _next_tick(loop: dict, t: float) -> float:
    n = math.ceil((t - loop["phase"]) / loop["period"] - 1e-9)
    return loop["phase"] + n * loop["period"]


def simulate(spec: dict) -> tuple[list[dict], dict[str, dict]]:
    """Every task instance in and around the window: [{t, k, s, e, frame, key, preds, handoff}]."""
    loops, tasks = spec["loops"], spec["tasks"]
    inst: dict[str, dict] = {}
    by_task: dict[str, list[dict]] = {}
    order: list[dict] = []
    for loop_id, loop in loops.items():
        mine = [t for t in tasks if t["loop"] == loop_id]
        k = math.floor((-170 - loop["phase"]) / loop["period"])
        while (tick := loop["phase"] + k * loop["period"]) <= WINDOW_MS + 40:
            for t in mine:
                if t.get("every") and k % t["every"] != t.get("every_at", 0):
                    continue
                start = tick + t.get("at", 0.0)
                for a in t.get("after", []):
                    a = a if isinstance(a, dict) else {"id": a}
                    p = inst.get(f"{a['id']}#{k}")
                    if p:
                        start = max(start, (p["s"] if a.get("anchor") == "start" else p["e"]) + a.get("gap", 0.05))
                if t.get("snap"):
                    start = _next_tick(loops[t["snap"]], start) + 0.3
                dur = t["dur"] * _jitter(t["id"], k, t.get("jit", 0.06))
                frame = k + loop.get("shift", 0) if loop.get("frame") else None
                x = {"t": t, "k": k, "s": start, "e": start + dur, "frame": frame,
                     "key": f"{t['id']}#f{frame}" if frame is not None else f"{t['id']}#c{k}"}
                inst[f"{t['id']}#{k}"] = x
                by_task.setdefault(t["id"], []).append(x)
                order.append(x)
            k += 1
    for xs in by_task.values():
        xs.sort(key=lambda x: x["s"])

    def latest_before(tid: str, at: float) -> dict | None:
        best = None
        for x in by_task.get(tid, []):
            if x["s"] > at:
                break
            if x["e"] <= at + 1e-6:
                best = x
        return best

    for x in order:
        t = x["t"]
        preds, handoff = [], t.get("type", "data")
        for a in t.get("after", []):
            a = a if isinstance(a, dict) else {"id": a}
            p = inst.get(f"{a['id']}#{x['k']}")
            if p:
                preds.append(p)
        for f in t.get("src", []):
            p = latest_before(f["id"], x["s"]) if f.get("cross") else inst.get(f"{f['id']}#{x['k'] + f.get('df', 0)}")
            if p:
                preds.append(p)
                handoff = f.get("type", handoff)
        x["preds"], x["handoff"] = preds, handoff
    return order, inst


def _in_window(x: dict) -> bool:
    return 0 <= x["s"] <= WINDOW_MS


def timeline_events(spec: dict, order: list[dict]) -> list[dict]:
    events = []
    for x in sorted(order, key=lambda v: (v["s"], v["key"])):
        if not _in_window(x):
            continue
        t = x["t"]
        layer, process, thread = spec["lanes"][t["lane"]]
        thread = t.get("thread", thread)
        loop = spec["loops"][t["loop"]]
        ev: dict[str, Any] = {
            "task_id": x["key"], "logical_task_id": t["id"], "layer": layer, "process": process, "thread": thread,
            "resource_name": f"fullstack/{GROUP[layer]}/{process} · {thread}",
            "task_type": "hw" if layer == "hw" else "sw", "frame_index": x["frame"],
            "start_ms": round(x["s"], 4), "end_ms": round(x["e"], 4), "duration_ms": round(x["e"] - x["s"], 4),
            "predecessors": [p["key"] for p in x["preds"]], "handoff": x["handoff"],
        }
        if t.get("node"):
            ev["node_id"] = t["node"]
        if not loop.get("frame"):
            ev["cadence_period_ms"] = round(loop["period"], 4)
        elif t.get("every"):
            ev["cadence_period_ms"] = round(loop["period"] * t["every"], 4)
        events.append(ev)
    return events


# ------------------------------------------------------------------ hand-off flows (sdb.handoff/1)
def _participant_id(spec: dict, lane: str) -> str:
    layer, process, _ = spec["lanes"][lane]
    return f"{layer}." + re.sub(r"[^a-z0-9]+", "-", process.lower()).strip("-")


def participants(spec: dict) -> list[dict]:
    out: dict[str, dict] = {}
    for lane, (layer, process, thread) in spec["lanes"].items():
        pid = _participant_id(spec, lane)
        p = out.setdefault(pid, {"id": pid, "layer": layer, "name": process, "threads": []})
        if thread not in p["threads"]:
            p["threads"].append(thread)
    order = list(GROUP)
    return [{"id": p["id"], "layer": p["layer"], "name": p["name"], "detail": " · ".join(p["threads"])}
            for p in sorted(out.values(), key=lambda p: order.index(p["layer"]))]


def cadences(spec: dict) -> list[dict]:
    return [{k: (round(v, 4) if isinstance(v, float) else v) for k, v in c.items() if k != "loops"} for c in spec["cadences"]]


def _cadence_of(spec: dict, task: dict) -> str:
    if task.get("cadence"):
        return task["cadence"]
    return next(c["id"] for c in spec["cadences"] if task["loop"] in c.get("loops", []))


def _closure(seed: dict, f: dict, down: dict[str, list[dict]]) -> dict[str, dict]:
    stop = f.get("stop", set())
    members = {seed["key"]: seed}
    if f["dir"] in ("up", "both"):
        stack = [seed]
        while stack:
            x = stack.pop()
            if x is not seed and x["t"]["id"] in stop:
                continue
            for p in x["preds"]:
                if p["key"] not in members:
                    members[p["key"]] = p
                    stack.append(p)
    if f["dir"] in ("down", "both"):
        stack = [seed]
        while stack:
            x = stack.pop()
            if x is not seed and x["t"]["id"] in stop:
                continue
            nexts = sorted(down.get(x["key"], []), key=lambda n: n["s"])
            # a cross-cadence consumer can pick the same output up again (DPU rescans the last commit): keep the first
            firsts = [n for i, n in enumerate(nexts) if all(m["t"]["id"] != n["t"]["id"] for m in nexts[:i])]
            for n in firsts:
                if n["key"] not in members:
                    members[n["key"]] = n
                    stack.append(n)
    return members


def flow(spec: dict, f: dict, order: list[dict]) -> dict:
    """Closure of one seed instance (upstream / downstream / both), ordered by time; branches become par blocks.

    ``require``: take the first seed instance from ``k`` on whose closure reaches that task (a 240 Hz touch
    report is only consumed when it is the latest one before a game frame update)."""
    down: dict[str, list[dict]] = {}
    for x in order:
        for p in x["preds"]:
            down.setdefault(p["key"], []).append(x)
    for seed in sorted((x for x in order if x["t"]["id"] == f["seed"] and x["k"] >= f["k"]), key=lambda x: x["k"]):
        members = _closure(seed, f, down)
        if not f.get("require") or any(m["t"]["id"] == f["require"] for m in members.values()):
            break
    else:
        raise SystemExit(f"{spec['key']}/{f['id']}: no seed instance reaches {f.get('require')}")
    xs = sorted(members.values(), key=lambda x: (x["s"], x["e"]))
    missing = [x["key"] for x in xs if not _in_window(x)]
    if missing:
        raise SystemExit(f"{spec['key']}/{f['id']}: steps outside the {WINDOW_MS:.0f} ms window: {missing}")
    # branch: inherited downstream from its root
    branch: dict[str, str] = {}
    for x in xs:
        b = f.get("branches", {}).get(x["t"]["id"])
        if b is None:
            b = next((branch[p["key"]] for p in x["preds"] if p["key"] in branch), None)
        if b is not None:
            branch[x["key"]] = b
    labels = list(dict.fromkeys(f.get("branches", {}).values()))
    trunk = [x for x in xs if x["key"] not in branch]
    ordered = trunk + [x for b in labels for x in xs if branch.get(x["key"]) == b]
    t0 = xs[0]["s"]

    steps: list[dict] = []
    if f.get("notes_first"):
        steps.append({"note": f["notes_first"], "over": [_participant_id(spec, ordered[0]["t"]["lane"])]})
    for x in ordered:
        t = x["t"]
        if t["id"] in f.get("notes", {}):
            steps.append({"note": f["notes"][t["id"]], "over": [_participant_id(spec, t["lane"])]})
        prim = max((p for p in x["preds"] if p["key"] in members), key=lambda p: p["e"], default=None)
        step: dict[str, Any] = {}
        if prim is not None:
            step["from"] = _participant_id(spec, prim["t"]["lane"])
        step |= {"to": _participant_id(spec, t["lane"]), "call": t.get("call", t["id"]), "task": t["id"], "slice": x["key"]}
        if t.get("node"):
            step["node"] = t["node"]
        if prim is not None and x["handoff"] != "data":
            step["handoff"] = x["handoff"]
        if x["key"] in branch:
            step["branch"] = branch[x["key"]]
        cad = _cadence_of(spec, t)
        if cad != f["cadence"]:
            step["cadence"] = cad
        if t.get("every"):
            step["every"] = t["every"]
        # same frame, issued on an earlier tick (camera request n−4)
        if seed["frame"] is not None and x["frame"] == seed["frame"] and x["k"] != seed["k"]:
            step["frame_offset"] = x["k"] - seed["k"]
        step |= {"t_ms": round(x["s"] - t0, 3), "dur_ms": round(x["e"] - x["s"], 3)}
        steps.append(step)
    return {"id": f["id"], "name": f["name"], "cadence": f["cadence"], "summary": f["summary"], "steps": steps}


def handoff_doc(spec: dict, order: list[dict]) -> dict:
    return {"format": "sdb.handoff/1", "generator": "generate_fullstack_trace_fixture.py (synthetic)",
            "participants": participants(spec), "cadences": cadences(spec),
            "flows": [flow(spec, f, order) for f in spec["flows"]]}


# ------------------------------------------------------------------ document
HEADER = """# SYNTHETIC full-stack timing + hand-off flow fixture (Behavior page) - not silicon data.
# Generated by scripts/generate_fullstack_trace_fixture.py: 250 ms window of App/Framework/HAL/Kernel/FW/HW
# slices with hand-off flows, same shape as a full-stack perfetto import, plus handoff_flows (sdb.handoff/1).
# Replace with an in-house capture.
"""


def document(spec: dict, events: list[dict], handoff: dict) -> dict:
    doc: dict[str, Any] = {
        "id": spec["evidence_id"],
        "schema_version": "2.2",
        "kind": "evidence.measurement",
        "scenario_ref": spec["scenario"],
        "variant_ref": spec["variant"],
        "project_ref": "proj-sm-s947b",
        "measured_at": "2026-10-31T10:00:00+09:00",
    }
    if spec["derived_from"]:
        doc["derived_from"] = spec["derived_from"]
    doc |= {
        "execution_context": {"silicon_rev": "EVT1", "sw_baseline_ref": "sw-vendor-v1.2.3", "thermal": "room",
                              "ambient_temp_c": 25.0, "power_state": "discharging", "method": "measurement"},
        "provenance": {"device_id": "SYNTHETIC", "collection_method": "synthetic_fixture", "data_origin": "synthetic",
                       "collection_tool_versions": {"generator": "generate_fullstack_trace_fixture.py"},
                       "sample_count": 1, "duration_per_sample_s": WINDOW_MS / 1000.0},
        "aggregation": {"strategy": "single_run"},
        "timeline_events": events,
        "handoff_flows": handoff,
    }
    return doc


def _flow_line(item: dict) -> str:
    return yaml.safe_dump(item, default_flow_style=True, allow_unicode=True, sort_keys=False, width=100000).strip()


def render(spec: dict) -> str:
    order, _ = simulate(spec)
    doc = document(spec, timeline_events(spec, order), handoff_doc(spec, order))
    events = doc.pop("timeline_events")
    handoff = doc.pop("handoff_flows")
    out = [HEADER, yaml.safe_dump(doc, allow_unicode=True, sort_keys=False, width=120), "timeline_events:\n"]
    out += [f"- {_flow_line(ev)}\n" for ev in events]
    out.append(f"handoff_flows:\n  format: {handoff['format']}\n  generator: {handoff['generator']}\n  participants:\n")
    out += [f"  - {_flow_line(p)}\n" for p in handoff["participants"]]
    out.append("  cadences:\n")
    out += [f"  - {_flow_line(c)}\n" for c in handoff["cadences"]]
    out.append("  flows:\n")
    for f in handoff["flows"]:
        head = {k: v for k, v in f.items() if k != "steps"}
        out.append("  - " + yaml.safe_dump(head, allow_unicode=True, sort_keys=False, width=120).replace("\n", "\n    ").rstrip() + "\n")
        out.append("    steps:\n")
        out += [f"    - {_flow_line(s)}\n" for s in f["steps"]]
    return "".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--write", action="store_true", help="write the evidence files")
    ap.add_argument("--only", default=",".join(SPECS), help="comma-separated: " + ", ".join(SPECS))
    args = ap.parse_args()
    for key in args.only.split(","):
        spec = SPECS[key.strip()]
        text = render(spec)
        out = EVIDENCE_DIR / f"{spec['evidence_id']}.yaml"
        if args.write:
            out.write_text(text, encoding="utf-8", newline="\n")
            print(f"wrote {out.relative_to(ROOT)}")
        else:
            print(f"--- {out.name} ({len(text.splitlines())} lines)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
