"""Decode study and train-only source grouping contracts."""
import importlib.util
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

TOOL = Path(__file__).resolve().parents[1] / 'src/tools/sign-csl-decoding-study.py'


def module():
    spec = importlib.util.spec_from_file_location('decode_study_test', TOOL)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m


class SplitTests(unittest.TestCase):
    def test_cross_group_text_gloss_and_video_collisions_are_quarantined(self):
        m = module()
        def row(id, code, text, gloss, video):
            return {'id': id, 'source_code': code, 'text': text, 'gloss_sequence': gloss, 'video_sha256': video}
        rows = [row('a', 'A', '我去', ['我','去'], 'v1'), row('g', 'G', '我去', ['你','来'], 'v2'),
                row('b', 'B', '你看', ['好'], 'v3'), row('h', 'H', '她说', ['好'], 'v4'),
                row('c', 'C', '我喝', ['喝'], 'v5'), row('h2', 'H', '你买', ['买'], 'v5'),
                row('d', 'D', '你去', ['你','去'], 'v6'), row('g2', 'G', '我看', ['我','看'], 'v7'),
                row('h3', 'H', '她买', ['她','买'], 'v8')]
        split, quarantined = m.group_partition(rows)
        self.assertEqual({x['id'] for x in quarantined}, {'a','g','b','h','c','h2'})
        self.assertEqual([x['id'] for x in split['train']], ['d'])
        self.assertEqual([x['id'] for x in split['selection']], ['g2'])
        self.assertEqual([x['id'] for x in split['holdout']], ['h3'])
        self.assertEqual(len(rows), sum(len(x) for x in split.values()) + len(quarantined))

    def test_invalid_or_duplicate_source_ids_are_rejected(self):
        m = module()
        row = {'id':'a', 'source_code':'A', 'text':'我去', 'gloss_sequence':['去'], 'video_sha256':'v'}
        with self.assertRaises(ValueError):
            m.group_partition([row, row])
        with self.assertRaises(ValueError):
            m.group_partition([{**row, 'source_code':'?'}])

    def test_digit_template_collision_and_near_duplicate_reported(self):
        m=module()
        parts={'train':[{'id':'a','text':'我买了2023本书'}],
               'selection':[{'id':'b','text':'我买了2024本书'}],
               'holdout':[{'id':'c','text':'我买了2025本书'}]}
        report=m.similarity_audit(parts)
        self.assertEqual(len(report['same_digit_shape_cross_split_groups']),1)
        self.assertEqual(len(report['prefix3_similarity_ge_088_pairs']),3)

    def test_training_loader_never_opens_holdout_and_detects_tamper(self):
        m = module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            train = {'id':'a', 'source_code':'A', 'text':'我去', 'gloss_sequence':['我','去'], 'video_sha256':'v1'}
            dev = {'id':'g', 'source_code':'G', 'text':'你来', 'gloss_sequence':['你','来'], 'video_sha256':'v2'}
            for name,row in [('train',train),('selection',dev)]:
                (root/(name+'.jsonl')).write_text(json.dumps(row,ensure_ascii=False)+'\n')
            (root/'holdout.jsonl').write_text('NEVER READ')
            m.u.base.write_json(root/'report.json', {**m.GATES, 'schema':'signbridge-gloss-source-group-v1',
                'counts':{'train':1,'selection':1,'holdout':1}, 'signer_identity_verified':False})
            m.write_sealed(root)
            original_bytes,original_text=Path.read_bytes,Path.read_text
            def safe_bytes(path,*a,**kw):
                if path.name == 'holdout.jsonl': self.fail('holdout bytes opened')
                return original_bytes(path,*a,**kw)
            def safe_text(path,*a,**kw):
                if path.name == 'holdout.jsonl': self.fail('holdout text opened')
                return original_text(path,*a,**kw)
            with patch.object(Path,'read_bytes',safe_bytes), patch.object(Path,'read_text',safe_text):
                data,_=m.read_grouped_training(root)
            self.assertEqual(data['train'][0]['id'],'a')
            (root/'selection.jsonl').write_text('tampered')
            with self.assertRaisesRegex(ValueError,'digest'):
                m.read_grouped_training(root)


@unittest.skipUnless(importlib.util.find_spec('torch'), 'Optional torch required')
class BeamTests(unittest.TestCase):
    def test_width_one_exactly_matches_existing_greedy_with_padding(self):
        import torch
        m = module(); torch.manual_seed(31)
        config = {'width':8, 'heads':2, 'layers':1, 'feedforward':16, 'dropout':0., 'max_source':16, 'max_target':16}
        vocab = {'source':m.u.base.SPECIALS + list('我去你'), 'target':m.u.base.SPECIALS + ['我','去','你']}
        model = m.u.base.make_model(vocab, config)
        source = torch.tensor([[2,4,5,3],[2,6,3,0]])
        expected = m.u.base.greedy_decode(model, source, vocab, max_length=8)
        actual = m.beam_candidates(model, source, vocab, width=1, max_length=8)
        self.assertEqual(expected, m.select_beams(actual, vocab, alpha=0.))

    def test_wide_beam_finds_better_complete_sequence_than_greedy(self):
        import torch
        m=module()
        class Toy:
            def eval(self): return self
            def encode(self,source): return torch.zeros((len(source),1,1))
            def decode(self,target,memory,padding):
                result=torch.full((len(target),target.size(1),6),-100.)
                for i,row in enumerate(target.tolist()):
                    if len(row)==1: result[i,-1,4]=math.log(.6);result[i,-1,5]=math.log(.4)
                    elif row[-1]==4: result[i,-1,3]=math.log(.51);result[i,-1,5]=math.log(.49)
                    else: result[i,-1,3]=math.log(.99);result[i,-1,4]=math.log(.01)
                return result
        vocab={'target':['<pad>','<unk>','<bos>','<eos>','A','B']};source=torch.tensor([[2,3]])
        self.assertEqual(m.select_beams(m.beam_candidates(Toy(),source,vocab,1,2),vocab,0.),[['A']])
        self.assertEqual(m.select_beams(m.beam_candidates(Toy(),source,vocab,2,2),vocab,0.),[['B']])

    def test_length_normalization_and_eos_handling(self):
        m = module()
        vocab = {'target': ['<pad>', '<unk>', '<bos>', '<eos>', '我', '去']}
        candidates = [[{'tokens':[4,3,3], 'score':-2.0, 'length':2}, {'tokens':[4,5,3], 'score':-2.1, 'length':3}]]
        self.assertEqual(m.select_beams(candidates, vocab, 0.), [['我']])
        self.assertEqual(m.select_beams(candidates, vocab, 1.), [['我','去']])

    def test_cuda_grouped_training_never_silently_falls_back_to_cpu(self):
        import torch
        m=module()
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();group=root/'group';group.mkdir()
            for name,row in [('train',{'id':'a','source_code':'A','text':'我去','gloss_sequence':['去'],'video_sha256':'a'}),
                             ('selection',{'id':'g','source_code':'G','text':'你来','gloss_sequence':['来'],'video_sha256':'b'})]:
                (group/(name+'.jsonl')).write_text(json.dumps(row,ensure_ascii=False)+'\n')
            m.u.base.write_json(group/'report.json',{**m.GATES,'schema':'signbridge-gloss-source-group-v1',
                'counts':{'train':1,'selection':1},'signer_identity_verified':False})
            m.write_sealed(group)
            with patch.object(torch.cuda,'is_available',return_value=False):
                with self.assertRaisesRegex(ValueError,'CUDA'):
                    m.train_grouped(group,root/'results',epochs=1)
            self.assertFalse((root/'results').exists())


if __name__ == '__main__':
    unittest.main()
