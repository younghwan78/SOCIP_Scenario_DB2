"""Legacy YAML import adapters.

The legacy importer converts simulation-oriented YAML into canonical
ScenarioDB YAML. It intentionally emits files first instead of writing DB rows
directly so engineers can review generated artifacts before ETL.
"""

