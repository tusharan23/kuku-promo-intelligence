import sys
import pytest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from promo_core import parse_script, generate_candidates, shortlist, stamp, sec, read_episodes
from promo_ai import choose_to_evaluate, _valid_results

SAMPLE = '''EPISODE NUMBER: Episode 1
EPISODE LOGLINE: A suspicious visitor appears at night.
CONTINUITY NOTES: The story begins here.
--- SCRIPT START ---
SCENE 01
Scene heading: INT. ROOM - NIGHT
Scene start: 00:00.00
Scene end: 00:45.00

**ACTION:**
Start: (00:00.00) | End: (00:02.00)
A stranger throws a letter onto the table.

**MIRA (Shocked):**
Start: (00:02.00) | End: (00:04.00)
"You were supposed to be dead!"

**ACTION:**
Start: (00:05.00) | End: (00:22.00)
She stares at a photograph and moves toward the door.

**STRANGER (Whispering):**
Start: (00:23.00) | End: (00:27.00)
"Do you really want to know who sent me?"

**ACTION:**
Start: (00:27.00) | End: (00:45.00)
The door swings open. A shadow is waiting outside.
--- SCRIPT END ---'''

def test_timestamp_roundtrip():
    assert sec('02:18.00') == 138
    assert stamp(138) == '02:18.00'


def test_episode_parsing():
    ep = parse_script(SAMPLE)
    assert ep.number == 1
    assert len(ep.events) == 5
    assert ep.duration == 45
    assert ep.events[1].kind == 'DIALOGUE'


def test_uppercase_scene_fields():
    ep = parse_script(SAMPLE.replace('Scene start:', 'SCENE START:').replace('Scene end:', 'SCENE END:'))
    assert ep.scenes[0]['end'] == 45


def test_candidate_validity():
    ep = parse_script(SAMPLE)
    pool, d = generate_candidates([ep], per_episode=4)
    assert pool
    assert all(20 <= p['duration_seconds'] <= 60 for p in pool)
    assert d['episodes_processed'] == 1
    assert d['total_generated'] > 0
    assert shortlist(pool, 2)[0]['rank'] == 1


def test_ai_result_validation():
    items = [{'id': 'valid', 'episode': 1}]
    result = _valid_results({'results':[{'id':'fake'},{'id':'valid','hook_score':4}]}, items)
    assert list(result) == ['valid']


def test_select_budget():
    items = [{'id':f'id{i}', 'episode':i, 'heuristic_score':float(i)} for i in range(10)]
    with pytest.raises(ValueError, match='too small'):
        choose_to_evaluate(items, 5)
    assert len(choose_to_evaluate(items, 10)) == 10


def test_no_cut_inside_overlapping_dialogue():
    # The camera ends at 00:30 but the dialogue lasts until 00:32.
    sample = SAMPLE.replace('**STRANGER (Whispering):**\nStart: (00:23.00) | End: (00:27.00)',
                            '**STRANGER (Whispering):**\nStart: (00:23.00) | End: (00:32.00)')
    ep = parse_script(sample)
    clips, _ = generate_candidates([ep], per_episode=100)
    for clip in clips:
        for moment in (clip['start_seconds'], clip['end_seconds']):
            assert not any(e.kind == 'DIALOGUE' and e.start < moment < e.end for e in ep.events)


def test_keyword_matches_whole_word_not_inside_unrelated_text():
    from promo_core import _has_keyword
    assert _has_keyword('I hate you', 'hate')
    assert not _has_keyword('whatever', 'hate')
    assert not _has_keyword('a glove', 'love')
    assert _has_keyword('a horribly shaken girl', 'horrif') is False


def test_quality_gate_filters_bad_cliffhanger_and_confusion():
    examples = [
        dict(id='weak', episode=1, start_seconds=0, end_seconds=25,
             score=95, method='GEMINI_AI', hook_score=5, cliffhanger_score=2,
             clarity_score=5, hook_evidence_id='A', cliffhanger_evidence_id='B'),
        dict(id='clear', episode=2, start_seconds=0, end_seconds=25,
             score=85, method='GEMINI_AI', hook_score=4, cliffhanger_score=4,
             clarity_score=4, hook_evidence_id='A', cliffhanger_evidence_id='B'),
        dict(id='confused', episode=3, start_seconds=0, end_seconds=25,
             score=90, method='GEMINI_AI', hook_score=5, cliffhanger_score=5,
             clarity_score=2, hook_evidence_id='A', cliffhanger_evidence_id='B'),
    ]
    assert [c['id'] for c in shortlist(examples)] == ['clear']


def test_parser_supports_hhmmss_and_text_card():
    sample = SAMPLE.replace('00:45.00', '00:00:45.00')
    sample = sample.replace('**ACTION:**', '**TEXT ON SCREEN:**', 1)
    ep = parse_script(sample)
    assert ep.duration == 45
    assert ep.events[0].kind == 'ACTION'
