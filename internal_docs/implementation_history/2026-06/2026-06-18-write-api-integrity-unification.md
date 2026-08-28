# Write API Integrity Unification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Share one variant overlay integrity engine across ETL, import-health, and Write API validation while keeping each surface's *observable* behavior (codes, paths, and reject/accept decisions) intact — except where a behavior change is consciously adopted and pinned by a test.

**Architecture:** Move `node_configs`, `selected_mode`, and `buffer_overrides` reference checks into a neutral core that accepts row-backed and dict-backed inputs. Keep thin adapters at each surface so ETL/import-health emit `IntegrityIssue`, while Write API keeps its existing `ValidationIssue` code taxonomy and path format.

**Tech Stack:** Python 3.11, SQLAlchemy ORM rows, FastAPI Write API service functions, pytest, ruff.

---

## Review-driven amendments (B1–B4)

The first draft of this plan would have *silently* changed observable behavior because the duplicated checks differ in semantics per surface. The engine and adapters below were amended to make every difference explicit and test-pinned:

- **B1 — selected_mode strictness is a per-surface policy, not a global default.** The core exposes `strict_undeclared_modes`. Interactive Write **staging** stays **strict** (a `selected_mode` on an IP that declares no `operating_modes` is rejected — historic Write behavior). Bulk paths (**ETL / import-health / import-bundle**) stay **lenient** (undeclared modes ⇒ cannot validate ⇒ skip). Both directions are pinned by tests in `tests/unit/test_integrity_checks.py` and the surface tests.
- **B2 — `compression_in_placement` is preserved.** It lived inside the old `_validate_buffer_overrides` (not in `_validate_pipeline_compression`) and gates the downstream compression check. It is split into a Write-only local helper `_validate_buffer_override_placement(...)` that runs alongside the shared engine.
- **B3 — import-bundle is a *conscious hardening*, not a pure refactor.** It keeps `import_variant_node_config_not_found` / `import_variant_buffer_override_not_found`, switches their `path` to node-granular (e.g. `…node_configs.<id>`), and adds three explicit new codes (`import_variant_node_config_invalid`, `import_variant_selected_mode_without_ip`, `import_variant_selected_mode_unsupported`). Each new behavior has a test.
- **B4 — pipeline-patch impact stays a pure refactor.** It calls the engine with `check_selected_mode=False` and maps only the two existence codes back to the historic impact strings; the public code `variant_overlay_impact` and its messages are unchanged. No catch-all, so previously-valid patches gain no new blocking errors.

**Policy summary**

| Surface | selected_mode policy | New rejections vs. before | Path change |
|---|---|---|---|
| ETL / import-health | lenient | none (byte-identical) | none |
| Write staging | **strict** (`strict_undeclared_modes=True`) | none | none (prefix stripped) |
| import-bundle | lenient | **yes** (shape + selected_mode) | coarse → node-granular |
| pipeline-patch impact | n/a (`check_selected_mode=False`) | none | none |

---

## Scope

In scope:
- Share variant overlay reference checks for:
  - `node_configs` target exists.
  - `node_configs.*` value is an object.
  - `node_configs.*.selected_mode` targets an IP-backed base node.
  - `node_configs.*.selected_mode` exists in the target IP `capabilities.operating_modes` when modes are declared.
  - `buffer_overrides` target exists.
- Preserve Write API public error codes:
  - staging overlay: `unknown_node_config`, `node_config_invalid`, `selected_mode_without_ip`, `unsupported_selected_mode`, `unknown_buffer_override`.
  - import bundle: `import_variant_node_config_not_found`, `import_variant_buffer_override_not_found`; add import-specific selected-mode codes only after tests define them.
  - pipeline patch impact: keep public code `variant_overlay_impact`.
- Keep Write API-specific compression placement validation in `write/service.py`.

Out of scope for this pass:
- Routing switch and topology patch edge validation unification.
- Changing API response schemas.
- Changing DB schema or migrations.
- Changing existing Write API code names unless a test explicitly requires it.

## Current Files

- Modify: `src/scenario_db/integrity_checks.py`
  - Add dict-friendly core input types and conversion helpers.
  - Keep existing ETL/import-health public functions working.
- Modify: `src/scenario_db/etl/validate_loaded.py`
  - Should continue using `validate_variant_overlay_integrity(...)` without behavior changes.
- Modify: `src/scenario_db/api/routers/explorer.py`
  - Should continue using `validate_variant_overlay_integrity(...)` without response shape changes.
- Modify: `src/scenario_db/write/service.py`
  - Replace duplicated `node_configs` / `buffer_overrides` checks with adapters around shared core.
  - Keep `_validate_pipeline_compression`, routing switch checks, topology patch checks, and candidate pipeline checks local.
- Add: `tests/unit/test_integrity_checks.py`
  - Pure unit tests for dict-backed core behavior.
- Modify: `tests/unit/test_write_service.py`
  - Regression tests for staging, import-bundle, and pipeline-patch code preservation.
- Modify: `tests/integration/test_write_api.py`
  - API-level checks only if unit coverage exposes a contract gap.

## Shared Core Design

Add neutral dataclasses in `src/scenario_db/integrity_checks.py`:

```python
@dataclass(slots=True)
class VariantOverlayTarget:
    scenario_id: str
    variant_id: str
    base_pipeline: dict[str, Any]
    node_configs: dict[str, Any]
    buffer_overrides: dict[str, Any]
    topology_patch: dict[str, Any]
    path_prefix: str
    document_kind: str = "scenario.usecase"
    document_id: str | None = None


@dataclass(slots=True)
class IpModeCatalog:
    modes_by_ip_ref: dict[str, set[str]] = field(default_factory=dict)

    def modes_for(self, ip_ref: str | None) -> set[str]:
        if not ip_ref:
            return set()
        return self.modes_by_ip_ref.get(str(ip_ref), set())
```

Add core function (note the two policy knobs from B1/B4):

```python
def validate_variant_overlay_targets(
    targets: list[VariantOverlayTarget],
    ip_modes: IpModeCatalog,
    *,
    check_selected_mode: bool = True,   # B4: pipeline-patch impact sets False
    strict_undeclared_modes: bool = False,  # B1: Write staging sets True
) -> list[IntegrityIssue]:
    ...
```

selected_mode rule that encodes both policies:

```python
modes = ip_modes.modes_for(ip_ref)
if (strict_undeclared_modes or modes) and str(selected_mode) not in modes:
    ...  # unsupported_selected_mode
```

Keep compatibility wrapper:

```python
def validate_variant_overlay_integrity(
    scenarios: list[Scenario],
    variants: list[ScenarioVariant],
    ips: list[IpCatalog],
) -> list[IntegrityIssue]:
    targets = variant_overlay_targets_from_rows(scenarios, variants)
    return validate_variant_overlay_targets(targets, ip_mode_catalog_from_rows(ips))
```

This makes the common logic usable by:
- ETL/import-health rows.
- Write API staged payload dict.
- import-bundle scenario documents.
- pipeline-patch candidate pipeline plus existing variants.

---

### Task 1: Add Pure Core Tests

**Files:**
- Create: `tests/unit/test_integrity_checks.py`
- Modify: `src/scenario_db/integrity_checks.py`

- [ ] **Step 1: Write failing tests for dict-backed targets**

Create `tests/unit/test_integrity_checks.py`:

```python
from __future__ import annotations

from scenario_db.integrity_checks import (
    IpModeCatalog,
    VariantOverlayTarget,
    validate_variant_overlay_targets,
)


def _target(**overrides):
    payload = {
        "scenario_id": "uc-camera-u",
        "variant_id": "v1",
        "base_pipeline": {
            "nodes": [{"id": "isp", "ip_ref": "ip-isp-v1"}],
            "edges": [],
            "buffers": {"REC": {"format": "YUV420"}},
        },
        "node_configs": {},
        "buffer_overrides": {},
        "topology_patch": {},
        "path_prefix": "payload.variant",
    }
    payload.update(overrides)
    return VariantOverlayTarget(**payload)


def test_variant_overlay_target_reports_missing_node_config_target():
    issues = validate_variant_overlay_targets(
        [_target(node_configs={"missing": {}})],
        IpModeCatalog({"ip-isp-v1": {"normal"}}),
    )

    assert [issue.code for issue in issues] == ["unknown_node_config"]
    assert issues[0].path == "payload.variant.node_configs.missing"


def test_variant_overlay_target_reports_unsupported_selected_mode():
    issues = validate_variant_overlay_targets(
        [_target(node_configs={"isp": {"selected_mode": "turbo"}})],
        IpModeCatalog({"ip-isp-v1": {"normal"}}),
    )

    assert [issue.code for issue in issues] == ["unsupported_selected_mode"]
    assert "turbo" in issues[0].message


def test_variant_overlay_target_allows_selected_mode_when_ip_modes_are_not_declared():
    issues = validate_variant_overlay_targets(
        [_target(node_configs={"isp": {"selected_mode": "turbo"}})],
        IpModeCatalog({}),
    )

    assert issues == []


def test_variant_overlay_target_reports_missing_buffer_override_target():
    issues = validate_variant_overlay_targets(
        [_target(buffer_overrides={"MISSING": {"format": "P010"}})],
        IpModeCatalog({"ip-isp-v1": {"normal"}}),
    )

    assert [issue.code for issue in issues] == ["unknown_buffer_override"]
    assert issues[0].path == "payload.variant.buffer_overrides.MISSING"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
uv run pytest tests/unit/test_integrity_checks.py -q
```

Expected:

```text
ImportError or AttributeError for VariantOverlayTarget / validate_variant_overlay_targets
```

- [ ] **Step 3: Implement the neutral core**

In `src/scenario_db/integrity_checks.py`, add the dataclasses and move the body of current `validate_variant_overlay_integrity(...)` into `validate_variant_overlay_targets(...)`.

Path construction rule:

```python
node_path = f"{target.path_prefix}.node_configs.{node_id_text}"
buffer_path = f"{target.path_prefix}.buffer_overrides.{buffer_id_text}"
```

Known nodes rule:

```python
base_nodes = {
    str(node.get("id")): node
    for node in (target.base_pipeline.get("nodes") or [])
    if isinstance(node, dict) and node.get("id")
}
injected_nodes = {
    str(node.get("id"))
    for node in (target.topology_patch.get("add_nodes") or [])
    if isinstance(node, dict) and node.get("id")
}
known_nodes = set(base_nodes) | injected_nodes
```

- [ ] **Step 4: Run core tests**

Run:

```powershell
uv run pytest tests/unit/test_integrity_checks.py -q
```

Expected:

```text
4 passed
```

- [ ] **Step 5: Run existing ETL/import-health tests**

Run:

```powershell
uv run pytest tests/unit/test_etl_validate_loaded.py tests/unit/api/test_explorer_summary_health.py -q
```

Expected:

```text
all tests passed
```

- [ ] **Step 6: Commit**

```powershell
git add src/scenario_db/integrity_checks.py tests/unit/test_integrity_checks.py
git commit -m "refactor: generalize variant overlay integrity checks"
```

---

### Task 2: Wire Write API Staging Overlay Validation

**Files:**
- Modify: `src/scenario_db/write/service.py`
- Modify: `tests/unit/test_write_service.py`

- [ ] **Step 1: Add failing tests that preserve staging codes**

Add or extend tests in `tests/unit/test_write_service.py`:

```python
def test_validate_variant_overlay_rejects_unknown_node_config_via_shared_integrity():
    db = _Db()
    normalized = normalize_payload(_payload(node_configs={"missing": {}}))

    issues = validate_variant_overlay(db, normalized)

    assert any(issue.code == "unknown_node_config" for issue in issues)
    assert any(issue.path == "node_configs.missing" for issue in issues)


def test_validate_variant_overlay_rejects_unknown_buffer_override_via_shared_integrity():
    db = _Db()
    normalized = normalize_payload(
        _payload(node_configs={}, buffer_overrides={"MISSING": {"format": "P010"}})
    )

    issues = validate_variant_overlay(db, normalized)

    assert any(issue.code == "unknown_buffer_override" for issue in issues)
    assert any(issue.path == "buffer_overrides.MISSING" for issue in issues)
```

- [ ] **Step 2: Run tests to verify current behavior**

Run:

```powershell
uv run pytest tests/unit/test_write_service.py::test_validate_variant_overlay_rejects_unknown_node_config_via_shared_integrity tests/unit/test_write_service.py::test_validate_variant_overlay_rejects_unknown_buffer_override_via_shared_integrity -q
```

Expected:

```text
Tests may pass already because duplicated local logic exists.
```

If they pass, continue. The goal is now refactor-safety rather than new behavior.

- [ ] **Step 3: Add Write API adapter for IntegrityIssue**

In `src/scenario_db/write/service.py`, import:

```python
from scenario_db.integrity_checks import (
    IpModeCatalog,
    IntegrityIssue,
    VariantOverlayTarget,
    validate_variant_overlay_targets,
)
```

Add helper:

```python
def _write_issue_from_integrity(issue: IntegrityIssue, *, path_prefix: str = "") -> ValidationIssue:
    path = issue.path
    if path_prefix and path.startswith(path_prefix + "."):
        path = path[len(path_prefix) + 1:]
    return _issue(issue.severity, issue.code, issue.message, path)
```

Add helper:

```python
def _ip_mode_catalog_from_db(db: Session, base_nodes: dict[str, dict[str, Any]]) -> IpModeCatalog:
    ip_refs = {
        str(node.get("ip_ref"))
        for node in base_nodes.values()
        if isinstance(node, dict) and node.get("ip_ref")
    }
    modes_by_ip_ref: dict[str, set[str]] = {}
    for ip_ref in ip_refs:
        modes_by_ip_ref[ip_ref] = _operating_mode_ids(db, ip_ref)
    return IpModeCatalog(modes_by_ip_ref)
```

- [ ] **Step 4: Replace staging `node_configs` / `buffer_overrides` calls**

In `validate_variant_overlay(...)`, replace:

```python
known_config_nodes = base_node_ids | injected_nodes
issues.extend(_validate_node_configs(db, variant.get("node_configs") or {}, base_nodes, known_config_nodes))
issues.extend(_validate_buffer_overrides(variant.get("buffer_overrides") or {}, buffer_ids))
```

with:

```python
target = VariantOverlayTarget(
    scenario_id=scenario_ref,
    variant_id=str(variant.get("id") or "staged"),
    base_pipeline=scenario.pipeline or {},
    node_configs=variant.get("node_configs") or {},
    buffer_overrides=variant.get("buffer_overrides") or {},
    topology_patch=variant.get("topology_patch") or {},
    path_prefix="payload.variant",
)
integrity_issues = validate_variant_overlay_targets(
    [target],
    _ip_mode_catalog_from_db(db, base_nodes),
)
issues.extend(
    _write_issue_from_integrity(issue, path_prefix="payload.variant")
    for issue in integrity_issues
)
```

Leave `_validate_pipeline_compression(...)` unchanged.

- [ ] **Step 5: Run staging tests**

Run:

```powershell
uv run pytest tests/unit/test_write_service.py::test_validate_variant_overlay_rejects_unsupported_selected_mode tests/unit/test_write_service.py::test_validate_variant_overlay_rejects_unknown_node_config_via_shared_integrity tests/unit/test_write_service.py::test_validate_variant_overlay_rejects_unknown_buffer_override_via_shared_integrity -q
```

Expected:

```text
3 passed
```

- [ ] **Step 6: Remove dead local helpers only if unused**

After staging/import-bundle/pipeline-patch tasks are complete, run:

```powershell
rg "_validate_node_configs|_validate_buffer_overrides" src/scenario_db/write/service.py
```

Do not delete them in this task if import-bundle or pipeline-patch still uses them.

- [ ] **Step 7: Commit**

```powershell
git add src/scenario_db/write/service.py tests/unit/test_write_service.py
git commit -m "refactor: reuse integrity checks for write staging"
```

---

### Task 3: Wire Import-Bundle Variant Validation

**Files:**
- Modify: `src/scenario_db/write/service.py`
- Modify: `tests/unit/test_write_service.py`

- [ ] **Step 1: Add failing test for import-bundle selected-mode validation**

Add to `tests/unit/test_write_service.py`:

```python
def test_validate_import_bundle_rejects_unsupported_selected_mode():
    doc = _import_usecase_doc()
    doc["pipeline"]["nodes"] = [{"id": "mfc", "ip_ref": "ip-mfc-v1"}]
    doc["pipeline"]["buffers"] = {"RECORD_BUF": {"format": "YUV420"}}
    doc["variants"][0]["node_configs"] = {"mfc": {"selected_mode": "turbo"}}
    ip_doc = {
        "kind": "ip",
        "schema_version": "2.2",
        "id": "ip-mfc-v1",
        "category": "MFC",
        "hierarchy": {},
        "capabilities": {"operating_modes": [{"id": "normal"}]},
    }
    normalized = normalize_import_bundle_payload({"documents": [ip_doc, doc]})

    issues = validate_import_bundle(_Db(), normalized)

    assert any(issue.code == "import_variant_selected_mode_unsupported" for issue in issues)
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
uv run pytest tests/unit/test_write_service.py::test_validate_import_bundle_rejects_unsupported_selected_mode -q
```

Expected:

```text
FAIL because selected_mode is not checked in import-bundle variant validation.
```

- [ ] **Step 3: Build import-bundle IP mode catalog**

In `src/scenario_db/write/service.py`, add:

```python
def _ip_mode_catalog_for_import_bundle(db: Session, docs: list[dict[str, Any]]) -> IpModeCatalog:
    modes_by_ip_ref: dict[str, set[str]] = {}
    for doc in docs:
        if doc.get("kind") == "ip" and doc.get("id"):
            modes_by_ip_ref[str(doc["id"])] = _operating_modes_from_capabilities(
                doc.get("capabilities") or {}
            )
    for ip_ref in _existing_ip_refs_needed_by_import_docs(docs) - set(modes_by_ip_ref):
        modes_by_ip_ref[ip_ref] = _operating_mode_ids(db, ip_ref)
    return IpModeCatalog(modes_by_ip_ref)
```

Add:

```python
def _operating_modes_from_capabilities(capabilities: dict[str, Any]) -> set[str]:
    modes = capabilities.get("operating_modes") if isinstance(capabilities, dict) else None
    if isinstance(modes, dict):
        return {str(key) for key in modes}
    return {
        str(mode["id"])
        for mode in modes or []
        if isinstance(mode, dict) and mode.get("id")
    }
```

- [ ] **Step 4: Use shared core inside `_validate_import_usecase_doc_refs`**

Inside the per-variant loop at `src/scenario_db/write/service.py`, replace direct node/buffer loops with:

```python
target = VariantOverlayTarget(
    scenario_id=str(doc.get("id")),
    variant_id=str(variant.get("id") or variant_idx),
    base_pipeline=pipeline,
    node_configs=variant.get("node_configs") or {},
    buffer_overrides=variant.get("buffer_overrides") or {},
    topology_patch=variant.get("topology_patch") or {},
    path_prefix=variant_path,
)
integrity_issues = validate_variant_overlay_targets([target], ip_mode_catalog)
issues.extend(_import_issue_from_integrity(issue) for issue in integrity_issues)
```

Add mapping:

```python
IMPORT_INTEGRITY_CODE_MAP = {
    "unknown_node_config": "import_variant_node_config_not_found",
    "unknown_buffer_override": "import_variant_buffer_override_not_found",
    "node_config_invalid": "import_variant_node_config_invalid",
    "selected_mode_without_ip": "import_variant_selected_mode_without_ip",
    "unsupported_selected_mode": "import_variant_selected_mode_unsupported",
}


def _import_issue_from_integrity(issue: IntegrityIssue) -> ValidationIssue:
    return _issue(
        issue.severity,
        IMPORT_INTEGRITY_CODE_MAP.get(issue.code, f"import_{issue.code}"),
        issue.message,
        issue.path,
    )
```

- [ ] **Step 5: Run import-bundle tests**

Run:

```powershell
uv run pytest tests/unit/test_write_service.py::test_validate_import_bundle_rejects_missing_import_ip_ref tests/unit/test_write_service.py::test_validate_import_bundle_rejects_missing_edge_buffer tests/unit/test_write_service.py::test_validate_import_bundle_rejects_unsupported_selected_mode -q
```

Expected:

```text
3 passed
```

- [ ] **Step 6: Commit**

```powershell
git add src/scenario_db/write/service.py tests/unit/test_write_service.py
git commit -m "refactor: reuse integrity checks for import bundles"
```

---

### Task 4: Wire Pipeline-Patch Variant Impact

**Files:**
- Modify: `src/scenario_db/write/service.py`
- Modify: `tests/unit/test_write_service.py`

- [ ] **Step 1: Add regression test preserving public code**

Add to `tests/unit/test_write_service.py`:

```python
def test_validate_pipeline_patch_reports_buffer_override_impact_via_shared_integrity():
    db = _Db()
    db.variant.buffer_overrides = {"RECORD_BUF": {"format": "YUV420"}}
    normalized = normalize_pipeline_patch_payload(
        _pipeline_patch_payload({"remove_buffers": ["RECORD_BUF"]})
    )

    issues = validate_pipeline_patch(db, normalized)

    assert any(issue.code == "variant_overlay_impact" for issue in issues)
    assert any("buffer_overrides" in issue.message for issue in issues)
```

- [ ] **Step 2: Run test to capture current behavior**

Run:

```powershell
uv run pytest tests/unit/test_write_service.py::test_validate_pipeline_patch_reports_buffer_override_impact_via_shared_integrity -q
```

Expected:

```text
PASS or FAIL depending on existing remove_buffers fixture support.
```

If it fails because `remove_buffers` is not supported by the helper, use the existing node removal test and assert message content there instead.

- [ ] **Step 3: Replace node_configs / buffer_overrides impact checks**

In `_pipeline_patch_impact(...)`, keep current routing switch and topology patch edge checks local. Replace only:

```python
for node_id in (variant.node_configs or {}):
    if node_id not in known_variant_nodes:
        errors.append(f"node_configs references removed node '{node_id}'")
for buffer_id in (variant.buffer_overrides or {}):
    if buffer_id not in buffer_ids:
        errors.append(f"buffer_overrides references removed buffer '{buffer_id}'")
```

with:

```python
target = VariantOverlayTarget(
    scenario_id=scenario_ref,
    variant_id=str(variant.id),
    base_pipeline=candidate,
    node_configs=variant.node_configs or {},
    buffer_overrides=variant.buffer_overrides or {},
    topology_patch=variant.topology_patch or {},
    path_prefix=f"variants.{variant.id}",
)
for issue in validate_variant_overlay_targets([target], _ip_mode_catalog_from_candidate(db, candidate)):
    if issue.code == "unknown_node_config":
        node_id = issue.path.rsplit(".", 1)[-1]
        errors.append(f"node_configs references removed node '{node_id}'")
    elif issue.code == "unknown_buffer_override":
        buffer_id = issue.path.rsplit(".", 1)[-1]
        errors.append(f"buffer_overrides references removed buffer '{buffer_id}'")
    elif issue.severity == "error":
        errors.append(issue.message)
```

Do not route routing-switch or topology-patch add-edge impact through the shared core in this task.

- [ ] **Step 4: Run pipeline-patch tests**

Run:

```powershell
uv run pytest tests/unit/test_write_service.py::test_validate_pipeline_patch_rejects_variant_overlay_breakage tests/unit/test_write_service.py::test_validate_pipeline_patch_reports_buffer_override_impact_via_shared_integrity -q
```

Expected:

```text
2 passed
```

- [ ] **Step 5: Commit**

```powershell
git add src/scenario_db/write/service.py tests/unit/test_write_service.py
git commit -m "refactor: reuse integrity checks for pipeline patch impact"
```

---

### Task 5: Remove Dead Duplicates and Run Full Verification

**Files:**
- Modify: `src/scenario_db/write/service.py`
- Possibly modify: `tests/unit/test_write_service.py`

- [ ] **Step 1: Find duplicate helpers**

Run:

```powershell
rg "_validate_node_configs|_validate_buffer_overrides|import_variant_node_config_not_found|import_variant_buffer_override_not_found" src/scenario_db/write/service.py tests
```

Expected:

```text
Only mappings/tests should remain for import_variant_* codes.
_validate_node_configs and _validate_buffer_overrides should be unused.
```

- [ ] **Step 2: Delete unused helpers**

Delete `_validate_node_configs(...)` and `_validate_buffer_overrides(...)` only if `rg` confirms no call sites remain.

Keep `_validate_pipeline_compression(...)` and `_operating_mode_ids(...)` if still used by mode catalog or compression checks.

- [ ] **Step 3: Run focused Write API tests**

Run:

```powershell
uv run pytest tests/unit/test_write_service.py tests/integration/test_write_api.py -q
```

Expected:

```text
all tests passed
```

- [ ] **Step 4: Run full verification**

Run:

```powershell
uv run pytest tests/unit -q
uv run pytest tests/integration -q
uv run ruff check src tests/unit scripts
git diff --check
```

Expected:

```text
unit tests passed
integration tests passed
All checks passed!
git diff --check has no output
```

- [ ] **Step 5: Commit cleanup**

```powershell
git add src/scenario_db/write/service.py tests/unit/test_write_service.py
git commit -m "refactor: remove duplicate write integrity checks"
```

---

## Acceptance Checklist

- [x] ETL `validate_loaded_db` still reports the same semantic errors for row-backed loaded data (compat wrapper preserves codes, paths, `document_id`, and messages).
- [x] `/api/v1/explorer/import-health` still reports the same `ImportHealthIssue` shape.
- [x] Write API staging keeps existing public error codes **and** paths, **and** the same reject/accept decisions (B1 strict policy + B2 placement check pinned).
- [x] Import-bundle keeps existing public node/buffer error codes; the new selected-mode/shape codes and the node-granular path are pinned by tests (B3, intentional hardening).
- [x] Pipeline-patch impact keeps public code `variant_overlay_impact` and its messages; no new blocking errors (B4).
- [x] `write/service.py` no longer owns separate node_config/buffer_override integrity loops for the shared cases (`_validate_node_configs` / `_validate_buffer_overrides` removed).
- [x] **Same input → same code + path + reject/accept** for unchanged surfaces (added per review; codes alone are insufficient).
- [x] Full unit, integration, ruff, and diff checks pass.

## Execution Status (2026-06-18)

Implemented in worktree `worktree-write-api-integrity` (`.claude/worktrees/write-api-integrity`), branched from `main@5d1b218`.

| Commit | Task |
|---|---|
| `61f92fb` | T1 generalize variant overlay integrity engine (+ `tests/unit/test_integrity_checks.py`) |
| `c796e13` | T2 route write staging through engine (B1 strict, B2 placement split) |
| `6fa6541` | T3 route import-bundle through engine (B3 hardening + node-granular path) |
| `8c69b1e` | T4 route pipeline-patch impact through engine (B4 existence-only) |

Dead duplicates (`_validate_node_configs`, `_validate_buffer_overrides`) were removed in T2 (their only caller), so the planned T5 cleanup commit was unnecessary.

Verification (worktree venv, `--group dev --group dashboard --group sim`):

```text
1111 passed in 11.91s        # tests/unit + tests/integration
All checks passed!           # ruff check src tests/unit scripts
git diff --check             # clean
```

Note: a fresh worktree venv needs `--group sim` (networkx/simpy); without it
`tests/unit/sim/test_timeline_dependencies.py` reports an env-only failure
(unrelated to this change).

## Rollback Plan

If any Write API response contract changes unexpectedly:

1. Revert only the latest task commit.
2. Keep earlier core generalization if ETL/import-health still pass.
3. Add a failing test for the exact response code/path that changed.
4. Re-apply the adapter mapping for that surface before continuing.
