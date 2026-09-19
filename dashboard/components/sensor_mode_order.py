"""Recording-oriented ordering without changing the selected mode IDs."""
import re

PRIORITY_FPS = (30, 60, 120, 240)


def recording_key(size, fps, label):
    width, height = size if isinstance(size, (list, tuple)) and len(size) == 2 else (0, 0)
    wide = bool(width and height and abs(width / height / (16 / 9) - 1) <= 0.01)
    rate = float(fps or 0)
    rank = next((i for i, target in enumerate(PRIORITY_FPS) if abs(rate / target - 1) <= 0.01), 4)
    index = re.search(r"mode(\d+)", label)
    return (0 if wide else 1, rank, rate if rank == 4 else 0,
            -(width * height), int(index[1]) if index else 0, label)


def ordered_dt_modes(modes):
    def key(label):
        mode = modes[label]
        fps = mode.get("decoded", {}).get("fps")
        cap = mode.get("option", {}).get("max_fps")
        if fps and isinstance(cap, (int, float)) and cap > 0:
            fps = min(fps, cap)
        return recording_key(mode.get("decoded", {}).get("size"), fps, label)
    return sorted(modes, key=key)


def ordered_cis_modes(profile):
    summaries = profile.get("mode_summaries", {})
    return sorted(profile["modes"], key=lambda label: recording_key(
        summaries.get(label, {}).get("size"), summaries.get(label, {}).get("fps"), label))
