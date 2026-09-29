"""Opt-in review reproductions with existing protocol/model fakes; not live AI."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[5] / 'student-4'))
from tests.backend.test_assistant import ACTIVITY, ProtocolFake, run

search = {'type': 'tool', 'name': 'activities_search', 'arguments': {}}
card = {'type': 'final', 'parts': [{'type': 'activity', 'activity_id': ACTIVITY}]}

def text_answer(text):
    return {'type': 'final', 'parts': [{'type': 'text', 'text': text}]}

cases = [
    ('whole_group', 'Find activities for 4 people under AUD 100 for the whole group', [search, card]),
    ('correct_rejection_overridden', 'Find Melbourne activities under AUD 100', [search, text_answer('The inspected activity is in Sydney, not Melbourne. I found no suitable activity in these results.')]),
    ('clarification_overridden', 'Find nearby activities under AUD 100', [text_answer('Which city or area would you like to explore?')]),
    ('date_lost', 'Find activities for 4 people on 2026-10-1', [{'type': 'tool', 'name': 'activities_search', 'arguments': {'filters': {'availability': {'date': '2026-10-01'}}}}, card]),
]
rows = []
for name, question, actions in cases:
    result = run(actions, ProtocolFake(), question=question)
    rows.append({'case': name, 'question': question, 'model_actions': actions, 'response': result})
    print(name, result['status'], result['parts'])
Path(__file__).with_name('deterministic-findings.json').write_text(json.dumps(rows, indent=2)+'\n')
