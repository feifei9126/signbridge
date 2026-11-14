"""Tiny train-only memorization diagnostic contracts, not translation evaluation."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

TOOL = Path(__file__).resolve().parents[1] / 'src/tools/sign-csl-tiny32.py'


def module():
    spec=importlib.util.spec_from_file_location('tiny32_test',TOOL)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    return m


class DataTests(unittest.TestCase):
    def test_selection_deterministic_disjoint_identity_and_conflicts_excluded(self):
        m=module()
        rows=[{'id':str(i),'text':'句'+str(i),'gloss_sequence':['词'+str(i)]} for i in range(36)]
        rows += [{'id':'conflict','text':'句0','gloss_sequence':['不同']}]
        a,excluded=m.choose(rows)
        b,_=m.choose(list(reversed(rows)))
        self.assertEqual(a,b)
        self.assertEqual(len(a),32)
        self.assertEqual(len({r['text'] for r in a}),32)
        self.assertNotIn('句0',{r['text'] for r in a})
        self.assertEqual(set(excluded['conflicting_text_ids']),{'0','conflict'})
        self.assertTrue(set(r['id'] for r in a)<={r['id'] for r in rows})
        with self.assertRaisesRegex(ValueError,'32'):
            m.choose(rows[:31])

    def test_prepare_only_reads_train_and_binds_frozen_samples(self):
        m=module()
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();source=root/'source';source.mkdir()
            rows=[{'id':str(i),'text':'我去'+str(i),'gloss_sequence':['去',str(i)],'source_code':'A',
                   'task':'gloss','label_source':'ce_csl_dataset','human_approved':False} for i in range(40)]
            (source/'train.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows))
            m.u.base.write_json(source/'report.json',{**m.u.GATES,'schema':'signbridge-gloss-source-group-v1','counts':{'train':40}})
            m.u.seal(source)
            for name in ['selection.jsonl','holdout.jsonl','test.jsonl']:(source/name).write_text('NEVER OPEN')
            original=Path.open
            def guarded(path,*a,**kw):
                if path.name in ['selection.jsonl','holdout.jsonl','test.jsonl']:
                    self.fail('Forbidden split opened')
                return original(path,*a,**kw)
            out=root/'prepared'
            with patch.object(Path,'open',guarded):
                plan=m.prepare(source,out)
                sample,vocab,meta=m.read_prepared(out)
            self.assertEqual(len(sample),32)
            self.assertEqual(plan['source_count'],40)
            self.assertFalse(plan['holdout_H_read'])
            self.assertEqual(meta,plan)
            with self.assertRaises(FileExistsError):m.prepare(source,out)
            (out/'samples.jsonl').write_text('tampered')
            with self.assertRaisesRegex(ValueError,'digest'):m.read_prepared(out)

    def test_teacher_forcing_alone_is_not_success(self):
        m=module()
        metric={'raw_gloss':{'samples':32,'exact_matches':30},'malformed_rows':0,'missing_eos_rows':0,'empty_prediction_rows':0}
        self.assertFalse(m.passed(metric,True))
        metric['raw_gloss']['exact_matches']=31
        self.assertTrue(m.passed(metric,True))
        self.assertFalse(m.passed(metric,False))
        for key in ['malformed_rows','missing_eos_rows','empty_prediction_rows']:
            self.assertFalse(m.passed(dict(metric,**{key:1}),True))

    def test_passing_checkpoint_always_outranks_lower_ger_malformed_checkpoint(self):
        m=module()
        malformed={'raw_gloss':{'samples':32,'exact_matches':31,'gloss_error_rate':.05},
                   'malformed_rows':1,'missing_eos_rows':0,'empty_prediction_rows':0}
        passing={'raw_gloss':{'samples':32,'exact_matches':31,'gloss_error_rate':.10},
                 'malformed_rows':0,'missing_eos_rows':0,'empty_prediction_rows':0}
        self.assertGreater(m.checkpoint_key(passing,True),m.checkpoint_key(malformed,True))

    def test_31_exact_plus_one_eos_only_cannot_pass(self):
        m=module()
        metric={'raw_gloss':{'samples':32,'exact_matches':31,'gloss_error_rate':.03},
                'malformed_rows':0,'missing_eos_rows':0,'empty_prediction_rows':1}
        self.assertFalse(m.passed(metric,True))

    def test_frozen_limits_are_enforced(self):
        m=module()
        self.assertEqual(m.SETTINGS['max_steps'],1000)
        self.assertEqual(m.SETTINGS['evaluate_every'],25)
        self.assertEqual(m.SETTINGS['sample_count'],32)
        for changes in [{'max_steps':1001},{'sample_count':33},{'learning_rate':.01}]:
            with self.assertRaisesRegex(ValueError,'settings'):m.check_settings(dict(m.SETTINGS,**changes))


@unittest.skipUnless(importlib.util.find_spec('torch'),'Existing optional torch required')
class TensorTests(unittest.TestCase):
    def test_teacher_forced_accuracy_excludes_pad_and_counts_eos(self):
        import torch
        m=module();target=torch.tensor([[2,4,3,0],[2,5,4,3]])
        logits=torch.zeros((2,3,6));pred=torch.tensor([[4,3,5],[5,5,3]])
        logits.scatter_(2,pred[:,:,None],10.)
        metric=m.forced_stats(logits,target)
        self.assertEqual(metric['tokens'],5)
        self.assertEqual(metric['correct_tokens'],4)
        self.assertEqual(metric['exact_sequences'],1)

    def test_cuda_only_training(self):
        import torch
        m=module()
        with patch.object(torch.cuda,'is_available',return_value=False):
            with self.assertRaisesRegex(ValueError,'CUDA'):m.train(Path('absent'),Path('unused'))


if __name__=='__main__':unittest.main()
