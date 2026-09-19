"""Import reviewed single-readout CIS timing tables; source tree stays read-only."""
import argparse
from collections import Counter
import hashlib
from pathlib import Path
import re
import yaml
from scenario_db.models.sensor import SensorTiming, SensorTimingProfile
from scenario_db.sim.sensor_timing_binding import timing_mode_hash

# Driver probe selections reviewed for the current source tree.
FAMILIES = {
    "hp2": ("S5KHP2", "B"), "jn3": ("S5KJN3", "A"), "3ld": ("S5K3LD", "A"),
    "imx564": ("IMX564", "A"), "imx564-ff": ("IMX564", "B"),
    "imx874": ("IMX874", "A"), "gn3": ("S5KGN3", "A"), "3lu": ("S5K3LU", "A"),
    "3k1": ("S5K3K1", "A"), "imx955": ("IMX955", "A"),
    "imx854": ("IMX854", "A"), "imx754": ("IMX754", "A"), "3j1": ("S5K3J1", "A"),
}


def number(expression):
    """Only literal integer multiplication, never execute source expressions."""
    value = 1
    for token in expression.strip().split("*"):
        token = re.sub(r"[uUlL]+$", "", token.strip())
        token = re.sub(r"\.0+$", "", token)
        if not re.fullmatch(r"(?:0x[0-9a-fA-F]+|[0-9]+)", token):
            raise ValueError(f"Unsupported numeric expression: {expression}")
        value *= int(token, 0)
    return value


def source_stamp(path, root, line=None):
    result = {"path": path.relative_to(root).as_posix(), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    if line is not None:
        result["line"] = line
    return result


def parse_table(path, root):
    text = path.read_text(encoding="utf-8")
    table = re.search(r"sensor_cis_mode_info \*(\w+)\[\] = \{(.*?)\};", text, re.S)
    if table is None:
        raise ValueError(f"No CIS table: {path.name}")
    body = re.sub(r"/\*.*?\*/|//[^\n]*", "", table[2], flags=re.S)
    if "#" in body or "[" in body:
        raise ValueError("Conditional/designated mode table requires explicit review")
    symbols = re.findall(r"&(\w+)", body)
    structs = {m[1]: (m[2], text[:m.start()].count("\n") + 1) for m in re.finditer(
        r"const struct sensor_cis_mode_info (\w+) = \{(.*?)\};", text, re.S)}
    rows = []
    for index, symbol in enumerate(symbols):
        block, line = structs[symbol]
        fields = dict(re.findall(r"\.(\w+)\s*=\s*([^,]+),", block))
        size = re.search(r"(\d+)[xX](\d+)", fields["setfile_index"])
        fps = re.search(r"_(\d+)[fF][pP][sS]", fields["setfile_index"])
        if not size:
            raise ValueError(f"Mode dimensions/fps require review: {symbol}")
        bits = re.search(r"RAW(\d+)", fields["bit_format"])
        if not bits:
            raise ValueError(f"Unknown bit format: {symbol}")
        label = "cis_" + re.sub(r"^sensor_.*?_mode_info_[ABC]_(?:19p2_)?", "", symbol).lower()
        data = {"active_width": int(size[1]), "active_height": int(size[2]),
                "pixel_clock_hz": number(fields["pclk"]),
                "line_length_pck": number(fields["line_length_pck"]),
                "frame_length_lines": number(fields["frame_length_lines"]),
                "source": {**source_stamp(path, root, line), "basis": "CIS indexed setfile",
                           "mode_index": index, **({"nominal_fps": int(fps[1])} if fps else {}),
                           "bits_per_pixel": int(bits[1]), "symbol": symbol,
                           "mode_name": fields.get("name", fields["setfile_index"]).strip('"')}}
        try:
            SensorTiming.model_validate(data)
            rows.append((label, data, None))
        except ValueError:
            rows.append((label, None, "setfile frame length is shorter than active height; readout sequence needs review"))
    return rows, table[1]


def run(root, fixtures):
    camera = root / "exynos/external-modules/camera/camera"
    cis = camera / "sensor/module_framework/cis"
    profiles, reports = {}, []
    for family, (sensor, revision) in FAMILIES.items():
        driver_name = family.removesuffix("-ff")
        header = cis / f"is-cis-{driver_name}-set{revision}-19p2.h"
        driver = cis / f"is-cis-{driver_name}.c"
        code = driver.read_text(encoding="utf-8")
        if "mode_infos[mode]" not in code or f"sensor_{driver_name}_info_{revision}_19p2" not in code:
            raise ValueError(f"Driver mode dispatch or probe selection changed: {family}")
        rows, table = parse_table(header, root)
        selection = f"set{revision}, 19.2 MHz, basic indexed mode; no runtime seamless switch"
        evidence = {"setfile": source_stamp(header, root), "driver": source_stamp(driver, root), "mode_table": table}
        if family == "imx564-ff":
            alternate = cis / "is-cis-imx564-setC-19p2.h"
            other, _ = parse_table(alternate, root)
            keys = ("active_width", "active_height", "pixel_clock_hz", "line_length_pck", "frame_length_lines")
            if len(other) != len(rows) or any(
                a[1] is None or b[1] is None or any(a[1][k] != b[1][k] for k in keys)
                or a[1]["source"]["bits_per_pixel"] != b[1]["source"]["bits_per_pixel"]
                for a, b in zip(rows, other)
            ):
                raise ValueError("FF setB/C timing equivalence must be reviewed")
            evidence["equivalent_setC"] = source_stamp(alternate, root)
            selection += "; FF setB/setC readout inputs verified identical by index"
        if family in ("gn3", "imx754"):
            selection += "; default setA selection, alternate setB is not selected"
        profile = {"id": f"sensortiming-{sensor.lower()}-set{revision.lower()}-19p2",
                   "schema_version": "2.2", "kind": "sensor.timing_profile", "sensor_name": sensor,
                   "revision": f"set{revision}-19p2-import-20260920",
                   "modes": {label: data for label, data, reason in rows if data},
                   "provenance": {"selection": selection, **evidence}}
        SensorTimingProfile.model_validate(profile)
        profiles[family] = (profile, rows, selection, evidence)
    # Validate and stage every change before writing any fixture.
    writes = {}
    for family, (profile, rows, selection, evidence) in profiles.items():
        writes[fixtures / f"timing-{family}.yaml"] = yaml.safe_dump(profile, sort_keys=False, allow_unicode=True)
        for path in sorted(fixtures.glob(f"*/sensor-{family}.yaml")):
            original = path.read_text(encoding="utf-8")
            doc = yaml.safe_load(original)
            src = root / doc["provenance"]["source"]["path"]
            if hashlib.sha256(src.read_bytes()).hexdigest() != doc["provenance"]["source"]["sha256"]:
                raise ValueError(f"DT source changed: {path}")
            if doc["module_properties"].get("mclk_freq") != 19200:
                raise ValueError(f"Unexpected MCLK: {path}")
            counts = Counter()
            for label, mode in doc["modes"].items():
                d = mode["decoded"]; index = d["mode_index"]
                reason = None
                if (not re.fullmatch(r"mode\d+", label) or d.get("ex_mode") != "EX_NONE"
                        or mode.get("option", {}).get("ex_mode_extra")):
                    reason = "Extended/suffix mode: runtime readout sequence needs review."
                elif index >= len(rows):
                    reason = "DT mode index is absent from the reviewed CIS table."
                else:
                    target, timing, reason = rows[index]
                    if timing:
                        images = [v for channels in mode.get("vc", {}).values() for v in channels.values() if v.get("data_class") == "image"]
                        if d["size"] != [timing["active_width"], timing["active_height"]]:
                            reason = "DT/indexed CIS dimensions differ; no resolution-only fallback."
                        elif len(images) != 1 or images[0].get("bits_per_pixel") != timing["source"]["bits_per_pixel"]:
                            reason = "DT image VC/bit depth differs from indexed CIS mode."
                if reason:
                    addition = {"timing_binding_note": reason}
                    counts[reason] += 1
                else:
                    addition = {"timing_binding": {"profile_ref": profile["id"], "profile_revision": profile["revision"],
                        "mode_label": target, "mode_index": index, "mode_sha256": timing_mode_hash(timing),
                        "source": {"basis": "DT cfg.mode -> CIS mode_infos[index]", "selection": selection, **evidence}}}
                    counts["bound"] += 1
                existing = {k: mode[k] for k in addition if k in mode}
                if existing:
                    if existing != addition:
                        raise ValueError(f"Existing binding differs: {path}/{label}")
                    continue
                block = "".join("    " + line + "\n" for line in yaml.safe_dump(addition, sort_keys=False).splitlines())
                original = original.replace(f"  {label}:\n", f"  {label}:\n" + block, 1)
            writes[path] = original
            reports.append({"catalog": doc["id"], "counts": dict(counts)})
    for path, content in writes.items():
        path.write_text(content, encoding="utf-8", newline="\n")
    print(yaml.safe_dump({"profiles": len(profiles), "catalogs": reports}, sort_keys=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--fixtures", type=Path, default=Path("db_fixtures_Exynos2600_S26Plus/00_sensor"))
    args = parser.parse_args()
    run(args.source_root, args.fixtures)
