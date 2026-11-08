"""Streamlit user interface. Run: streamlit run app.py"""
import json
import os
import hashlib
from pathlib import Path

import streamlit as st

from promo_core import read_episodes, generate_candidates, shortlist, export_result, candidate_text
from promo_ai import evaluate_gemini

st.set_page_config(page_title='Kuku Promo Intelligence', page_icon='🎬', layout='wide')
st.title('🎬 Kuku Promo Intelligence')
st.caption('Story-aware promo discovery · 20–60 second cuts · explainable ranking')

with st.sidebar:
    st.header('1 · Input')
    data_file = st.file_uploader('Upload screenplay ZIP or episode TXT', type=['zip', 'txt'])
    st.header('2 · Evaluation')
    mode = st.radio('Ranking method', ['Heuristic demo (offline)', 'Gemini AI (semantic evaluation)'])
    api_key = ''
    model = 'gemini-3.5-flash-lite'
    budget = 60
    if mode.startswith('Gemini'):
        api_key = st.text_input('Gemini API key', value=os.environ.get('GEMINI_API_KEY',''), type='password',
                                help='Kept in this running session; do not commit keys to GitHub.')
        model = st.text_input('Model ID (editable)', value=model)
        budget = st.slider('Candidates to review with AI', min_value=50, max_value=120, value=60, step=10,
                           help='More candidates = more API calls. A budget of 50 guarantees one per episode for this assignment pack.')
        consent = st.checkbox('I understand script excerpts will be sent to the selected AI provider.')
        st.warning('Kuku scripts are confidential. Check the provider’s data-use terms before sending excerpts. Never publish the screenplay pack.')
    else:
        consent = False
        st.info('Offline mode is a **baseline**. It uses keyword and timing rules, not an LLM.')
    count = st.slider('Number of final promos', 5, 20, 12)
    run = st.button('Find promo moments', type='primary', use_container_width=True,
                    disabled=(data_file is None or (mode.startswith('Gemini') and (not api_key or not consent))))

if not data_file:
    st.info('Upload the ZIP containing 50 scripts from your computer, then select the ranking method.')
    st.stop()

if data_file:
    current_file_hash = hashlib.sha256(data_file.getvalue()).hexdigest()
    if st.session_state.get('input_hash') != current_file_hash:
        st.session_state.pop('run_data', None)
        st.session_state.pop('manual_reviews', None)
        st.session_state['input_hash'] = current_file_hash

if run:
    try:
        with st.spinner('Reading screenplay files and generating valid clip boundaries...'):
            if data_file.name.lower().endswith('.zip'):
                episodes = read_episodes(data_file.getvalue())
            else:
                from promo_core import parse_script
                episodes = [parse_script(data_file.getvalue().decode('utf-8-sig'), data_file.name)]
            candidates, diag = generate_candidates(episodes, per_episode=4)
        if mode.startswith('Gemini'):
            indicator = st.progress(0, text='Starting AI evaluation...')
            def update(fraction, phase):
                indicator.progress(float(fraction), text=f'AI phase: {phase} ({round(fraction*100)}%)')
            with st.spinner('Evaluating first-time viewer clarity and story cliffhangers...'):
                ai_candidates, meta = evaluate_gemini(episodes, candidates, api_key=api_key,
                                                    model=model, budget=budget, cache_dir=Path('.cache'), progress=update)
            indicator.empty()
            if ai_candidates:
                candidates_for_output = ai_candidates
                method = 'GEMINI_AI'
                diag.update(meta)
                if meta['ai_errors']:
                    st.warning(f"Some AI calls failed: {len(meta['ai_errors'])} warnings. Results include successful AI evaluations only.")
            else:
                candidates_for_output = candidates
                method = 'HEURISTIC_ONLY'
                diag.update(meta)
                st.error('No usable AI evaluations were returned. Displaying the offline baseline, clearly labelled.')
        else:
            candidates_for_output = candidates
            method = 'HEURISTIC_ONLY'
        results = shortlist(candidates_for_output, count=count)
        if method == 'GEMINI_AI':
            diag['quality_gate'] = 'Hook, cliffhanger and clarity >= 3, with grounded hook and ending evidence'
            diag['quality_eligible'] = sum(
                min(c.get('hook_score', -1), c.get('cliffhanger_score', -1), c.get('clarity_score', -1)) >= 3
                and c.get('hook_evidence_id') and c.get('cliffhanger_evidence_id')
                for c in candidates_for_output)
        st.session_state['run_data'] = (episodes, candidates_for_output, diag, results, method)
    except Exception as exc:
        st.error(f'Could not finish processing: {exc}')

if 'run_data' not in st.session_state:
    st.stop()
episodes, candidates, diag, ranked, method = st.session_state['run_data']
episode_by_no = {ep.number: ep for ep in episodes}

if method == 'HEURISTIC_ONLY':
    st.warning('**Offline baseline:** these are rule-based candidates, not verified best promos or AI judgements.')
else:
    st.success(f'Gemini semantic evaluations completed for {diag.get("ai_successful",0)} clips from '
               f'{diag.get("ai_evaluated_episodes",0)} episodes. This is not proof of real-world ad performance.')

m1, m2, m3, m4 = st.columns(4)
m1.metric('Episodes read', len(episodes))
m2.metric('Timed screenplay entries', sum(len(ep.events) for ep in episodes))
m3.metric('Candidate windows generated', diag['total_generated'])
m4.metric('Final promo shortlist', len(ranked))

promos_tab, story_tab, quality_tab = st.tabs(['🏆 Ranked promos', '📖 Episode story map', '🧪 Quality and export'])
with promos_tab:
    if not ranked:
        st.error('No 20–60-second promo candidates found.')
    for promo in ranked:
        with st.expander(f"#{promo['rank']} · Episode {promo['episode']:02d} · {promo['start']} → {promo['end']} · "
                         f"{promo['duration_seconds']:.1f}s · Score {promo['score']:.1f}",
                         expanded=(promo['rank'] <= 2)):
            st.caption(f"Method: {promo['method']} · Angle: {promo.get('promo_angle','unclassified')}")
            c1, c2 = st.columns(2)
            with c1:
                st.markdown('**Opening hook (source evidence)**')
                st.write(promo['hook_evidence'] or 'No verified opening evidence')
            with c2:
                st.markdown('**Possible cliffhanger (source evidence)**')
                st.write(promo['cliffhanger_evidence'] or 'No verified ending evidence')
            st.markdown('**Why it works / evaluation status**')
            st.write(promo['explanation'])
            if promo.get('confusion_reason'):
                st.caption('Cold-viewer concern: '+promo['confusion_reason'])
            if st.checkbox(
                'Show timecoded source excerpt',
                key=f"source_excerpt_{promo['id']}"
            ):
                ep = episode_by_no[promo['episode']]
                st.code(
                    candidate_text(
                    ep.events,
                    promo['start_seconds'],
                    promo['end_seconds']
                ),
                language='text'
            )
with story_tab:
    st.caption('The logline and continuity notes are included in the story-aware AI evaluation prompt.')
    for ep in episodes:
        with st.expander(f'Episode {ep.number:02d} · {len(ep.events)} entries · {ep.duration:.1f}s'):
            st.write('**Logline:**', ep.logline)
            st.write('**Continuity:**', ep.continuity)
with quality_tab:
    st.subheader('What was checked automatically?')
    invalid = [x for x in ranked if not (20 <= x['duration_seconds'] <= 60)]
    st.write(f'**Valid 20–60s clips:** {len(ranked)-len(invalid)} / {len(ranked)}')
    st.write(f'**Episodes processed:** {diag["episodes_processed"]} / {len(episodes)}')
    st.write(f'**AI coverage:** {diag.get("ai_evaluated_episodes",0)} episodes'
             if method == 'GEMINI_AI' else '**AI coverage:** 0 (offline fallback)')
    if method == 'GEMINI_AI':
        st.write(f"**Passing quality gate:** {diag.get('quality_eligible',0)} / {len(candidates)} evaluated candidates")
    st.info('Strong hooks and cliffhangers are subjective. Manually review a sample and report a real failure in the solution document.')
    st.subheader('Development-only review rubric')
    st.caption('Use this to test your prototype. The production editor should not need to evaluate every generated candidate.')
    if ranked:
        chosen = st.selectbox('Promo to review', [x['id'] for x in ranked],
                              format_func=lambda id: next(f"#{c['rank']} · Episode {c['episode']} · {c['start']}–{c['end']}" for c in ranked if c['id']==id))
        r1,r2,r3 = st.columns(3)
        with r1:
            human_hook = st.select_slider('Hook in first 3 sec', options=[0,1,2], value=1,
                                          help='0 weak, 1 partial, 2 strong')
        with r2:
            human_cliff = st.select_slider('Unresolved cliffhanger', options=[0,1,2], value=1)
        with r3:
            human_clear = st.select_slider('Standalone clarity', options=[0,1,2], value=1)
        human_note = st.text_input('Specific failure or reason for rating (optional)', key='review_note')
        if st.button('Save this human review'):
            reviews = st.session_state.setdefault('manual_reviews', {})
            reviews[chosen] = {'candidate_id':chosen, 'hook_0_to_2':human_hook,
                               'cliffhanger_0_to_2':human_cliff, 'clarity_0_to_2':human_clear,
                               'review_total_0_to_6': human_hook+human_cliff+human_clear,
                               'notes':human_note}
            st.success('Saved in this session. Download the review file before closing the app.')
        if st.session_state.get('manual_reviews'):
            st.write(f"Reviewed {len(st.session_state['manual_reviews'])} distinct promos")
            st.download_button('Download human_reviews.json',
                               json.dumps(list(st.session_state['manual_reviews'].values()), indent=2),
                               file_name='human_reviews.json', mime='application/json')
    result_obj = export_result(episodes, candidates, ranked, diag, method)
    result_json = json.dumps(result_obj, indent=2, ensure_ascii=False)
    st.download_button('Download complete raw run (.json)', result_json,
                       file_name='kuku_raw_run.json', mime='application/json')
    import csv, io
    csv_io = io.StringIO()
    fields = ['rank', 'episode', 'start', 'end', 'duration_seconds', 'score', 'method',
              'hook_evidence', 'cliffhanger_evidence', 'promo_angle', 'explanation']
    writer = csv.DictWriter(csv_io, fieldnames=fields)
    writer.writeheader()
    writer.writerows({k: promo.get(k, '') for k in fields} for promo in ranked)
    st.download_button('Download editor shortlist (.csv)', csv_io.getvalue(),
                       file_name='kuku_promo_shortlist.csv', mime='text/csv')
    with st.expander('Show processing diagnostics'):
        st.json(diag)
