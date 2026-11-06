"""Data preparation cannot relabel CSL or leak frozen Chinese contrasts."""
import importlib.util
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

TOOL = Path(__file__).resolve().parents[1] / 'src/tools/sign-csl-semantic-round.py'


def module():
    spec = importlib.util.spec_from_file_location('semantic_round_test', TOOL)
    result = importlib.util.module_from_spec(spec); spec.loader.exec_module(result)
    return result


class ContractTests(unittest.TestCase):
    def test_fixture_is_unique_group_disjoint_and_preserves_scope_contrasts(self):
        m = module(); rows = m.cases(); m.validate_cases(rows)
        by_text = {r['text']: r for r in rows}
        self.assertEqual(len(rows), len(by_text))
        a, b = by_text['我不想去'], by_text['我想不去']
        self.assertNotEqual(a['expected_operators'], b['expected_operators'])
        self.assertEqual(a['expected_operators'], ['negation:不', 'modal:想'])
        self.assertEqual(b['expected_operators'], ['modal:想', 'negation:不'])
        self.assertEqual(by_text['我们']['expected_kind'], 'entity')
        self.assertEqual(by_text['我们']['expected_roles'], {'actor': '我们'})
        for row in rows:
            self.assertFalse(row['human_approved']); self.assertFalse(row['csl_supervision'])
            self.assertNotIn('gloss_sequence', row)

    def test_invalid_pairs_partitions_and_role_spans_rejected(self):
        m = module(); good = m.cases()
        for change in ['duplicate', 'partition', 'pair', 'tags']:
            rows = json.loads(json.dumps(good))
            if change == 'duplicate': rows.append(rows[0])
            elif change == 'partition':
                same = next(r for r in rows[1:] if r['template_group'] == rows[0]['template_group'])
                same['partition'] = 'challenge' if rows[0]['partition'] != 'challenge' else 'train'
            elif change == 'pair':
                paired = next(r for r in rows if r.get('pair_id')); paired['pair_relation'] = 'same' if paired['pair_relation'] == 'different' else 'different'
            else: next(r for r in rows if r['tags'])['tags'][0] = 999
            with self.subTest(change=change), self.assertRaises(ValueError): m.validate_cases(rows)

    def test_training_reserves_old_and_new_contrasts_and_conflicting_labels(self):
        m = module(); rows = m.cases()
        candidate = next(r for r in rows if r['partition'] == 'train')
        train, dev, removed = m.partition(rows, {m.normalize(candidate['text'])})
        self.assertNotIn(candidate['id'], {r['id'] for r in train + dev})
        self.assertIn(candidate['id'], removed)
        self.assertFalse({m.normalize(r['text']) for r in train} & {m.normalize(r['text']) for r in dev})
        self.assertFalse({r['template_group'] for r in train} & {r['template_group'] for r in dev})
        self.assertTrue(all(r['partition'] != 'challenge' for r in train + dev))

    def test_dataset_disagreement_is_a_clue_not_a_label_correction(self):
        m = module()
        reference = ['我', '不', '去']; prediction = ['你', '去']
        result = m.diagnose(reference, prediction, {'我': 3, '不': 4, '去': 7})
        self.assertEqual(result['deletions'], 1)
        self.assertTrue(result['person_surface_mismatch'])
        self.assertTrue(result['negation_surface_mismatch'])
        self.assertFalse(result['annotation_changed']); self.assertFalse(result['human_approved'])
        self.assertEqual(reference, ['我', '不', '去'])

    def test_all_accept_and_all_reject_cannot_look_successful(self):
        m = module()
        rows = [next(r for r in m.cases() if r['text'] == '我帮你'),
                next(r for r in m.cases() if r['expected_roles'] is None)]
        class Reject:
            def predict(self, text): return {'status': 'abstained'}
        metrics = m.evaluate(Reject(), rows)['metrics']
        self.assertEqual(metrics['supported_coverage'], 0)
        self.assertIsNone(metrics['selective_accuracy'])
        class Accept:
            def predict(self, text):
                return {'status': 'parsed', 'roles': {'actor': '我', 'predicate': '帮', 'patient': '你'}, 'spans': []}
        metrics = m.evaluate(Accept(), rows)['metrics']
        self.assertEqual(metrics['false_accept_rate'], 1)
        self.assertEqual(metrics['selective_accuracy'], .5)

    def test_training_input_hash_tampering_and_gate_escalation_fail(self):
        m = module(); rows = m.cases()
        train, dev, _ = m.partition(rows, set())
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve() / 'package'
            fixture = json.dumps({**m.GATES, 'schema': m.SCHEMA, 'frozen_before_current_round_evaluation': True, 'rows': rows}, ensure_ascii=False).encode()
            m.write_package(root, train, dev, {'fixture_sha256': hashlib.sha256(fixture).hexdigest()}, fixture)
            self.assertEqual(len(m.read_package(root)[0]['train']), len(train))
            with (root / 'train.jsonl').open('a') as stream: stream.write('{}\n')
            with self.assertRaises(ValueError): m.read_package(root)
            m.u.seal(root)
            with self.assertRaises(ValueError): m.read_package(root)

    def test_resealed_research_gate_escalation_is_rejected(self):
        m = module(); rows = m.cases(); train, dev, _ = m.partition(rows, set())
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve() / 'package'
            fixture = json.dumps({**m.GATES, 'schema': m.SCHEMA, 'frozen_before_current_round_evaluation': True, 'rows': rows}, ensure_ascii=False).encode()
            m.write_package(root, train, dev, {'fixture_sha256': hashlib.sha256(fixture).hexdigest()}, fixture)
            path = root / 'contract.json'; value = json.loads(path.read_text()); value['training_ready'] = True
            path.write_text(json.dumps(value)); m.u.seal(root)
            with self.assertRaisesRegex(ValueError, 'contract'): m.read_package(root)

    def test_structurally_valid_relabeling_cannot_bypass_original_frozen_target(self):
        m = module(); rows = m.cases(); train, dev, _ = m.partition(rows, set())
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve() / 'package'
            fixture = json.dumps({**m.GATES, 'schema': m.SCHEMA, 'frozen_before_current_round_evaluation': True, 'rows': rows}, ensure_ascii=False).encode()
            m.write_package(root, train, dev, {'fixture_sha256': hashlib.sha256(fixture).hexdigest()}, fixture)
            path = root / 'train.jsonl'
            contents = [json.loads(line) for line in path.read_text().splitlines()]
            row = next(r for r in contents if r['text'] == '我买书')
            row['expected_roles']['goal'] = row['expected_roles'].pop('patient')
            row['spans'][-1]['role'] = 'goal'
            row['tags'][-1] = m.base.LABELS.index('B-goal')
            path.write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in contents))
            m.u.seal(root)
            with self.assertRaisesRegex(ValueError, 'frozen'): m.read_package(root)

    def test_incomplete_pairs_never_receive_a_same_or_different_pair_score(self):
        m = module(); rows = m.cases()
        class Correct:
            def predict(self, text):
                row = next(r for r in rows if r['text'] == text)
                return {'status': 'parsed', 'roles': row['expected_roles'], 'spans': row['spans']}
        for relation in ['same', 'different']:
            row = next(r for r in rows if r['pair_id'] and r['pair_relation'] == relation)
            measured = m.evaluate(Correct(), [row])
            self.assertEqual(measured['pairs'], [])
            self.assertEqual(measured['incomplete_pair_ids'], [row['pair_id']])

    def test_seed_package_cannot_claim_training_ready_without_scope_and_reject_coverage(self):
        m = module(); train, dev, _ = m.partition(m.cases(), set())
        report = m.training_coverage({'train': train, 'dev': dev})
        self.assertFalse(report['ready_for_GPU_training'])
        self.assertIn('compound_scope_absent_from_train', report['blockers'])
        self.assertIn('no_dev_rejection_cases', report['blockers'])
        self.assertGreater(report['counts']['train']['event'], 0)


if __name__ == '__main__': unittest.main()
