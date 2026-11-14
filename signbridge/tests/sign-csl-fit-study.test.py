"""Full training fit measurement and one-learning-rate research contracts."""
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

TOOL=Path(__file__).resolve().parents[1]/'src/tools/sign-csl-fit-study.py'


def module():
    spec=importlib.util.spec_from_file_location('fit_study_test',TOOL)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


class ContractTests(unittest.TestCase):
    def test_control_has_exact_old_budget_and_one_learning_rate_change(self):
        m=module();control=m.control_settings({'epochs_completed':15,'optimizer_steps':1035,'plan':{'settings':m.t.SETTINGS}},4368)
        self.assertEqual(control['learning_rate'],.001)
        self.assertEqual(control['epochs'],15)
        self.assertEqual(control['expected_steps'],1035)
        self.assertEqual(control['batch_size'],64)
        for bad in [{'epochs_completed':14,'optimizer_steps':1035,'plan':{'settings':m.t.SETTINGS}},
                    {'epochs_completed':15,'optimizer_steps':1034,'plan':{'settings':m.t.SETTINGS}},
                    {'epochs_completed':15,'optimizer_steps':1035,'plan':{'settings':dict(m.t.SETTINGS,seed=0)}}]:
            with self.assertRaisesRegex(ValueError,'baseline'):m.control_settings(bad,4368)

    def test_prediction_forgery_and_duplicates_rejected(self):
        m=module();rows=[{'id':'a','text':'我','gloss_sequence':['我']}]
        good={'id':'a','text':'我','reference':['我'],'predicted':['我'],'terminated':True,'representation_errors':[]}
        m.verify_predictions(rows,[good])
        for bad in [[],[dict(good,id='b')],[dict(good,text='你')],[dict(good,reference=['你'])],[good,good]]:
            with self.assertRaisesRegex(ValueError,'prediction'):m.verify_predictions(rows,bad)

    def test_groups_keep_unknown_and_rare_examples_visible(self):
        m=module();train=[{'id':'a','text':'我去','gloss_sequence':['我','去']},
                         {'id':'b','text':'你去','gloss_sequence':['你','去']}]
        rows=[{'id':'c','text':'我不去','gloss_sequence':['我','不','去']},
              {'id':'d','text':'你来','gloss_sequence':['你','来']}]
        groups=m.slices(train,rows)
        self.assertEqual(groups['all'],[0,1]);self.assertEqual(groups['negation'],[0])
        self.assertEqual(groups['person'],[0,1]);self.assertEqual(groups['unknown_target_character'],[0,1])
        self.assertEqual(groups['rare_train_label'],[0,1])

    def test_lower_total_error_cannot_hide_more_deletions_or_invalid_output(self):
        m=module()
        old={'raw_gloss':{'gloss_error_rate':.7,'deletions':10},'slices':{'person':{'gloss_error_rate':.6},'negation':{'gloss_error_rate':.5}},
             'malformed_rows':0,'empty_prediction_rows':0,'missing_eos_rows':0}
        new={**old,'raw_gloss':{'gloss_error_rate':.65,'deletions':11}}
        gates=m.adoption_gates(new,old)
        self.assertTrue(gates['overall_no_regression']);self.assertFalse(gates['deletions_no_regression'])
        for name in ['malformed_rows','empty_prediction_rows','missing_eos_rows']:
            self.assertFalse(m.adoption_gates(dict(old,**{name:1}),old)['outputs_valid'])

    def test_lr_ablation_enforces_every_shared_source_hash(self):
        m=module();hashes=m.source_hashes(False)
        self.assertEqual(len(hashes),6);m.enforce_shared_sources(hashes)
        for bad in [{},dict(hashes,**{'sign-csl-bert-transfer.py':'0'*64})]:
            with self.assertRaisesRegex(ValueError,'source hashes'):m.enforce_shared_sources(bad)


@unittest.skipUnless(importlib.util.find_spec('torch'),'Existing optional torch required')
class TensorTests(unittest.TestCase):
    def test_forced_counts_include_eos_but_not_pad(self):
        import torch
        m=module();target=torch.tensor([[2,4,3,0],[2,5,4,3]])
        logits=torch.zeros((2,3,6));logits.scatter_(2,torch.tensor([[[4],[3],[5]],[[5],[5],[3]]]),10.)
        sums=m.forced_counts(logits,target)
        self.assertEqual(sums['tokens'],5);self.assertEqual(sums['correct_tokens'],4);self.assertEqual(sums['exact_sequences'],1)

    def test_train_refuses_cpu(self):
        import torch
        m=module()
        with patch.object(torch.cuda,'is_available',return_value=False):
            with self.assertRaisesRegex(ValueError,'CUDA'):m.train(Path('not-read'),Path('encoder'),Path('unused'))


if __name__=='__main__':unittest.main()
