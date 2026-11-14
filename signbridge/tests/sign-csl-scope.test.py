"""Scope extension must reuse learned emissions and fail closed outside its contract."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import numpy as np

TOOLS = Path(__file__).resolve().parents[1] / 'src/tools'
def load(name):
    path = TOOLS / name
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ScopeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = load('sign-csl-learned.py')
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name) / 'model'
        cls.base.train_run(cls.root, count=8000, epochs=14, seed=17)
        cls.parser = cls.base.load_model(cls.root)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def experiment(self):
        self.assertTrue((TOOLS / 'sign-csl-scope.py').exists(), 'scope experiment has not been implemented')
        module = load('sign-csl-scope.py')
        return module, module.ScopeParser(self.parser)

    def test_opposite_scope_remains_distinct(self):
        _, parser = self.experiment()
        a, b = [parser.predict(t) for t in ['我不想去', '我想不去']]
        self.assertEqual([a['status'], b['status']], ['parsed', 'parsed'])
        self.assertEqual(a['event_graph']['operator'], 'negation:不')
        self.assertEqual(a['event_graph']['argument']['operator'], 'modal:想')
        self.assertEqual(b['event_graph']['operator'], 'modal:想')
        self.assertNotEqual(a['event_key'], b['event_key'])
        self.assertFalse(a['csl_translation_trained'])
        self.assertFalse(a['model_training_ready'])
        self.assertNotIn('motions', a)

    def test_time_placement_is_same_but_actor_swap_differs(self):
        _, parser = self.experiment()
        a,b=[parser.predict(t) for t in ['我今天去学校', '今天我去学校']]
        self.assertEqual(a['event_key'],b['event_key'])
        self.assertNotEqual(parser.predict('我帮你')['event_key'],parser.predict('你帮我')['event_key'])

    def test_no_lexical_fallback_when_learned_weights_are_blank(self):
        module,_=self.experiment()
        blank=self.base.Parser(self.parser.metadata,np.zeros_like(self.parser.weights),np.zeros_like(self.parser.transitions))
        for text in ['我不想去','我想不去','我帮你']:
            self.assertEqual(module.ScopeParser(blank).predict(text)['status'],'abstained')

    def test_unsupported_and_ambiguous_structures_stay_rejected(self):
        _, parser=self.experiment()
        for text in ['我喝书','我买医院','我学习水','我去火星','我不不去','我想想去','我没有想去','我可以不去','我不想没去','我不想今天去学校','如果你来我就去','我。帮你','我；去学校','我帮你你帮我']:
            with self.subTest(text=text):self.assertEqual(parser.predict(text)['status'],'abstained')

    def test_aspect_and_nonoccurrence_do_not_collapse(self):
        _, parser=self.experiment()
        a,b=[parser.predict(t) for t in ['我去了','我没去']]
        self.assertEqual(a['status'],'parsed')
        self.assertNotEqual(a['event_key'],b['event_key'])

    def test_baseline_predictions_are_unchanged(self):
        _,parser=self.experiment()
        self.assertEqual(self.parser.predict('我不想去')['status'],'abstained')
        self.assertEqual(self.parser.predict('我帮你')['status'],'parsed')
        self.assertTrue(parser.predict('我不想去')['scope_experiment'])

    def test_scene_plan_never_turns_candidate_evidence_into_playback(self):
        module,parser=self.experiment()
        plan=module.expression_plan(parser.predict('我今天去学校'),[{'id':'today','proposed_text':'今天','human_approved':False,'training_ready':False}])
        self.assertEqual(plan['status'],'review_required')
        self.assertFalse(plan['can_play'])
        self.assertEqual(plan['motion_items'],[])
        self.assertIn('今天',[x['text'] for x in plan['components'] if x['evidence']])
        self.assertIn('去',plan['uncovered'])

    def test_contrast_metrics_do_not_reward_all_reject_or_all_accept(self):
        self.assertTrue((TOOLS / 'sign-semantic-contrast.py').exists())
        module=load('sign-semantic-contrast.py')
        rows=[{'id':'good','text':'我帮你','partition':'development','template_group':'test','expected_roles':{'actor':'我','predicate':'帮','patient':'你'},'expected_operators':[]},
              {'id':'bad','text':'我喝书','partition':'development','template_group':'test','expected_roles':None,'expected_operators':None}]
        class Reject:
            def predict(self,text):return {'status':'abstained'}
        rejected=module.evaluate(Reject(),rows)['metrics']
        self.assertEqual(rejected['supported_coverage'],0)
        self.assertIsNone(rejected['selective_accuracy'])
        class Accept:
            def predict(self,text):return {'status':'parsed','roles':{'actor':'我','predicate':'帮','patient':'你'},'spans':[]}
        accepted=module.evaluate(Accept(),rows)['metrics']
        self.assertEqual(accepted['false_accept_rate'],1)
        self.assertEqual(accepted['selective_accuracy'],.5)
        self.assertEqual(accepted['supported_coverage'],1)
        self.assertEqual(accepted['correct_supported_parse_rate'],1)

    def test_model_service_scope_is_explicit_and_baseline_stays_default(self):
        service=load('sign-private-serve.py')
        self.assertTrue(hasattr(service,'load_parser'))
        self.assertEqual(service.load_parser(self.root).predict('我不想去')['status'],'abstained')
        self.assertEqual(service.load_parser(self.root,True).predict('我不想去')['status'],'parsed')

    def test_frozen_groups_have_one_partition(self):
        path=Path(__file__).parent/'fixtures/semantic-contrast-v1.json'
        fixture=json.loads(path.read_text())
        mapping={}
        for row in fixture['rows']:
            mapping.setdefault(row['template_group'],set()).add(row['partition'])
        self.assertTrue(all(len(parts)==1 for parts in mapping.values()))
        self.assertTrue(fixture['frozen_before_scope_implementation'])

    def test_contrast_runner_reports_exact_training_overlap_and_leakage_excluded_metrics(self):
        self.assertTrue((TOOLS / 'sign-semantic-contrast.py').exists())
        module=load('sign-semantic-contrast.py')
        with tempfile.TemporaryDirectory() as tmp:
            report=module.run(self.root,Path(__file__).parent/'fixtures/semantic-contrast-v1.json',Path(tmp)/'run')
        self.assertTrue(report['old_training_text_overlap'])
        self.assertLess(report['leakage_excluded_scope_experiment']['metrics']['cases'],report['scope_experiment']['metrics']['cases'])
        self.assertEqual(len(report['old_training_text_overlap']),len(set(report['old_training_text_overlap'])))
        unseen=report['leakage_excluded_scope_experiment']['by_partition']['structure_holdout']
        self.assertEqual((unseen['cases'],unseen['supported'],unseen['false_accepts']),(46,22,0))


if __name__=='__main__':unittest.main()
