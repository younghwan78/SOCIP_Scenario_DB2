from dashboard.components.sensor_mode_order import ordered_dt_modes, ordered_cis_modes


def test_recording_order_uses_aspect_rate_and_cap_without_changing_ids():
    def mode(size, fps, cap=None):
        return {"decoded": {"size": size, "fps": fps}, "option": {"max_fps": cap}}
    modes = {
        "mode1": mode([4000, 3000], 30),
        "mode2": mode([4080, 2296], 240),
        "mode3": mode([3840, 2160], 120),
        "mode4": mode([1920, 1080], 60),
        "mode5": mode([1920, 1080], 30),
        "mode6_nfi": mode([3840, 2160], 120, 30),
        "mode7": mode([1920, 1080], 480),
    }
    assert ordered_dt_modes(modes) == ["mode6_nfi", "mode5", "mode4", "mode3", "mode2", "mode7", "mode1"]


def test_cis_order_handles_fractional_setfile_rates_and_near_16_9():
    profile = {"modes": ["wide60", "photo30", "wide30", "near120"], "mode_summaries": {
        "wide60": {"size": [4000, 2252], "fps": 59.94},
        "photo30": {"size": [4000, 3000], "fps": 30},
        "wide30": {"size": [3840, 2160], "fps": 30.03},
        "near120": {"size": [1984, 1120], "fps": 120},
    }}
    assert ordered_cis_modes(profile) == ["wide30", "wide60", "near120", "photo30"]
