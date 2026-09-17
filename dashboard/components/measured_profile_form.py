"""Measured replay UI: select a capture, review mapping, prepare and run a pinned profile."""
from __future__ import annotations

import json
from urllib.parse import quote

import streamlit as st
import yaml

from dashboard.components.evidence_api_client import list_evidence
from dashboard.components.simulation_api_client import _request_json
from dashboard.components.viewer_api_client import ViewerApiError
from scenario_db.models.evidence.profiling import MeasuredTimingProfile


def profile_payload(raw: dict, *, scenario_id: str, variant_id: str, frames: int = 4) -> dict:
    profile = MeasuredTimingProfile.model_validate(raw)
    if (profile.scenario_ref, profile.variant_ref) != (scenario_id, variant_id):
        raise ValueError('Profile does not belong to the selected scenario/variant')
    context = dict(profile.capture_context)
    if not all(context.get(k) for k in ('silicon_rev', 'sw_baseline_ref', 'thermal')):
        raise ValueError('Profile has incomplete capture context')
    context['method'] = 'calculation'
    return dict(scenario_id=scenario_id, variant_id=variant_id, execution_context=context,
                config=dict(timing_profile=profile.model_dump(mode='json'), include_timeline=True,
                            timeline_frame_count=frames), dvfs_tables={}, persist=False, force=False)


def default_task_mapping(evidence: dict) -> dict[str, str]:
    rows = [*(evidence.get('sw_task_timing') or []), *(evidence.get('hw_task_timing') or [])]
    return {row['task']:row.get('node_id') or row['task'] for row in rows if row.get('task')}


def render_measured_profile_form(*, api_base: str, scenario_id: str, variant_id: str) -> dict | None:
    st.subheader('Measured timing profile')
    st.caption('Select a measured capture and review task mapping. Capture conditions are retained; this does not calibrate power.')
    scope = f'{api_base}|{scenario_id}|{variant_id}'
    state_key = f'measured_profile:{scope}'
    choice = st.radio('Profile source', ['Stored measurement', 'Profile YAML'], key=f'{scope}:source')
    raw = None
    if choice == 'Profile YAML':
        uploaded = st.file_uploader('Timing profile YAML', type=['yaml','yml'], key=f'{scope}:upload')
        if uploaded is not None:
            try:
                if uploaded.size > 1_000_000:
                    raise ValueError('Profile YAML exceeds 1 MB')
                raw = yaml.safe_load(uploaded.getvalue())
                if not isinstance(raw, dict):
                    raise ValueError('Profile YAML must contain an object')
            except (ValueError, yaml.YAMLError) as exc:
                st.error(str(exc)); return None
    else:
        try:
            items = list_evidence(api_base, kind='evidence.measurement', scenario_ref=scenario_id, variant_ref=variant_id)
        except ViewerApiError as exc:
            st.error(str(exc)); return None
        if not items:
            st.info('No measurements in this scope. Import a capture or upload an existing profile YAML.')
            return None
        by_id = {row['id']:row for row in items}
        selected = st.selectbox('Measurement capture', list(by_id), key=f'{scope}:capture')
        item = by_id[selected]
        st.json(item.get('execution_context') or {}, expanded=False)
        for field in ('hw_task_timing', 'sw_task_timing', 'sw_event_latency'):
            if item.get(field):
                st.caption(field)
                st.dataframe(item[field], hide_index=True, use_container_width=True)
        mapping = st.text_area('Task → active node mapping (JSON)',
                               value=json.dumps(default_task_mapping(item), indent=2), key=f'{scope}:{selected}:mapping')
        profile_id = st.text_input('Profile ID', value=f'{selected}-timing', key=f'{scope}:{selected}:id')
        revision = st.number_input('Profile revision', min_value=1, value=1, step=1, key=f'{scope}:{selected}:revision')
        statistic = st.selectbox('Runtime case', ['mean','min','max'], key=f'{scope}:{selected}:statistic')
        signature = (selected, mapping, profile_id, int(revision), statistic)
        if st.button('Prepare measured profile', key=f'{scope}:prepare'):
            st.session_state.pop(state_key, None)
            try:
                task_mapping = json.loads(mapping)
                if not isinstance(task_mapping, dict) or not task_mapping:
                    raise ValueError('Provide a nonempty task mapping')
                prepared = _request_json('POST', api_base, f'/evidence/{quote(selected, safe="")}/timing-profile',
                    json=dict(profile_id=profile_id, revision=int(revision), statistic=statistic, task_mapping=task_mapping))
                st.session_state[state_key] = (signature, prepared)
            except (ValueError, ViewerApiError) as exc:
                st.error(str(exc))
                if isinstance(exc, ViewerApiError) and exc.body:
                    st.code(exc.body)
        saved = st.session_state.get(state_key)
        if saved and saved[0] == signature:
            raw = saved[1]
    if raw is None:
        return None
    frames = st.number_input('Replay frames', min_value=1, max_value=16, value=4, step=1, key=f'{scope}:frames')
    try:
        payload = profile_payload(raw, scenario_id=scenario_id, variant_id=variant_id, frames=int(frames))
    except ValueError as exc:
        st.error(str(exc)); return None
    profile = payload['config']['timing_profile']
    st.success(f"{profile['profile_id']} / revision {profile['revision']} / {profile['statistic']}")
    st.json(profile, expanded=False)
    st.download_button('Download pinned profile', yaml.safe_dump(profile, sort_keys=False),
                       file_name='timing-profile.yaml', mime='application/yaml', key=f'{scope}:download')
    st.caption('Preview does not save evidence. To roll back, upload an earlier profile revision; the API rechecks source and baseline.')
    return payload if st.button('Run measured timing preview', type='primary', key=f'{scope}:run') else None
