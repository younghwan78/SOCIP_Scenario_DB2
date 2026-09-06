# SPA Navigation and Saved Evidence Links

| Field | Value |
| --- | --- |
| Status | Current |
| Last verified | 2026-09-06 |
| Scope | React SPA in `web/` |
| Tests | `web/tests/urlState.test.ts`, `web/tests/client.test.ts` |

The SPA restores its hierarchy and selected view from the URL before rendering.
Changing the hierarchy, tab or view level creates a browser history entry.
Back/forward restores those values together, without requests for an intermediate
mixture of old and new selections.

| Parameter | Meaning |
| --- | --- |
| `soc_id`, `project_id` | SoC and board/project filters |
| `scenario_id`, `variant_id` | Scenario and variant selection |
| `tab` | `timeline` (default), `pipeline`, `evidence`, `explorer`, `query` |
| `level` | Pipeline depth: `0` (default), `1`, `2` |
| `mode` | Level 0 mode: `architecture` (default), `topology`, `resource` |
| `expand` | Level 2 target; camera is the default when omitted |
| `sim` | `latest` enables the latest pipeline simulation overlay |
| `sim_evidence_id` | Pins a saved simulation and enables its pipeline overlay |

Example saved-result query string:

```text
?scenario_id=uc-example&variant_id=FHD30&tab=evidence&sim_evidence_id=sim-example
```

In Evidence Dashboard, **Pin saved result in URL** changes the address to the
currently displayed saved evidence. Copy that URL to share the same result.
**Return to latest simulation** removes the pin. Pinned evidence must be a
simulation belonging to both the selected scenario and variant. A foreign or
measurement evidence produces an error instead of being displayed as the selected
scenario's simulation. The Pipeline API also validates evidence membership.

Preview results are not persisted. Evidence and Timeline share them in the
browser's query cache, and they cannot be pinned as saved evidence. Reloading a
preview loads the latest saved result, if any. API credentials, form inputs,
hover state, selected task and viewport coordinates are not written into generated
links. Query editor text is not restored by this feature.

Unsupported tab, level and mode values fall back to the defaults. A variant
without a scenario and an evidence without a scenario/variant are discarded.
Base scenario pipeline views remain supported; the SPA does not invent a variant
ID to run a simulation.
