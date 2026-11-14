"""Optional Chinese event-scope research using frozen learned labels; never CSL generation."""
from collections import Counter
import hashlib
import importlib.util
import json
from pathlib import Path
import re

spec = importlib.util.spec_from_file_location('scope_frozen_labels', Path(__file__).with_name('sign-csl-learned.py'))
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)
SCHEMA = 'signbridge-chinese-event-scope-v1'


def event_graph(roles, spans):
    graph = {'type': 'event', 'roles': {k: roles[k] for k in sorted(roles) if k not in ('negation', 'modal')}}
    operators = [s for s in spans if s['role'] in ('negation', 'modal')]
    for value in reversed(operators):
        graph = {'type': 'operator', 'operator': value['role'] + ':' + value['text'], 'argument': graph}
    return graph


def graph_key(graph):
    return hashlib.sha256(json.dumps(graph, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def tagged_spans(parser, text):
    encoded = [[parser.lookup[f] for f in base.features(text, i) if f in parser.lookup] for i in range(len(text))]
    tags = base.decode(encoded, parser.weights, parser.transitions)
    spans = []
    for i, tag_id in enumerate(tags):
        tag = base.LABELS[tag_id]
        if tag == 'O':
            return None
        role = tag[2:]
        if tag.startswith('B-') or not spans or spans[-1]['role'] != role:
            spans.append({'role': role, 'start': i, 'end': i + 1, 'text': text[i]})
        else:
            spans[-1]['end'] = i + 1
            spans[-1]['text'] += text[i]
    return spans


class ScopeParser:
    def __init__(self, parser, evidence=()):
        self.parser = parser
        self.evidence = list(evidence)

    def predict(self, text):
        result = self.parser.predict(text)
        result.update(scope_experiment=True, scope_schema=SCHEMA,
                      model_kind='frozen_perceptron_with_explicit_scope_constraints',
                      model_id=self.parser.metadata['model_id'] + '-scope-v1',
                      model_training_ready=False, confidence=None)
        # Do not erase clause boundaries by the baseline punctuation normalizer.
        if isinstance(text, str) and re.search(r'[。.!！?？；;]', text.strip().rstrip('。.!！?？；;')):
            result.update(status='abstained', roles={}, spans=[], reasons=['internal_clause_boundary'])
        if result['status'] != 'parsed':
            reasons = set(result['reasons'])
            if reasons and reasons <= {'operator_scope_requires_review', 'unseen_role_order'}:
                spans = tagged_spans(self.parser, base.clean(text))
                if spans and self._supported_extension(spans):
                    result.update(status='parsed', roles={s['role']: s['text'] for s in spans}, spans=spans,
                                  reasons=[], accepted_by='learned_labels_plus_scope_contract')
        if result['status'] == 'parsed':
            result['event_graph'] = event_graph(result['roles'], result['spans'])
            result['event_key'] = graph_key(result['event_graph'])
            result['meaning_key'] = result['event_key']
            result['expression_plan'] = expression_plan(result, self.evidence)
        return result

    def _supported_extension(self, spans):
        counts = Counter(s['role'] for s in spans)
        if counts['actor'] != 1 or counts['predicate'] != 1 or any(v > 1 for v in counts.values()):
            return False
        if any(s['text'] not in self.parser.allowed_values.get(s['role'], ()) for s in spans):
            return False
        roles = {s['role']: s['text'] for s in spans}
        support = self.parser.argument_support.get(roles['predicate'], {})
        if any(roles[k] not in support.get(k, ()) for k in ('patient', 'goal') if k in roles):
            return False
        order = tuple(s['role'] for s in spans)
        operators = [s['role'] + ':' + s['text'] for s in spans if s['role'] in ('negation', 'modal')]
        predicate_index = order.index('predicate')
        if any(order.index(k) > predicate_index for k in ('negation', 'modal') if k in order):
            return False
        if len(operators) == 2:
            if operators not in [['negation:不', 'modal:想'], ['modal:想', 'negation:不'], ['negation:不', 'modal:能']]:
                return False
            # The remainder must still have a role order seen by the frozen model.
            reduced = tuple(k for k in order if k != 'negation')
            return reduced in self.parser.allowed_orders and not counts['politeness'] and not counts['aspect']
        if counts['aspect'] and not operators and roles['aspect'] in ('了', '过') and roles['predicate'] in ('去', '来', '买', '看', '找到'):
            return tuple(k for k in order if k != 'aspect') in self.parser.allowed_orders
        return False


def expression_plan(prediction, evidence=()):
    roles = prediction.get('roles', {})
    candidates = {}
    for row in evidence:
        text = row.get('proposed_text')
        if isinstance(text, str):
            candidates.setdefault(text, []).append({'id': row['id'], 'human_approved': False,
                                                    'word_boundaries_verified': False, 'training_ready': False})
    components = [{'role': role, 'text': text, 'evidence': candidates.get(text, [])}
                  for role, text in roles.items()]
    return {'schema': 'signbridge-meaning-evidence-plan-v1',
            'scene': 'daily_coming_going' if roles.get('predicate') in ('去', '来', '到', '回') else 'simple_interpersonal',
            'status': 'review_required', 'can_play': False, 'motion_items': [],
            'components': components, 'uncovered': [c['text'] for c in components if not c['evidence']],
            'blockers': ['csl_word_alignment_unreviewed', 'spatial_and_nonmanual_realization_unreviewed'],
            'order_contract': 'semantic components only; not a CSL gloss sequence or motion order',
            'human_approved': False, 'training_ready': False, 'model_training_ready': False}
