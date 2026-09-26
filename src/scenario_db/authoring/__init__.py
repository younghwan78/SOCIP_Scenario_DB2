"""Layered authoring sources for ScenarioDB canonical YAML.

Authoring files (``authoring/``) are the human-edited SSOT. They are compiled
into canonical schema v2.2 YAML that the existing ETL loader consumes.

Layers:
    platform  -- HW / sensor / SW catalog docs, inheritable across SoCs
    project   -- board-level project doc + scenario set, inheritable
    scenario  -- base pipeline + compact (base+delta) variants
    sw_timing -- SW task timing table, overridable by measurements
    sizes     -- node size bindings to size anchors (+ optional derived anchors)
"""
