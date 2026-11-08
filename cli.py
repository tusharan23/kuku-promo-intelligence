"""CLI for repeatable headless runs. Example: python cli.py your_scripts.zip --output outputs/"""
import argparse
import csv
import json
import os
from pathlib import Path
from promo_core import read_episodes, generate_candidates, shortlist, export_result
from promo_ai import evaluate_gemini


def main():
    parser = argparse.ArgumentParser(description='Screenplay to ranked promo candidates')
    parser.add_argument('input', help='Path to a ZIP, TXT or folder of TXT screenplays')
    parser.add_argument('--output', default='outputs', help='Private output folder')
    parser.add_argument('--count', type=int, default=12)
    parser.add_argument('--method', choices=['heuristic', 'gemini'], default='heuristic')
    parser.add_argument('--model', default='gemini-3.5-flash-lite')
    parser.add_argument('--ai-budget', type=int, default=60)
    args = parser.parse_args()
    episodes = read_episodes(args.input)
    candidates, diagnostics = generate_candidates(episodes)
    method = 'HEURISTIC_ONLY'
    if args.method == 'gemini':
        api_key = os.getenv('GEMINI_API_KEY', '')
        if not api_key:
            raise SystemExit('Set GEMINI_API_KEY in your terminal first; it is not included in source code.')
        print('Warning: script excerpts will be transmitted to the configured AI provider. Verify confidentiality terms.')
        candidates, extra = evaluate_gemini(episodes, candidates, api_key, model=args.model,
                                            budget=args.ai_budget, cache_dir=Path('.cache'))
        diagnostics.update(extra)
        if not candidates:
            raise SystemExit('AI evaluations failed. No silent fallback; rerun with --method heuristic to test baseline.')
        method = 'GEMINI_AI'
    finals = shortlist(candidates, count=args.count)
    if method == 'GEMINI_AI':
        diagnostics['quality_gate'] = 'Hook, cliffhanger and clarity >= 3, with grounded hook and ending evidence'
        diagnostics['quality_eligible'] = sum(
            min(c.get('hook_score', -1), c.get('cliffhanger_score', -1), c.get('clarity_score', -1)) >= 3
            and c.get('hook_evidence_id') and c.get('cliffhanger_evidence_id') for c in candidates)
    result = export_result(episodes, candidates, finals, diagnostics, method)
    folder = Path(args.output)
    folder.mkdir(exist_ok=True, parents=True)
    (folder/'raw_run.json').write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding='utf-8')
    fields = ['rank','episode','start','end','duration_seconds','score','method',
              'hook_evidence','cliffhanger_evidence','promo_angle','explanation']
    with (folder/'promo_shortlist.csv').open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows({k:c.get(k,'') for k in fields} for c in finals)
    print(f'Read {len(episodes)} episodes, {sum(len(e.events) for e in episodes)} events; '
          f'generated {diagnostics["total_generated"]} possible windows; wrote {len(finals)} promos ({method}).')
    print(f'Outputs: {folder.resolve()}')


if __name__ == '__main__':
    main()
