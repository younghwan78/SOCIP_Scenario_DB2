# CLAUDE.md

See `AGENTS.md` for the current project context and working rules.

Important constraints:

- Use `implementation/` as the repository root.
- Run Python through the project virtual environment.
- `.\.venv\Scripts\python.exe -m ...` is the most explicit form.
- `uv run ...` is acceptable from `implementation/`; use `--group dashboard` for Streamlit and `--group dev` for pytest.
- Do not modify the legacy reference projects.
- Do not commit local runtime artifacts such as `.venv`, `.env`, logs, screenshots, caches, or database volumes.
- FastAPI entry point: `scenario_db.api.app:app`.
- Viewer entry point: `dashboard\Home.py`.
