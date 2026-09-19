"""Build reviewed basic GNG DT/CIS bindings from a read-only kernel tree.

Usage: python scripts/bind_gng_cis_timing.py --source-root <12_SM_S947B>
Extended/seamless modes intentionally remain unmapped.
"""
import argparse
import hashlib
from pathlib import Path
import re
import yaml
from scenario_db.sim.sensor_timing_binding import timing_mode_hash


def bind(source_root, fixtures):
    camera = source_root / "exynos/external-modules/camera/camera"
    header = camera / "sensor/module_framework/cis/is-cis-gng-setA-19p2.h"
    text = header.read_text(encoding="utf-8")
    table = re.search(r"sensor_gng_mode_infos_A_19p2\[\] = \{(.*?)\};", text, re.S)
    if not table:
        raise ValueError("GNG setA mode table not found")
    symbols = re.findall(r"&sensor_gng_mode_info_A_19p2_(\w+)", table[1])
    profile_path = fixtures / "timing-s5kgng.yaml"
    profile = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    if len(symbols) != len(profile["modes"]):
        raise ValueError("CIS mode table differs from imported profile")
    evidence = {}
    for name, path, marker in [
        ("mode_table", header, "sensor_gng_mode_infos_A_19p2[]"),
        ("cis_driver", camera / "sensor/module_framework/cis/is-cis-gng.c", "mode_info = cis->sensor_info->mode_infos[mode];"),
        ("mode_dispatch", camera / "sensor/module_framework/is-device-sensor-peri.c", "cis_mode_change, cis->subdev, device->cfg->mode"),
        ("dt_parser", camera / "is-dt.c", '"common", idx_dt++, &cfg->mode'),
    ]:
        body = path.read_text(encoding="utf-8")
        if marker not in body:
            raise ValueError(f"Missing dispatch evidence: {name}")
        evidence[name] = {"path": path.relative_to(source_root).as_posix(),
                          "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                          "line": body[:body.index(marker)].count("\n") + 1}
    # Verify every imported timing entry against the actual indexed setfile struct.
    for symbol in symbols:
        struct = re.search(r"sensor_gng_mode_info_A_19p2_" + re.escape(symbol) + r" = \{(.*?)\};", text, re.S)[1]
        timing = profile["modes"]["cis_" + symbol]
        pclk = re.search(r"\.pclk = (\d+)ULL \* (\d+)", struct)
        if not pclk or int(pclk[1]) * int(pclk[2]) != timing["pixel_clock_hz"]:
            raise ValueError(f"Pixel clock mismatch: {symbol}")
        for key in ("line_length_pck", "frame_length_lines"):
            value = re.search(r"\." + key + r" = (0x[0-9a-fA-F]+|\d+)", struct)[1]
            if int(value, 0) != timing[key]:
                raise ValueError(f"Timing mismatch: {symbol}/{key}")
    count = 0
    for board in ("m1s", "m2s"):
        path = fixtures / board / "sensor-gng.yaml"
        original = path.read_text(encoding="utf-8")
        doc = yaml.safe_load(original)
        source = source_root / doc["provenance"]["source"]["path"]
        if hashlib.sha256(source.read_bytes()).hexdigest() != doc["provenance"]["source"]["sha256"]:
            raise ValueError(f"DT source changed: {board}")
        if doc["module_properties"]["mclk_freq"] != 19200:
            raise ValueError("SetA-19p2 requires 19.2 MHz MCLK")
        for label, mode in doc["modes"].items():
            # Full labels are deliberate: suffix variants do not inherit a base mapping.
            if not re.fullmatch(r"mode\d+", label) or mode["decoded"]["ex_mode"] != "EX_NONE":
                continue
            index = mode["decoded"]["mode_index"]
            target = "cis_" + symbols[index]
            timing = profile["modes"][target]
            if mode["decoded"]["size"] != [timing["active_width"], timing["active_height"]]:
                raise ValueError(f"Dimension mismatch: {board}/{label}")
            binding = {"profile_ref": profile["id"], "profile_revision": profile["revision"],
                       "mode_label": target, "mode_index": index,
                       "mode_sha256": timing_mode_hash(timing),
                       "source": {"basis": "DT cfg.mode -> CIS mode_infos[index]",
                                  "selection": "setA, 19.2 MHz, non-mirror basic mode; no runtime seamless transition",
                                  **evidence}}
            if mode.get("timing_binding"):
                if mode["timing_binding"] != binding:
                    raise ValueError(f"Existing binding needs review: {board}/{label}")
                count += 1
                continue
            block = yaml.safe_dump({"timing_binding": binding}, sort_keys=False)
            block = "".join("    " + line + "\n" for line in block.splitlines())
            original = original.replace(f"  {label}:\n", f"  {label}:\n" + block, 1)
            count += 1
        path.write_text(original, encoding="utf-8", newline="\n")
    print(f"Verified 47 CIS entries; bound {count} basic DT modes")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--fixtures", type=Path, default=Path("db_fixtures_Exynos2600_S26Plus/00_sensor"))
    args = parser.parse_args()
    bind(args.source_root, args.fixtures)
