import sys
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
    assert len(choose_to_evaluate(items, 5)) == 5
    assert len(choose_to_evaluate(items, 10)) == 10
