"""Optional semantic promo evaluation using Google's Gemini API.

All source timestamps are selected by promo_core; the LLM NEVER generates cut points.
AI is optional: the project remains runnable as a clearly labeled heuristic baseline.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import time
from collections import defaultdict

from promo_core import Episode, candidate_text, stamp

RUBRIC = '''You assess short-form drama promo moments for mobile first-time viewers.
Objective: find 20-60 second unedited clip stretches with a hook in first 3 seconds,
an unresolved cliffhanger at the cut, and standalone clarity. Be a strict critic.
Scores are 0 to 5 integers. 0 = absent, 3 = moderate, 5 = exceptional.
Don't reward a shocking word when the scene is hard to understand; don't hallucinate
facts, dialogue, character names, or timestamps. Give low scores when evidence is weak.
Give evidence event IDs that exist in the clip. Return only valid JSON.
'''


def _safe_int(value, default: int = 1) -> int:
    try:
        return min(5, max(0, int(value)))
    except (ValueError, TypeError):
        return default


def _clip_for_llm(ep: Episode, c: dict) -> dict:
    start, end = c['start_seconds'], c['end_seconds']
    timed = [e for e in ep.events if e.end > start and e.start < end and e.kind in ('DIALOGUE', 'ACTION', 'SOUND FX')]
    return {'id': c['id'], 'episode': ep.number, 'duration_seconds': c['duration_seconds'],
            'events': [f'{e.id} [{stamp(e.start)}-{stamp(e.end)}] {e.speaker or e.kind}: {e.text}' for e in timed],
            'opening_event_ids': [e.id for e in timed if e.start < start + 3 and e.end > start],
            'ending_event_ids': [e.id for e in timed if e.end > end - 7 and e.start < end]}


# Gemini free-tier RPM is limited. The app evaluates two prompts per batch,
# so a 60-candidate run may send 30 requests. Pace uncached calls to 10/min.
# Cached prompt responses do NOT cause an API request or incur a delay.
_LAST_GEMINI_REQUEST_AT = 0.0
GEMINI_REQUEST_SPACING_SECONDS = 6.0


def _pace_gemini_request() -> None:
    global _LAST_GEMINI_REQUEST_AT
    delta = time.monotonic() - _LAST_GEMINI_REQUEST_AT
    if _LAST_GEMINI_REQUEST_AT and delta < GEMINI_REQUEST_SPACING_SECONDS:
        time.sleep(GEMINI_REQUEST_SPACING_SECONDS - delta)
    _LAST_GEMINI_REQUEST_AT = time.monotonic()


def _call_gemini(client, model: str, prompt: str) -> dict:
    try:
        from google.genai import types
    except ImportError as exc:
        raise RuntimeError('Install optional google-genai: pip install -r requirements.txt') from exc
    last_exc = None
    for tries in range(3):
        try:
            _pace_gemini_request()
            response = client.models.generate_content(
                model=model,
                contents=prompt,
                config=types.GenerateContentConfig(response_mime_type='application/json', temperature=0.1),
            )
            body = (response.text or '').strip()
            if body.startswith('```'):
                body = body.split('\n', 1)[-1].rsplit('```', 1)[0].strip()
            return json.loads(body)
        except Exception as exc:
            last_exc = exc
            err = str(exc).lower()
            # Retry a rate-limit error once after the minute window has passed.
            # Do not endlessly retry: a daily quota or billing problem won't
            # necessarily clear by waiting.
            if '429' in err or 'resource_exhausted' in err:
                if tries == 0:
                    time.sleep(65)
                    continue
                break
            if any(x in err for x in ('quota', 'billing', 'invalid api key', 'permission_denied')):
                break
            if tries < 2:
                time.sleep(1 + tries * 2)
    raise RuntimeError(f'Gemini model call failed: {str(last_exc)[:350]}') from last_exc


def _make_batch_prompt(episodes_by_id: dict[int, Episode], batch: list[dict], phase: str) -> str:
    clips = [_clip_for_llm(episodes_by_id[c['episode']], c) for c in batch]
    if phase == 'viewer':
        system = '''You are a cold-start social-media viewer who has never seen this series.
You may ONLY see the candidate clip content. Do not assume any prior episode knowledge.
For EACH clip return hook_score (first 3 seconds) and clarity_score (does it make sense
without history) as 0..5 INTEGERS. Identify the earliest relevant hook_event_id from
opening_event_ids, or empty string if no useful hook. Give a short confusion_reason
if unclear. The model should penalize dialogue that starts mid-conversation.
JSON shape {"results": [{"id": "candidate id", "hook_score": 0, "clarity_score": 0,
"hook_event_id":"event id or empty", "confusion_reason": "<= 20 words"}]}.
Return one result for every supplied candidate and do not invent identifiers.
'''
        payload = clips
    else:
        system = '''You are a story editor. You see the clip and its brief context notes.
For EACH clip return cliffhanger_score (0..5: is the cut unresolved?) and
pacing_score (0..5), plus promo_angle (one of betrayal, suspense, romance,
justice, danger, identity, family, other), explanation (<= 28 words, only
grounded claims), and cliff_event_id (one of ending_event_ids or empty).
Important: a reveal already fully resolved by the cut is NOT a cliffhanger.
Be demanding: a scene can be emotional but not a good promotional clip.
JSON shape {"results": [{"id":"candidate id", "cliffhanger_score":0,
"pacing_score":0, "cliff_event_id":"event id or empty", "promo_angle":"other",
"explanation":"<= 28 words"}]}.
Return one result for every supplied candidate and don't invent identifiers.
'''
        payload = []
        for c, cl in zip(batch, clips):
            ep = episodes_by_id[c['episode']]
            clip = dict(cl)
            clip['episode_logline'] = ep.logline
            clip['episode_continuity'] = ep.continuity
            prev = episodes_by_id.get(ep.number - 1)
            if prev:
                clip['previous_episode_logline'] = prev.logline
            payload.append(clip)
    return RUBRIC + '\n' + system + '\nCANDIDATES:\n' + json.dumps(payload, ensure_ascii=False)


def _valid_results(blob: dict, batch: list[dict]) -> dict:
    found = {c['id'] for c in batch}
    return {v['id']: v for v in blob.get('results', [])
            if isinstance(v, dict) and isinstance(v.get('id'), str) and v['id'] in found}


def _roundtrip_cached(client, model, prompt, cache_dir: Path | None) -> dict:
    if cache_dir is None:
        return _call_gemini(client, model, prompt)
    cache_dir.mkdir(exist_ok=True, parents=True)
    key = hashlib.sha256((model + '\n' + prompt).encode()).hexdigest()
    cache_file = cache_dir / (key + '.json')
    if cache_file.exists():
        return json.loads(cache_file.read_text(encoding='utf-8'))
    response = _call_gemini(client, model, prompt)
    cache_file.write_text(json.dumps(response, ensure_ascii=False, indent=2), encoding='utf-8')
    return response


def choose_to_evaluate(candidates: list[dict], budget: int = 60) -> list[dict]:
    """First take best candidate from each episode, then best remaining across series."""
    candidates = sorted(candidates, key=lambda x: (-x['heuristic_score'], x['episode']))
    best_per_ep = {}
    for c in candidates:
        best_per_ep.setdefault(c['episode'], c)
    if budget < len(best_per_ep):
        return candidates[:budget]
    chosen = list(best_per_ep.values())
    seen = {c['id'] for c in chosen}
    for c in candidates:
        if len(chosen) >= budget:
            break
        if c['id'] not in seen:
            seen.add(c['id'])
            chosen.append(c)
    return chosen


def evaluate_gemini(episodes: list[Episode], candidates: list[dict], api_key: str,
                    model: str = 'gemini-3.5-flash-lite', budget: int = 60,
                    batch_size: int = 4, cache_dir: Path | None = None,
                    progress=None) -> tuple[list[dict], dict]:
    """Returns AI-evaluated candidates and diagnostics. Never silently labels fallback as AI."""
    if not api_key.strip():
        raise ValueError('Missing Gemini API key')
    try:
        from google import genai
    except ImportError as exc:
        raise RuntimeError('Install google-genai first: pip install -r requirements.txt') from exc
    client = genai.Client(api_key=api_key.strip())
    by_ep = {e.number: e for e in episodes}
    selected = choose_to_evaluate(candidates, min(budget, len(candidates)))
    viewer, story, errors = {}, {}, []
    steps = ((len(selected) + batch_size-1)//batch_size) * 2
    completed = 0
    try:
        for phase in ('viewer', 'story'):
            for k in range(0, len(selected), batch_size):
                batch = selected[k:k+batch_size]
                prompt = _make_batch_prompt(by_ep, batch, phase)
                try:
                    blob = _roundtrip_cached(client, model, prompt, cache_dir)
                    res = _valid_results(blob, batch)
                    (viewer if phase == 'viewer' else story).update(res)
                    if len(res) != len(batch):
                        errors.append(f'{phase} batch {k//batch_size + 1}: {len(res)}/{len(batch)} IDs returned')
                except Exception as exc:
                    errors.append(f'{phase} batch {k//batch_size + 1}: {str(exc)[:220]}')
                completed += 1
                if progress:
                    progress(completed / max(1, steps), phase)
    finally:
        client.close()
    evaluated = []
    for c in selected:
        rid = c['id']
        if rid not in viewer or rid not in story:
            continue
        ep = by_ep[c['episode']]
        valid_ids = {e.id: e for e in ep.events if e.end > c['start_seconds'] and e.start < c['end_seconds']}
        v, s = viewer[rid], story[rid]
        hs = _safe_int(v.get('hook_score'))
        cs = _safe_int(v.get('clarity_score'))
        ks = _safe_int(s.get('cliffhanger_score'))
        ps = _safe_int(s.get('pacing_score'))
        total = round(20 * (.35*hs + .35*ks + .20*cs + .10*ps), 2)
        updated = dict(c)
        updated.update({"score": total, "method": "GEMINI_AI", "model": model,
                        "hook_score": hs, "cliffhanger_score": ks,
                        "clarity_score": cs, "pacing_score": ps,
                        "confusion_reason": str(v.get('confusion_reason', ''))[:250],
                        "promo_angle": str(s.get('promo_angle', 'other'))[:40],
                        "explanation": str(s.get('explanation', ''))[:320]})
        hook_id = v.get('hook_event_id', '')
        cliff_id = s.get('cliff_event_id', '')
        openids = {e.id for e in ep.events if e.start < c['start_seconds']+3 and e.end > c['start_seconds']}
        closeids = {e.id for e in ep.events if e.end > c['end_seconds']-7 and e.start < c['end_seconds']}
        if hook_id in valid_ids and hook_id in openids:
            updated['hook_evidence_id'] = hook_id
            updated['hook_evidence'] = valid_ids[hook_id].text
        else:
            updated['hook_evidence_id'] = ''
            updated['hook_evidence'] = 'No verified opening-hook evidence'
        if cliff_id in valid_ids and cliff_id in closeids:
            updated['cliffhanger_evidence_id'] = cliff_id
            updated['cliffhanger_evidence'] = valid_ids[cliff_id].text
        else:
            updated['cliffhanger_evidence_id'] = ''
            updated['cliffhanger_evidence'] = 'No verified cliffhanger evidence'
        # Penalize claims of high-quality clips without supporting source evidence.
        if not updated['hook_evidence_id']:
            updated['score'] = min(updated['score'], 65.0)
        if not updated['cliffhanger_evidence_id']:
            updated['score'] = min(updated['score'], 60.0)
        evaluated.append(updated)
    evaluated.sort(key=lambda c: (-c['score'], c['episode']))
    details = {"model": model, "ai_requested": len(selected), "ai_successful": len(evaluated),
               "ai_errors": errors, "ai_evaluated_episodes": len({x['episode'] for x in evaluated}),
               "total_episodes": len(episodes)}
    return evaluated, details
