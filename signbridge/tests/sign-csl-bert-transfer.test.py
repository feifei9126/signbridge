"""Frozen pretrained encoder / character Gloss transfer contracts."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

TOOL=Path(__file__).resolve().parents[1]/'src/tools/sign-csl-bert-transfer.py'


def module():
    spec=importlib.util.spec_from_file_location('bert_transfer_test',TOOL)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


class ContractTests(unittest.TestCase):
    def test_fixed_model_and_settings(self):
        m=module()
        self.assertEqual(m.MODEL_ID,'google-bert/bert-base-chinese')
        self.assertEqual(m.REVISION,'8f23c25b06e129b6c986331a13d8d025a92cf0ea')
        self.assertEqual((m.SETTINGS['epochs'],m.SETTINGS['patience'],m.SETTINGS['batch_size']),(30,6,64))
        self.assertEqual(m.SETTINGS['learning_rate'],.0002)
        for bad in [dict(m.SETTINGS,epochs=31),dict(m.SETTINGS,freeze_encoder=False)]:
            with self.assertRaisesRegex(ValueError,'settings'):m.check_settings(bad)

    def test_only_known_unused_pretraining_heads_may_be_ignored(self):
        m=module()
        info={'missing_keys':[],'mismatched_keys':[],'error_msgs':[],
              'unexpected_keys':['bert.pooler.dense.weight','bert.pooler.dense.bias','cls.predictions.bias']}
        m.validate_loading_info(info)
        for bad in [dict(info,unexpected_keys=['bert.encoder.bad']),dict(info,missing_keys=['embeddings.word_embeddings.weight']),
                    dict(info,error_msgs=['shape error'])]:
            with self.assertRaisesRegex(ValueError,'loading'):m.validate_loading_info(bad)

    def test_copy_uses_only_verified_allowlisted_inputs_never_H_or_test(self):
        m=module()
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();source=root/'source';source.mkdir()
            for name in ['train.jsonl','selection.jsonl','report.json']:(source/name).write_text(name)
            m.u.seal(source)
            expected={'SHA256SUMS':m.u.base.sha(source/'SHA256SUMS')}
            for name in ['train.jsonl','selection.jsonl','report.json']:expected[name]=m.u.base.sha(source/name)
            (source/'holdout.jsonl').write_text('NEVER READ');(source/'test.jsonl').symlink_to(source/'holdout.jsonl')
            original=Path.open
            def guarded(path,*a,**kw):
                if path.name in ['holdout.jsonl','test.jsonl']:self.fail('Forbidden sentinel read')
                return original(path,*a,**kw)
            with patch.object(Path,'open',guarded):m.copy_verified_inputs(source,root/'output',expected)
            self.assertEqual({p.name for p in (root/'output').iterdir()},{'train.jsonl','selection.jsonl','report.json','SHA256SUMS'})
            self.assertEqual((root/'output/SHA256SUMS').read_bytes(),(source/'SHA256SUMS').read_bytes())


@unittest.skipUnless(importlib.util.find_spec('torch'),'Existing optional torch required')
class ModelTests(unittest.TestCase):
    def setUp(self):
        import torch
        self.torch=torch;torch.set_num_threads(1);torch.manual_seed(2);self.m=module()
        self.config={'width':8,'heads':2,'layers':1,'feedforward':16,'dropout':.1,'max_source':128,'max_target':64}
        self.vocab={'source':self.m.c.u.base.SPECIALS+list('我去你'),
                    'target':self.m.c.u.base.SPECIALS+[self.m.c.END,'我','去','你']}

    def encoder(self):
        torch=self.torch
        class Encoder(torch.nn.Module):
            def __init__(self):
                super().__init__();self.config=SimpleNamespace(hidden_size=12)
                self.embedding=torch.nn.Embedding(150,12,padding_idx=0);self.dropout=torch.nn.Dropout(.5)
                self.last_mask=None
            def forward(self,input_ids,attention_mask,return_dict=True):
                self.last_mask=attention_mask
                return SimpleNamespace(last_hidden_state=self.dropout(self.embedding(input_ids)))
        return Encoder()

    def test_encoder_stays_frozen_eval_with_no_grads_and_masks_are_correct(self):
        torch=self.torch;m=self.m;encoder=self.encoder();model=m.make_model(encoder,self.vocab,self.config);model.train()
        self.assertFalse(encoder.training)
        self.assertTrue(all(not p.requires_grad for p in encoder.parameters()))
        source=torch.tensor([[101,4,5,102],[101,6,102,0]])
        target=torch.tensor([[2,5,4,6,4,3],[2,7,4,3,0,0]])
        logits=model(source,target[:,:-1]);loss=torch.nn.functional.cross_entropy(logits.flatten(0,1),target[:,1:].reshape(-1),ignore_index=0)
        loss.backward()
        self.assertTrue(all(p.grad is None for p in encoder.parameters()))
        self.assertTrue(self.torch.equal(encoder.last_mask,source.ne(0)))
        for name in ['projection.weight','target.weight','output.weight']:
            self.assertGreater(float(dict(model.named_parameters())[name].grad.abs().sum()),0,name)
        state=m.trainable_state(model)
        self.assertFalse(any(name.startswith('encoder.') for name in state))
        m.load_trainable(model,state)
        bad=dict(state);bad.pop('projection.weight')
        with self.assertRaisesRegex(ValueError,'trainable'):m.load_trainable(model,bad)

    def test_wordpiece_inputs_and_character_targets_are_separate_without_truncation(self):
        m=self.m;torch=self.torch
        class Tokenizer:
            pad_token_id=0;unk_token_id=100
            def __call__(self,texts,**kwargs):
                self.kwargs=kwargs
                return {'input_ids':torch.tensor([[101,6,102,0],[101,4,5,102]])}
        tok=Tokenizer();rows=[{'text':'你','gloss_sequence':['你']},{'text':'我去','gloss_sequence':['我','去']}]
        x,y=m.batch(rows,self.vocab,tok,'cpu')
        self.assertFalse(tok.kwargs['truncation'])
        self.assertEqual(x[0].tolist(),[101,6,102,0])
        self.assertEqual([self.vocab['target'][i] for i in y[1].tolist()],['<bos>','我',m.c.END,'去',m.c.END,'<eos>'])
        class TooLong(Tokenizer):
            def __call__(self,texts,**kwargs):return {'input_ids':torch.ones((2,129),dtype=torch.long)}
        with self.assertRaisesRegex(ValueError,'length'):m.batch(rows,self.vocab,TooLong(),'cpu')

    def test_missing_eos_is_recorded_as_invalid_gloss(self):
        m=self.m;torch=self.torch
        class Tok:
            pad_token_id=0;unk_token_id=100
            def __call__(self,texts,**kwargs):return {'input_ids':torch.tensor([[101,4,102]])}
        class NeverEnd:
            def eval(self):return self
            def encode(self,source):return torch.zeros((1,3,8))
            def decode(self,target,memory,mask):
                logits=torch.full((1,target.size(1),len(self_vocab['target'])),-100.)
                logits[:,-1,5]=100.;return logits
        self_vocab=self.vocab
        row={'id':'a','text':'我','gloss_sequence':['我']}
        result=m.generate(NeverEnd(),[row],self.vocab,Tok(),'cpu')[0]
        self.assertFalse(result['terminated'])
        self.assertIn('missing_eos',result['representation_errors'])

    def test_cuda_only_training_guard(self):
        m=self.m
        with patch.object(self.torch.cuda,'is_available',return_value=False):
            with self.assertRaisesRegex(ValueError,'CUDA'):m.train(Path('absent'),Path('encoder'),Path('unused'))


if __name__=='__main__':unittest.main()
