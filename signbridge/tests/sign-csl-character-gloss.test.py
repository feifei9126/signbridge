"""Character targets preserve raw Gloss identity, boundaries and split isolation."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

TOOL = Path(__file__).resolve().parents[1] / 'src/tools/sign-csl-character-gloss.py'


def module():
    spec = importlib.util.spec_from_file_location('character_gloss_test', TOOL)
    result = importlib.util.module_from_spec(spec); spec.loader.exec_module(result)
    return result


class TokenTests(unittest.TestCase):
    def test_exact_roundtrip_keeps_variants_unicode_slashes_and_spaces(self):
        m = module()
        gloss = ['考试1', '考试2', '告诉（我）', 'A/B', '手 指', '𠮷']
        encoded = m.encode_gloss(gloss)
        self.assertEqual(encoded.count(m.END), len(gloss))
        self.assertEqual(m.decode_gloss(encoded), {'gloss': gloss, 'errors': []})
        self.assertNotEqual(m.encode_gloss(['一起去']), m.encode_gloss(['一起', '去']))

    def test_vocabulary_uses_only_train_and_oov_reduction_is_not_false_zero(self):
        m = module()
        rows = [{'id':'a', 'text':'我考试', 'gloss_sequence':['考试1','考试2']}]
        vocab = m.build_vocab(rows)
        self.assertNotIn('醋', vocab['target'])
        self.assertNotIn('醋', vocab['source'])
        stats = m.representation_stats(rows, [{'id':'b','text':'我考试醋','gloss_sequence':['考试12','醋']}])
        self.assertEqual(stats['unseen_whole_gloss_types'], 2)
        self.assertEqual(stats['unseen_target_character_types'], 1)
        self.assertEqual(stats['unseen_whole_gloss_types_composable_from_train_characters'], 1)

    def test_missing_boundary_unknown_and_empty_labels_are_exposed(self):
        m = module()
        cases = [['我'], [m.END], ['我','<unk>',m.END], ['我',m.END,m.END]]
        for tokens in cases:
            result = m.decode_gloss(tokens)
            self.assertTrue(result['errors'], tokens)
            self.assertTrue(any(x.startswith(m.INVALID) for x in result['gloss']), tokens)
        self.assertEqual(m.decode_gloss(['我',m.END])['errors'], [])
        self.assertEqual(m.decode_gloss([])['gloss'], [])
        for bad in [[], [''], ['<unk>'], [m.INVALID+'x'], ['ok', None]]:
            with self.assertRaises(ValueError):
                m.encode_gloss(bad)

    def test_loader_preserves_source_and_never_opens_h_or_official_test(self):
        m = module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            for name,row in [('train',{'id':'a','source_code':'A','text':'我去','gloss_sequence':['我','去'],'video_sha256':'a'}),
                             ('selection',{'id':'g','source_code':'G','text':'你来','gloss_sequence':['你','来'],'video_sha256':'b'})]:
                (root/(name+'.jsonl')).write_text(json.dumps(row,ensure_ascii=False)+'\n')
            m.u.base.write_json(root/'report.json', {**m.u.GATES,'schema':'signbridge-gloss-source-group-v1',
                'counts':{'train':1,'selection':1,'holdout':1}})
            m.u.seal(root)
            (root/'holdout.jsonl').write_text('DO NOT OPEN')
            (root/'test.jsonl').write_text('DO NOT OPEN')
            original = Path.open
            def guarded(path,*a,**kw):
                if path.name in ['holdout.jsonl','test.jsonl']:
                    self.fail('sealed evaluation was opened')
                return original(path,*a,**kw)
            with patch.object(Path,'open',guarded):
                data,provenance = m.load_data(root)
            self.assertEqual(data['train'][0]['gloss_sequence'], ['我','去'])
            self.assertNotIn('holdout.jsonl', provenance['sha256'])
            with (root/'train.jsonl').open('a') as f: f.write(' ')
            with self.assertRaisesRegex(ValueError,'digest'):
                m.load_data(root)

    def test_prepare_rebinds_exact_baseline_and_rejects_approval_or_config_changes(self):
        m=module()
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();group=root/'group';base=root/'baseline';group.mkdir();base.mkdir()
            a={'id':'a','source_code':'A','text':'我去','gloss_sequence':['我','去'],'video_sha256':'a'}
            g={'id':'g','source_code':'G','text':'你来','gloss_sequence':['你','来'],'video_sha256':'b'}
            for name,row in [('train',a),('selection',g)]:
                (group/(name+'.jsonl')).write_text(json.dumps(row,ensure_ascii=False)+'\n')
            m.u.base.write_json(group/'report.json',{**m.u.GATES,'schema':'signbridge-gloss-source-group-v1',
                'counts':{'train':1,'selection':1,'holdout':99}})
            m.u.seal(group);data,prov=m.load_data(group)
            predictions=[{'id':'g','text':'你来','reference':['你','来'],'predicted':['你']}]
            metric=m.metrics([g],predictions)['raw_gloss']
            m.u.base.write_json(base/'report.json',{'schema':'signbridge-gloss-grouped-scratch-v1','status':'completed',
                'initialization':'fresh_random_no_prior_checkpoint','source':prov,'selected_epoch':1,'history':[{'selection':metric}],
                'config':m.CONFIG,'seed':20261105,'optimizer':'AdamW','learning_rate':.0002})
            m.u.base.write_json(base/'selected-predictions.json',predictions);m.u.seal(base)
            launch_plan=root/'gpu-prepared-v2/launch-config.json';launch_plan.parent.mkdir()
            m.u.base.write_json(launch_plan,{'epochs':30,'patience':6,'batch_size':64,'seed':20261105,
                'learning_rate':.0002,'initialization':'fresh_random_no_prior_checkpoint'})
            m.u.base.write_json(root/'launch.json',{'command':['python','sign-csl-decoding-study.py','train-grouped','--grouped','/group','--output','/results']})
            def seal_run():
                paths=[base/'report.json',launch_plan,root/'launch.json']
                (root/'EVIDENCE-SHA256SUMS').write_text(''.join(m.u.base.sha(p)+'  '+str(p.relative_to(root))+'\n' for p in paths))
            seal_run()
            out=root/'new';plan=m.prepare(group,base,out)
            self.assertFalse((out/'input/holdout.jsonl').exists())
            self.assertEqual((out/'input/train.jsonl').read_bytes(),(group/'train.jsonl').read_bytes())
            _,vocab,_,_=m.read_prepared(out)
            self.assertNotIn('你',vocab['source'])
            for bad in [dict(plan,human_approved=True),dict(plan,epochs=31),dict(plan,holdout_H_may_be_reused=True)]:
                m.u.base.write_json(out/'experiment.json',bad);m.u.seal(out)
                with self.assertRaisesRegex(ValueError,'contract'):
                    m.read_prepared(out)
            baseline_report=json.loads((base/'report.json').read_text())
            for changes in [{'config':dict(m.CONFIG,width=512)}, {'seed':0}, {'learning_rate':.1}, {'optimizer':'SGD'}]:
                m.u.base.write_json(base/'report.json',dict(baseline_report,**changes));m.u.seal(base);seal_run()
                with self.assertRaisesRegex(ValueError,'ablation'):
                    m.checked_baseline(base,data,prov)
            m.u.base.write_json(base/'report.json',baseline_report);m.u.seal(base)
            changed=json.loads(launch_plan.read_text());changed['epochs']=31
            m.u.base.write_json(launch_plan,changed);seal_run()
            with self.assertRaisesRegex(ValueError,'schedule'):
                m.checked_baseline(base,data,prov)

    def test_invalid_predictions_are_counted_not_discarded(self):
        m=module();rows=[{'id':'a','text':'我去','gloss_sequence':['我','去']}]
        pred=[{'id':'a','reference':['我','去'],'predicted':[m.INVALID+'我'],
               'representation_errors':['missing_word_boundary'],'terminated':True}]
        scores=m.metrics(rows,pred)
        self.assertEqual(scores['raw_gloss']['samples'],1)
        self.assertEqual(scores['raw_gloss']['gloss_error_rate'],1.)
        self.assertEqual(scores['malformed_rows'],1)


@unittest.skipUnless(importlib.util.find_spec('torch'), 'Existing optional PyTorch runtime required')
class TensorTests(unittest.TestCase):
    def test_longest_accepted_target_has_room_to_generate_eos(self):
        import torch
        m=module();row={'id':'a','text':'我','gloss_sequence':['我'*61]};vocab=m.build_vocab([row])
        class Toy:
            def eval(self): return self
            def encode(self,source): return torch.zeros((len(source),1,1))
            def decode(self,target,memory,padding):
                result=torch.full((len(target),target.size(1),len(vocab['target'])),-100.)
                token='我' if target.size(1)<=61 else m.END if target.size(1)==62 else '<eos>'
                result[:,-1,vocab['target'].index(token)]=100.
                return result
        pred=m.generate(Toy(),[row],vocab,'cpu')[0]
        self.assertTrue(pred['terminated'])
        self.assertEqual(pred['representation_errors'],[])
        self.assertEqual(pred['predicted'],row['gloss_sequence'])

    def test_target_tensor_uses_characters_and_explicit_boundaries(self):
        m=module()
        row={'id':'a','text':'我考试','gloss_sequence':['考试1','我']}
        vocab=m.build_vocab([row]);source,target=m.character_batch([row],vocab,'cpu')
        tokens=[vocab['target'][i] for i in target[0].tolist()]
        self.assertEqual(tokens, ['<bos>','考','试','1',m.END,'我',m.END,'<eos>'])
        self.assertEqual(source.shape[1], len(row['text'])+2)
        with self.assertRaisesRegex(ValueError,'length'):
            m.character_batch([row],vocab,'cpu',max_target=5)

    def test_cuda_unavailable_never_updates_on_cpu(self):
        import torch
        m=module()
        with patch.object(torch.cuda,'is_available',return_value=False):
            with self.assertRaisesRegex(ValueError,'CUDA'):
                m.train(Path('not-read'),Path('not-written'))


if __name__=='__main__':
    unittest.main()
