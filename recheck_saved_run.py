"""Re-apply quality/boundary rules to a SAVED Gemini result, without new API calls.

This is a deterministic secondary review, NOT a new Gemini inference run. The original
unedited raw run remains unchanged for the assignment's raw-output requirement.
"""
from __future__ import annotations
import argparse
import csv
import json
from pathlib import Path
from promo_core import read_episodes, shortlist, _inside_dialogue

CSV_FIELDS = ['rank','episode','start','end','duration_seconds','score','method',
              'hook_evidence','cliffhanger_evidence','promo_angle','explanation']


def recheck_saved(raw: dict, episodes=None, count: int = 12) -> dict:
    if raw.get('method') != 'GEMINI_AI':
        raise ValueError('A saved Gemini AI run is required; not heuristic-only output.')
    evaluated = raw.get('evaluated_candidates', [])
    if not evaluated:
        raise ValueError('Saved run has no evaluated candidates.')
    original = raw.get('ranked_promos', [])
    by_ep = {ep.number: ep for ep in episodes} if episodes is not None else {}
    included, boundary_rejected = [], []
    for c in evaluated:
        ep = by_ep.get(c['episode'])
        if episodes is not None and ep is None:
            raise ValueError(f'Episode {c["episode"]} not present in screenplay pack')
        if ep and any(_inside_dialogue(ep.events, t) for t in (c['start_seconds'], c['end_seconds'])):
            boundary_rejected.append(c['id'])
        else:
            included.append(c)
    finals = shortlist(included, count=count)
    filtered = json.loads(json.dumps(raw))  # never change the supplied original object
    filtered['ranked_promos'] = finals
    filtered['derived_review'] = {
        'status': 'DETERMINISTIC_REVIEW_OF_SAVED_AI_RESPONSES',
        'note': 'No new Gemini calls. Preserves original AI evaluations and reranks after quality and boundary checks.',
        'min_hook_cliffhanger_clarity': 3,
        'require_evidence_ids': True,
        'dialogue_boundary_verified_against_scripts': episodes is not None,
        'boundary_rejected_ids': boundary_rejected,
        'original_final_count': len(original),
        'reviewed_final_count': len(finals),
        'evaluated_candidates_reused': len(evaluated),
    }
    return filtered


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('saved_raw_json',help='Original unedited Gemini raw run')
    parser.add_argument('--scripts',help='Private screenplay ZIP used to verify cut boundaries')
    parser.add_argument('--output',default='outputs/quality_review')
    parser.add_argument('--count',type=int,default=12)
    args=parser.parse_args()
    raw=json.loads(Path(args.saved_raw_json).read_text(encoding='utf-8'))
    episodes=read_episodes(args.scripts) if args.scripts else None
    data=recheck_saved(raw, episodes, args.count)
    dst=Path(args.output); dst.mkdir(exist_ok=True,parents=True)
    (dst/'quality_checked_run.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf8')
    with (dst/'quality_checked_shortlist.csv').open('w',newline='',encoding='utf8') as f:
        w=csv.DictWriter(f,fieldnames=CSV_FIELDS); w.writeheader()
        w.writerows({k:c.get(k,'') for k in CSV_FIELDS} for c in data['ranked_promos'])
    print('Reused',len(data['evaluated_candidates']),'recorded AI evaluations; exported',len(data['ranked_promos']),'quality-checked promos.')
    print('No new Gemini calls. Original raw results were not modified.')

if __name__=='__main__': main()
