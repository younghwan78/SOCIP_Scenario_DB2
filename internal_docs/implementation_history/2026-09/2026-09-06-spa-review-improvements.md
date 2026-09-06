# Scenario DB review improvements

Status: implementation summary prepared for PR, 2026-09-06.

## Resulting behavior

- Write mutations invalidate the imported document signature so reimporting the
  same YAML restores its actual content. Multi-document validation loads the IP
  identity catalog once per validation call.
- The timeline adapter separates HW node identity from display/catalog names and
  preserves explicit shared resources. OTF groups reserve resources across frames
  and ordinary tasks. Updated timing references are guarded by capacity tests.
- Buffer placement follows authored data, and simulation overlays reject
  substring/ambiguous matches. IP shorthand rules and mapped-column sorting work.
- Query and standard view projection load only the ten evidence columns needed
  by their consumers; full detail endpoints retain their existing behavior.
  Latest evidence selection preserves ordering semantics with a single pass.
- The new React SPA uses paged API adapters, explicit simulation execution
  conditions and preview results shared between Evidence and Timeline. It
  displays request failures and clears stale context on selection changes.
- Tabs load lazily and ELK runs in a browser Worker. Pipeline layout responses are
  scoped to the current view. Timeline pan preserves its time span and responds
  to container resize.
- URL navigation restores hierarchy, view and saved evidence across reload/back.
  Pinned evidence must belong to the selected scenario and variant. Query uses
  the structured backend API rather than presenting an inactive SQL console.
- GitHub CI now validates the SPA install, lint, tests and production build.

## Validation before integration with main

- Python unit and isolated PostgreSQL integration suites: 1,198 passed.
- SPA: 12 regression tests, TypeScript/Vite build and Oxlint passed.
- Ruff and configured mypy scope passed.
- Production-bundle browser checks with synthetic API responses covered
  selection, ELK Worker layout, Level 2 defaults, preview handoff, empty evidence,
  query execution, saved-result links, reload/back and foreign-evidence rejection.

These pre-integration results do not replace CI on the final PR revision.

## Boundaries

The SPA supplements the existing Streamlit Workbench. Preview results are not
saved; the SPA comparison tab is explicitly unavailable. Full graph/group visual
parity, comparison/save UX, large-list virtualization, deeper SQL predicate
pushdown and issue-policy consolidation remain follow-up work. Existing stored
evidence is not rewritten. The resource model is a conservative reservation
model and does not replace real-hardware calibration.

Current contracts are documented in `docs/guides/spa-navigation.md`,
`docs/contracts/simulation/soc-simulation-contract.md` and
`docs/design/viewer-and-projection.md`.

## Integration validation

Integrated `origin/main` at `448f7ad`, retaining its correlation features,
Streamlit Workbench, fixture changes and simulation-only query semantics.
Conflicts were resolved by combining those behaviors with the narrower evidence
read and independent resource-capacity regression tests.

- Integrated Python unit + PostgreSQL tests: 1,293 passed, combined coverage 85.79%.
- CI-style unit-only check after the dependency security patch: 1,145 passed,
  coverage 82.31% (required minimum 80%).
- New SPA: locked npm install, 12 tests, lint and production build passed.
- Existing Workbench: locked npm install, 34 tests and typecheck passed.
- Frozen runtime dependency audit initially found three Tornado 6.5.7 advisories.
  Updated only Tornado to 6.5.8; the repeated audit found no known vulnerabilities.
- Ruff and configured mypy scope passed.
