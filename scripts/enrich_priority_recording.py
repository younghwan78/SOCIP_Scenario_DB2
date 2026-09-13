"""Materialize priority recording assumptions; run before verification/strict ETL."""
from copy import deepcopy
from pathlib import Path
import yaml
import json

ROOT = Path(__file__).resolve().parents[1] / "db_fixtures_Exynos2600_S26Plus"
CPU = "ip-cpu-s5e9965"
CORE = ["csis", "pdp", "byrp", "rgbp", "yuvsc", "mlsc", "mtnr", "msnr", "yuvp", "mcsc"]
PRIORITY = ["cam-rec-r1-fhd30-vdis", "cam-rec-r1-fhd60-supersteady", "cam-rec-r1-uhd30-vdis", "cam-rec-r1-uhd60-supersteady", "cam-rec-r1-8k30-sdr", "cam-rec-r1-fhd120", "cam-rec-r1-fhd240", "cam-rec-r1-uhd120"]
NOTE = "Engineering assumption approved for fixture exploration; replace with internal measurements."


def read(path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def write(path, data):
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


def sw(low, mean, high):
    return {"min_ms": low, "mean_ms": mean, "max_ms": high, "value_source": "assumed", "source_note": NOTE}


def cpu_node(id):
    return {"id": id, "ip_ref": CPU, "role": "sw_task", "instance_index": 0}


def control(a, b):
    return {"from": a, "to": b, "type": "control"}


def image_io(port, direction, size, fmt="YUV420", bits=8):
    w, h = map(int, size.split("x"))
    return {"port": port, "direction": direction, "width": w, "height": h, "format": fmt, "bitwidth": bits}


def writer(v, encoder, rate):
    v["design_conditions"].update(record_bitrate_mbps=rate, bitrate_source="assumed", writer_model="linear_bitrate_wall_time", storage_model="sustained_write_assumed")
    patch = v.setdefault("topology_patch", {})
    patch["add_nodes"] = [n for n in patch.get("add_nodes", []) if n["id"] not in {"mpeg_writer", "storage_write"}] + [cpu_node("mpeg_writer"), cpu_node("storage_write")]
    patch["add_edges"] = [e for e in patch.get("add_edges", []) if e["to"] not in {"mpeg_writer", "storage_write"}] + [control(encoder, "mpeg_writer"), control("mpeg_writer", "storage_write")]
    config = v["node_configs"]
    config["mpeg_writer"] = {"sw_timing": sw(2, 4, 8), "sw_bitrate_scaling": {"reference_bitrate_mbps": 1000}, "memory_io": [
        {"port": "CPU_BITSTREAM_READ", "direction": "read", "bitrate_condition": "record_bitrate_mbps"},
        {"port": "CPU_BITSTREAM_WRITE", "direction": "write", "bitrate_condition": "record_bitrate_mbps"}], "timeline_resource_id": "CPU_WRITER", "source_note": NOTE}
    config["storage_write"] = {"sw_timing": sw(4, 8, 16), "sw_bitrate_scaling": {"reference_bitrate_mbps": 1000},
        "timeline_resource_id": "STORAGE_IO", "memory_io": [{"port": "STORAGE_BITSTREAM_READ", "direction": "read", "bitrate_condition": "record_bitrate_mbps"}],
        "source_note": "I/O completion wall time, not CPU active execution; no UFS capacity sign-off. " + NOTE}
    config.setdefault(encoder, {})["memory_io"] = [{"port": "APV_WDMA_BITSTREAM" if encoder == "apv_enc" else "MFC_WDMA_BITSTREAM", "direction": "write", "bitrate_condition": "record_bitrate_mbps"}]


def remap(value, mapping):
    if isinstance(value, str):
        return mapping.get(value, value)
    if isinstance(value, list):
        return [remap(x, mapping) for x in value]
    if isinstance(value, dict):
        return {mapping.get(k, k): remap(v, mapping) for k, v in value.items()}
    return value


def sync_import_bundle():
    path = ROOT / "import_bundle.json"
    bundle = json.loads(path.read_text(encoding="utf-8"))
    bundle["payload"]["documents"] = [read(p) for folder in ["00_hw", "01_sw", "02_definition"] for p in sorted((ROOT / folder).glob("*.yaml")) if read(p).get("kind") != "sim.config_profile"]
    path.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    path = ROOT / "02_definition/uc-camera-recording.yaml"
    raw = read(path)
    sensor_path = ROOT / "00_hw/ip-sensor-gng-s5e9965.yaml"
    sensor = read(sensor_path)
    mode_id = "user_raw10_7680x4620_30fps"
    modes = sensor["capabilities"]["properties"]["modes"]
    mode = deepcopy(modes["cis_full_ln1_raw10_8000x4500_30fps_2969msps"])
    mode.update(active_size=[7680, 4620], sensor_size=[7680, 4620], sensor_fps=30, source_note="User-confirmed 8K30 size; line/register timing borrowed from 8000x4500 and unverified.", provenance_status="user_size_assumed_timing")
    modes[mode_id] = mode
    if not any(m["id"] == mode_id for m in sensor["capabilities"]["operating_modes"]):
        sensor["capabilities"]["operating_modes"].append({"id": mode_id})
    write(sensor_path, sensor)
    front_path = ROOT / "00_hw/ip-sensor-imx874-s5e9965.yaml"
    front = read(front_path)
    front_mode = deepcopy(front["capabilities"]["properties"]["modes"]["mode10"])
    front_mode.update(active_size=[4000, 3000], source_note="DTS mode10 with full 4:3 ingress; downstream 16:9 MCSC crop assumed.")
    front["capabilities"]["properties"]["modes"]["dual_full_4000x3000_30fps"] = front_mode
    if not any(m["id"] == "dual_full_4000x3000_30fps" for m in front["capabilities"]["operating_modes"]):
        front["capabilities"]["operating_modes"].append({"id": "dual_full_4000x3000_30fps"})
    write(front_path, front)
    variants = {v["id"]: v for v in raw["variants"]}
    base_anchors = {k:v for k,v in raw["size_profile"]["anchors"].items() if not k.startswith("front_")}
    raw["size_profile"]["anchors"].update({"front_" + k: v for k, v in base_anchors.items()})
    for id in PRIORITY:
        v = variants[id]
        v["design_conditions"].update(priority_recording=True, verification_scope="priority_model_assumed", input_ratio="16:9")
        if "8k30" in id:
            v["node_configs"]["sensor_rear"]["selected_mode"] = "user_raw10_7680x4620_30fps"
            v["design_conditions"].update(sensor_input_fps=30, sensor_input_source="user_confirmed", sensor_runtime_confirmation=True, input_ratio="7680:4620", output_ratio="16:9")
            for anchor in ["sensor_full", "mlsc_out", "pyramid_l0"]:
                v["size_overrides"][anchor] = "7680x4620"
            w, h = 7680, 4620
            for layer in range(1, 5):
                w, h = (w+1)//2, (h+1)//2
                v["size_overrides"][f"pyramid_l{layer}"] = f"{w}x{h}"
            for node in CORE:
                v["node_configs"][node]["sim"].update(width=7680, height=4620)
        writer(v, "mfc_enc", 120 if "8k" in id else 80 if "uhd" in id else 30)
    reference = variants["cam-rec-r1-8k30-sdr"]
    for id, v in variants.items():
        if id.startswith("cam-rec-r1-8k30-") and not v.get("derived_from_variant"):
            v["size_overrides"].update(deepcopy(reference["size_overrides"]))
            v["node_configs"]["sensor_rear"] = deepcopy(reference["node_configs"]["sensor_rear"])
            for node in CORE:
                v["node_configs"][node]["sim"].update(width=7680, height=4620)
    # Dual is two logical streams on shared physical camera IPs, then SW composition.
    clone_ids = CORE + ["lme", "vps_od", "post_crta", "pre_me_rta", "post_irta"]
    node_map = {n["id"]: n for n in raw["pipeline"]["nodes"]}
    for resolution in ["fhd", "uhd"]:
        parent = variants[f"cam-rec-r1-{resolution}30-sdr"]
        for id in [f"cam-rec-pip-{resolution}30", f"cam-rec-rcv-{resolution}30-sdr"]:
            v = deepcopy(parent)
            v["id"] = id
            v["design_conditions"].update(priority_recording=True, camera_mode="dual_async", sensor_place="rear_and_front", fps=30,
                stream_model="wide_plus_front_shared_hw", composition_source="assumed_CPU_PIP", sensor_runtime_confirmation=True)
            v["routing_switch"]["disabled_nodes"] = [n for n in v["routing_switch"]["disabled_nodes"] if n != "sensor_front"]
            patch = v.setdefault("topology_patch", {})
            patch.setdefault("remove_edges", []).append({"from": "sensor_front", "to": "csis"})
            mapping = {n: "front_" + n for n in clone_ids}
            buffer_ids = set()
            edges = []
            for e in raw["pipeline"]["edges"]:
                if e["from"] in clone_ids and e["to"] in clone_ids:
                    edges.append(deepcopy(e))
                    if e.get("buffer"):
                        buffer_ids.add(e["buffer"])
            buffer_ids |= {k for k, b in raw["pipeline"]["buffers"].items() if b.get("history", {}).get("node_id") in clone_ids or b.get("dma", {}).get("node_id") in clone_ids}
            mapping.update({k: "FRONT_" + k for k in buffer_ids})
            anchors = {k: "front_" + k for k in base_anchors}
            mapping.update(anchors)
            for k in buffer_ids:
                raw["pipeline"]["buffers"][mapping[k]] = remap(deepcopy(raw["pipeline"]["buffers"][k]), mapping)
            patch["add_nodes"] = [remap(deepcopy(node_map[n]), mapping) for n in clone_ids] + [cpu_node("dual_compose")]
            patch.setdefault("add_edges", []).extend(remap(edges, mapping) + [{"from": "sensor_front", "to": "front_csis", "type": "OTF"}])
            cfg = v["node_configs"]
            for n in clone_ids:
                cfg[mapping[n]] = remap(deepcopy(cfg[n]), mapping)
                resource = "STAGE_LME" if n == "pre_me_rta" else "CPU_CAMERA" if n in {"post_crta", "post_irta"} else n
                cfg[n]["timeline_resource_id"] = resource
                cfg[mapping[n]]["timeline_resource_id"] = resource
            cfg["sensor_front"] = {"selected_mode": "dual_full_4000x3000_30fps", "source_note": "4000x3000 30fps DTS candidate; 16:9 crop is assumed."}
            for k, value in v["size_overrides"].copy().items():
                v["size_overrides"]["front_" + k] = value
            for k in ["sensor_full", "mlsc_out", "pyramid_l0"]:
                v["size_overrides"]["front_" + k] = "4000x3000"
            w, h = 4000, 3000
            for layer in range(1, 5):
                w, h = (w + 1)//2, (h + 1)//2
                v["size_overrides"][f"front_pyramid_l{layer}"] = f"{w}x{h}"
            for n in CORE:
                cfg["front_" + n]["sim"].update(width=4000, height=3000)
            out = v["size_overrides"]["record_out"]
            cfg["dual_compose"] = {"sw_timing": sw(1.5, 3, 6), "source_note": NOTE,
                "memory_io": [image_io("CPU_IMAGE_READ", "read", out), image_io("CPU_FRONT_READ", "read", out), image_io("CPU_IMAGE_WRITE", "write", out)]}
            if out != v["size_overrides"]["preview_out"]:
                cfg["dual_compose"]["memory_io"].append(image_io("CPU_PREVIEW_WRITE", "write", v["size_overrides"]["preview_out"]))
            # Remove direct output bypasses so encode/display wait for composition.
            patch["add_edges"] = [e for e in patch["add_edges"] if e["to"] not in {"dpu", "mfc_enc"}]
            patch["add_edges"] += [control("mcsc", "dual_compose"), control("front_mcsc", "dual_compose"), control("dual_compose", "mfc_enc"), control("dual_compose", "dpu")]
            for e in raw["pipeline"]["edges"]:
                if e["to"] in {"dpu", "mfc_enc"}:
                    patch.setdefault("remove_edges", []).append({"from": e["from"], "to": e["to"]})
            # Explicit scaler output writes and encoder/display reads after SW composition.
            for n in ["mcsc", "front_mcsc"]:
                cfg[n]["memory_io"] = [image_io("MCSC_WDMA_W0", "write", out)]
            cfg["mfc_enc"]["memory_io"] = [image_io("MFC_RDMA", "read", out)]
            cfg["dpu"]["memory_io"] = [image_io("DPU_RDMA", "read", v["size_overrides"]["preview_out"])]
            cfg["mcsc"]["active_output_ports"] = ["MCSC_WDMA_W0"]
            cfg["front_mcsc"]["active_output_ports"] = ["MCSC_WDMA_W0"]
            v["design_conditions"]["mcsc_dma_channels"] = 1
            writer(v, "mfc_enc", 80 if resolution == "uhd" else 30)
            cfg["mfc_enc"]["memory_io"].append(image_io("MFC_RDMA", "read", out))
            variants[id] = v
        # Portrait uses SEG + CPU bokeh as an explicit unverified placement assumption.
        v = deepcopy(parent)
        v["id"] = f"cam-rec-r1-{resolution}30-portrait"
        v["design_conditions"].update(priority_recording=True, fps=30, portrait=True, portrait_hw_source="assumed_VPS_SEG_CPU_bokeh", sensor_runtime_confirmation=True)
        v["routing_switch"]["disabled_nodes"] = [n for n in v["routing_switch"]["disabled_nodes"] if n != "vps_seg"]
        patch = v.setdefault("topology_patch", {})
        patch["add_nodes"] = [cpu_node("portrait_blend")]
        patch.setdefault("remove_edges", []).extend([{"from": "mlsc", "to": "vps_seg"}, {"from": "vps_seg", "to": "mtnr"}])
        patch["add_edges"] = [e for e in patch.get("add_edges", []) if e["to"] not in {"dpu", "mfc_enc"}]
        patch["add_edges"] += [{"from": "mlsc", "to": "vps_seg", "type": "M2M", "buffer": "OD_INPUT", "port_pairs": [{"src": "MLSC_W_FDPIG", "dst": "VPS_RDMA"}]}, control("vps_seg", "portrait_blend"), control("mcsc", "portrait_blend"), control("portrait_blend", "mfc_enc"), control("portrait_blend", "dpu")]
        for e in raw["pipeline"]["edges"]:
            if e["to"] in {"dpu", "mfc_enc"}:
                patch["remove_edges"].append({"from": e["from"], "to": e["to"]})
        cfg = v["node_configs"]
        cfg["vps_seg"] = {"sim": {"width": 512, "height": 288, "inherit_shape": True}, "timeline_resource_id": "VPS", "source_note": NOTE,
            "memory_io": [image_io("VPS_WDMA", "write", "512x288", "Y")]}
        cfg["vps_od"]["timeline_resource_id"] = "VPS"
        out = v["size_overrides"]["record_out"]
        scale = 2 if resolution == "uhd" else 1
        cfg["portrait_blend"] = {"sw_timing": sw(2*scale, 4*scale, 8*scale), "memory_io": [image_io("CPU_MASK_READ", "read", "512x288", "Y"), image_io("CPU_IMAGE_READ", "read", out), image_io("CPU_IMAGE_WRITE", "write", out)]}
        if out != v["size_overrides"]["preview_out"]:
            cfg["portrait_blend"]["memory_io"].append(image_io("CPU_PREVIEW_WRITE", "write", v["size_overrides"]["preview_out"]))
        cfg["mcsc"]["active_output_ports"] = ["MCSC_WDMA_W0"]
        v["design_conditions"]["mcsc_dma_channels"] = 1
        cfg["mcsc"]["memory_io"] = [image_io("MCSC_WDMA_W0", "write", out)]
        cfg["dpu"]["memory_io"] = [image_io("DPU_RDMA", "read", v["size_overrides"]["preview_out"])]
        writer(v, "mfc_enc", 80 if resolution == "uhd" else 30)
        cfg["mfc_enc"]["memory_io"].append(image_io("MFC_RDMA", "read", out))
        variants[v["id"]] = v
    raw["variants"] = list(variants.values())
    write(path, raw)
    # APV inherits the corrected single-camera processing path, not MFC hardware.
    path = ROOT / "02_definition/uc-camera-recording-apv.yaml"
    apv = read(path)
    old_variants = deepcopy(apv["variants"])
    apv["pipeline"] = remap(deepcopy(raw["pipeline"]), {"mfc_enc": "apv_enc", "ip-mfc-s5e9965": "ip-apv-s5e9965", "MFC_RDMA": "APV_RDMA_FRAME"})
    apv["pipeline"]["buffers"] = {k: b for k,b in apv["pipeline"]["buffers"].items() if not k.startswith("FRONT_")}
    apv["size_profile"] = deepcopy(raw["size_profile"])
    apv["variants"] = []
    for old in old_variants:
        dc = old.get("design_conditions", {})
        res, fps = dc.get("resolution", "UHD").lower(), dc.get("fps", 30)
        parent = f"cam-rec-r1-{res}{fps}-sdr"
        v = remap(deepcopy(variants[parent]), {"mfc_enc": "apv_enc", "MFC_RDMA": "APV_RDMA_FRAME"})
        v["id"] = old["id"]
        v["design_conditions"].update(dc)
        v["design_conditions"].update(priority_recording=True, encoder_hw="APV", sensor_runtime_confirmation=True)
        cfg = v["node_configs"]["apv_enc"]
        cfg.update({k: value for k,value in old.get("node_configs", {}).get("apv_enc", {}).items() if k != "sim"})
        cfg["sim"].update(format="YUV444" if dc.get("apv_chroma_format_idc")==2 else "YUV422")
        fmt = cfg["sim"]["format"]
        for key in ["MCSC_VIDEO", "GDC_VIDEO"]:
            v.setdefault("buffer_overrides", {}).setdefault(key, {}).update(format=fmt, bitdepth=10)
        rate = (3000 if res == "8k" else 1000 * fps / 30) * (1.5 if fmt=="YUV444" else 1) * (1.25 if dc.get("apv_band_idc")==1 else 1)
        writer(v, "apv_enc", rate)
        apv["variants"].append(v)
    write(path, apv)
    # Logical DMA names explicitly remain unverified physical port mappings.
    for filename, ports in {"ip-apv-s5e9965": ["APV_RDMA_FRAME", "APV_WDMA_BITSTREAM"], "ip-mfc-s5e9965": ["MFC_WDMA_BITSTREAM"], "ip-cpu-s5e9965": ["CPU_BITSTREAM_READ", "CPU_BITSTREAM_WRITE", "STORAGE_BITSTREAM_READ", "CPU_IMAGE_READ", "CPU_FRONT_READ", "CPU_IMAGE_WRITE", "CPU_MASK_READ", "CPU_PREVIEW_WRITE"]}.items():
        path = ROOT / "00_hw" / (filename + ".yaml")
        ip = read(path)
        props = ip["capabilities"].setdefault("properties", {})
        modules = props.setdefault("modules", [])
        for port in ports:
            if not any(m["name"]==port for m in modules):
                modules.append({"name": port, "type": "DMA", "direction": "read" if "READ" in port or "RDMA" in port else "write", "naming": "logical traffic endpoint; physical mapping unverified"})
        if filename == "ip-apv-s5e9965":
            ip["capabilities"]["sim"] = {"hw_name": "APV", "ppc": 2, "vdd": "VDD_CODEC", "dvfs_group": "APV", "source": "assumed_capacity", "source_note": NOTE + " Core power unavailable; excluded."}
        write(path, ip)
    sync_import_bundle()


if __name__ == "__main__":
    main()
