import json
import sys
import types
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from promo_core import parse_script, generate_candidates
from promo_ai import evaluate_gemini
from test_core import SAMPLE


def test_two_phase_ai_with_fake_provider(monkeypatch):
    calls = []
    class FakeModels:
        def generate_content(self, model, contents, config):
            phase = 'viewer' if 'cold-start social-media viewer' in contents else 'story'
            records = json.loads(contents.split('CANDIDATES:\n', 1)[1])
            result = []
            for rec in records:
                if phase == 'viewer':
                    result.append({'id':rec['id'], 'hook_score':4, 'clarity_score':4,
                                   'hook_event_id':rec['opening_event_ids'][0], 'confusion_reason':''})
                else:
                    result.append({'id':rec['id'], 'cliffhanger_score':4, 'pacing_score':3,
                                   'cliff_event_id':rec['ending_event_ids'][0],
                                   'promo_angle':'suspense', 'explanation':'The visitor hides a secret.'})
            calls.append(phase)
            return types.SimpleNamespace(text=json.dumps({'results':result}))
    class FakeClient:
        def __init__(self, api_key):
            self.models = FakeModels()
        def close(self):
            pass
    google_module = types.ModuleType('google')
    genai_module = types.ModuleType('google.genai')
    genai_module.Client = FakeClient
    genai_module.types = types.SimpleNamespace(GenerateContentConfig=lambda **kwargs: kwargs)
    google_module.genai = genai_module
    monkeypatch.setitem(sys.modules, 'google', google_module)
    monkeypatch.setitem(sys.modules, 'google.genai', genai_module)
    ep = parse_script(SAMPLE)
    candidates, _ = generate_candidates([ep])
    res, diag = evaluate_gemini([ep], candidates, api_key='placeholder', model='test-model', budget=2)
    assert len(res) == 2
    assert all(c['method'] == 'GEMINI_AI' and c['score'] > 0 for c in res)
    assert diag['ai_successful'] == 2
    assert calls == ['viewer', 'story']


def test_schema_validation_rejects_missing_or_malformed_scores():
    from promo_ai import _valid_results
    batch = [{'id':'ok'}, {'id':'bad'}]
    response = {'results':[
        {'id':'ok', 'hook_score':4, 'clarity_score':3, 'hook_event_id':'A', 'confusion_reason':''},
        {'id':'bad', 'hook_score':'high', 'clarity_score':3, 'hook_event_id':'B', 'confusion_reason':''}
    ]}
    assert list(_valid_results(response,batch,'viewer')) == ['ok']


def test_bad_cache_is_not_reused(tmp_path, monkeypatch):
    from promo_ai import _roundtrip_cached
    batch = [{'id':'one'}]
    calls = []
    def fake_call(client, model, prompt):
        calls.append(1)
        return {'results':[{'id':'one','hook_score':4,'clarity_score':4,
                            'hook_event_id':'abc','confusion_reason':''}]}
    monkeypatch.setattr('promo_ai._call_gemini', fake_call)
    value = _roundtrip_cached(None, 'model','prompt',tmp_path,batch,'viewer')
    assert len(calls) == 1
    assert value['results'][0]['hook_score'] == 4
    cached_file = next(tmp_path.glob('*.json'))
    cached_file.write_text('{'+'"results": [{"id": "one"}]'+'}',encoding='utf8')
    value = _roundtrip_cached(None,'model','prompt',tmp_path,batch,'viewer')
    assert len(calls) == 2
    assert value['results'][0]['hook_score'] == 4
