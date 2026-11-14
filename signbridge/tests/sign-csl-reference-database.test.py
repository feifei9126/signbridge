"""Reference merge removes exact duplicates, never same-label sign variants."""
import importlib.util
from pathlib import Path
import tempfile
import json
from unittest.mock import patch
from types import SimpleNamespace
import unittest

PATH = Path(__file__).resolve().parents[1] / 'src/tools/sign-csl-reference-database.py'
SPEC = importlib.util.spec_from_file_location('reference_db_test', PATH)
m = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m)


def sample(sid, label='我', digest='a'*64, split='train', sentence=None):
    return {'id': sid, 'source_split': split, 'video': {'sha256': digest},
            'raw': {'Chinese Sentences': sentence or label, 'Gloss': label, 'Note': ''},
            'gloss_tokens': [{'kind': 'gloss', 'label': label, 'raw': label, 'position': 0}]}


def term(sid, text, kind='word'):
    return {'id': sid, 'canonical_text': text, 'unit_type': kind, 'meaning': '课内含义',
            'source_id': 'source-'+sid, 'source_sha256': 'b'*64,
            'evidence_status': 'assistant_source_audited', 'human_approved': False,
            'semantics_approved': False, 'boundaries_approved': False,
            'training_ready': False, 'model_training_ready': False}


class ReferenceDatabaseTests(unittest.TestCase):
    def test_same_gloss_different_video_is_retained(self):
        status, aliases, conflicts = m.group_samples([sample('a'), sample('b', digest='b'*64)])
        self.assertEqual(status, {'a': 'retained', 'b': 'retained'})
        self.assertEqual((aliases, conflicts), ([], []))

    def test_same_media_different_label_quarantines_all(self):
        status, aliases, conflicts = m.group_samples([sample('a', '走'), sample('b', '计划')])
        self.assertTrue(all(v == 'quarantined_label_conflict' for v in status.values()))
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(aliases, [])

    def test_same_video_exact_annotation_collapses_without_test_to_train_leak(self):
        status, aliases, conflicts = m.group_samples([sample('a'), sample('z', split='test')])
        self.assertEqual(status, {'z': 'retained', 'a': 'duplicate_alias'})
        self.assertEqual(aliases[0]['canonical_sample_id'], 'z')
        self.assertFalse(conflicts)

    def test_note_conflicts_and_chinese_difference_not_silently_lost(self):
        a, b = sample('a'), sample('b')
        b['raw']['Note'] = 'different'
        self.assertEqual(len(m.group_samples([a, b])[2]), 1)
        b['raw']['Note'] = ''
        b['raw']['Chinese Sentences'] = '我们'
        self.assertEqual(len(m.group_samples([a, b])[2]), 1)

    def test_exact_text_terms_merge_evidence_but_not_signs_or_types(self):
        terms, occurrences, mapping = m.make_terms([sample('s')], [term('a', '我'), term('b', '我'), term('c', '我', 'grammar_concept')])
        self.assertEqual(len(terms), 2)
        original = next(t for t in terms if t['in_ce_csl'])
        self.assertEqual(original['tutorial_lexical_ids'], ['a', 'b'])
        self.assertEqual(original['ce_occurrences_by_split'], {'train': 1, 'dev': 0, 'test': 0})
        self.assertFalse(any(x['same_sign_verified'] for x in mapping))
        self.assertEqual(mapping[2]['relation'], 'same_label_different_unit_type_kept_separate')
        self.assertEqual(len(occurrences), 1)

    def test_numbered_variants_and_compound_gloss_not_normalized_away(self):
        terms, _, mapping = m.make_terms([sample('a', '考试1'), sample('b', '考试2')], [term('a', '考试')])
        self.assertEqual({t['label'] for t in terms}, {'考试1', '考试2', '考试'})
        self.assertEqual(mapping[0]['relation'], 'not_in_ce_csl_exact_labels')
        self.assertNotEqual(m.identifier('tutorial-term', '家', 'word'), m.identifier('tutorial-term', '家（房子）', 'word'))

    def test_duplicate_lexical_record_and_fake_approval_rejected(self):
        with self.assertRaises(ValueError):
            m.make_terms([], [term('a', '我'), term('a', '你')])
        bad = term('a', '你')
        bad['human_approved'] = True
        with self.assertRaises(ValueError):
            m.make_terms([], [bad])

    def test_media_copy_does_not_hardlink_or_change_original(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); source = root/'original.mp4'; source.write_bytes(b'originalvideo'); out = root/'new'; out.mkdir()
            digest = m.ce.sha(source); copies = m.MediaCopies(out)
            copies.copy(source, digest, 'video/a.mp4'); copies.copy(source, digest, 'video/b.mp4')
            self.assertNotEqual(source.stat().st_ino, (out/'video/a.mp4').stat().st_ino)
            self.assertEqual((out/'video/a.mp4').stat().st_ino, (out/'video/b.mp4').stat().st_ino)
            self.assertEqual(len(copies.assets), 1)
            self.assertEqual(len(copies.aliases), 2)
            self.assertEqual(source.read_bytes(), b'originalvideo')
            with self.assertRaises(ValueError):
                copies.copy(source, 'f'*64, 'video/c.mp4')

    def test_media_path_cannot_escape_or_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); source=root/'original';source.write_bytes(b'v');out=root/'new';out.mkdir();copies=m.MediaCopies(out)
            with self.assertRaises(ValueError):copies.copy(source,m.ce.sha(source),'../escape.mp4')
            copies.copy(source,m.ce.sha(source),'a.mp4')
            with self.assertRaises(ValueError):copies.copy(source,m.ce.sha(source),'a.mp4')

    def test_known_actual_conflicting_ids_can_never_be_silently_deduplicated(self):
        a=sample('csl_ce_csl_train_03571','暂时/乱/走/不/。',sentence='暂时不要乱走。')
        b=sample('csl_ce_csl_train_03572','暂时/计划/没有/。',sentence='暂时还没别的计划。')
        status,aliases,conflicts=m.group_samples([a,b])
        self.assertEqual(len(conflicts),1);self.assertFalse(aliases)
        self.assertTrue(all(x=='quarantined_label_conflict' for x in status.values()))

    def test_revalidation_report_must_bind_current_input_snapshots(self):
        with tempfile.TemporaryDirectory() as d:
            r=Path(d); source=r/'ce'; source.mkdir(); intake=r/'intake'; intake.mkdir(); inv=r/'inv.json'; inv.write_text('{}')
            required=[inv]+[intake/n for n in ['SHA256SUMS','report.json','samples.jsonl','video-inventory.jsonl']]+[base/'label'/f'{split}.csv' for base in [source,intake] for split in m.ce.SPLITS]
            for p in required:
                p.parent.mkdir(parents=True,exist_ok=True)
                if not p.exists():p.write_text('fixture')
            check={'status':'passed','errors':[],'changes':[], 'sources':{'ce_csl_root':str(source),'candidate_library_root':str(intake),'tutorial_inventory':str(inv)},'input_snapshots':[{'path':str(p),'sha256':m.ce.sha(p)} for p in required]}
            m.validate_revalidation(check,source,intake,inv)
            inv.write_text('{"changed":true}')
            with self.assertRaises(ValueError):m.validate_revalidation(check,source,intake,inv)
            check['input_snapshots']=[]
            with self.assertRaises(ValueError):m.validate_revalidation(check,source,intake,inv)

    def test_candidate_pts_framecount_and_missing_masks_checked(self):
        import numpy as np
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'observations.npz'; values={'source_pts_seconds':np.array([1.,1.04]),'source_frame_ids_0based':np.array([25,26])}
            for name,n in [('pose_image',33),('left_hand_image',21),('right_hand_image',21),('face_image',468)]:
                v=np.zeros((2,n,3),np.float32);v[1]=np.nan;values[name]=v;values[name+'_detected']=np.array([True,False])
            np.savez(p,**values)
            result=SimpleNamespace(stdout=json.dumps({'streams':[{'nb_read_frames':'2','avg_frame_rate':'25/1'}]}))
            with patch.object(m.shutil,'which',return_value='/ffprobe'),patch.object(m.subprocess,'run',return_value=result):
                self.assertTrue(m.validate_candidate_media(Path('/clip'),p,2,25.,[1.,1.04],[25,26])['missing_preserved'])
                with self.assertRaises(ValueError):m.validate_candidate_media(Path('/clip'),p,2,25.,[1.,1.05],[25,26])
                values['left_hand_image'][1]=0;np.savez(p,**values)
                with self.assertRaises(ValueError):m.validate_candidate_media(Path('/clip'),p,2,25.,[1.,1.04],[25,26])


    def test_candidate_id_path_escape_rejected_before_output(self):
        for value in ['basic-x/../../../../approved/candidate','../outside','', 'a/b','a\\b']:
            with self.assertRaises(ValueError):m.safe_id(value)
        self.assertEqual(m.safe_id('basic-you'), 'basic-you')
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);outside=root.parent/'escape-should-never-exist'
            with self.assertRaises(ValueError):m.new_target(root,'../escape-should-never-exist')
            self.assertFalse(outside.exists())

    def test_reviewed_parameter_copy_must_match_hash_and_one_frame_shapes(self):
        import numpy as np
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'candidate.npz';shapes={'global_orient':(1,3),'body_pose':(21,3),'left_hand_pose':(15,3),'right_hand_pose':(15,3),'jaw_pose':(1,3),'leye_pose':(1,3),'reye_pose':(1,3),'betas':(1,10),'expression':(1,10),'transl':(1,3)}
            np.savez(p,**{k:np.zeros(s,dtype=np.float32) for k,s in shapes.items()});digest=m.ce.sha(p)
            self.assertEqual(m.reviewed_native(p,digest),p.read_bytes())
            np.savez(p,**{k:np.ones(s,dtype=np.float32) for k,s in shapes.items()})
            with self.assertRaises(ValueError):m.reviewed_native(p,digest)
            np.savez(p,body_pose=np.zeros((2,21,3)))
            with self.assertRaises(ValueError):m.reviewed_native(p,m.ce.sha(p))

    def fixture(self, root):
        root=root.resolve()
        import numpy as np
        source=root/'source'; intake=root/'intake'; audit=root/'audit'; obs=root/'obs'
        for r in [source,intake,audit,obs]:r.mkdir()
        for split in m.ce.SPLITS:
            p=source/'label'/f'{split}.csv';p.parent.mkdir(exist_ok=True)
            import csv
            with p.open('w',encoding='utf-8-sig',newline='') as f:
                w=csv.writer(f);w.writerow(m.HEADERS);w.writerow([split+'-00001','A','你','你/。',''])
            q=intake/'label'/f'{split}.csv';q.parent.mkdir(exist_ok=True);q.write_bytes(p.read_bytes())
            v=source/'video'/split/'A'/(split+'-00001.mp4');v.parent.mkdir(parents=True);v.write_bytes(split.encode())
        old,_,_=m.ce.read_labels(source)
        for row in old:
            p=source/row['video_relative_path'];row['video']={'status':'present','sha256':m.ce.sha(p)}
        m.write_jsonl(intake/'samples.jsonl',old);m.write_jsonl(intake/'video-inventory.jsonl',[]);m.write_json(intake/'report.json',{})
        original=root/'lesson.mp4';original.write_bytes(b'lesson');digest=m.ce.sha(original)
        lexical=term('lex','你');lexical.update(source_id='tutorial-one',source_sha256=digest,raw_aliases=['你'],evidence_status='assistant_source_audited',source_intervals=[{'start':0,'end':2,'basis':'visible_title'}])
        m.write_jsonl(audit/'lexical-entries.jsonl',[lexical])
        inv=root/'inputs/inventory.json';m.write_json(inv,{'unique_sources':[{'source_id':'tutorial-one','path':str(original),'sha256':digest,'aliases':[str(original)]}],'counts':{'exact_duplicates':0}})
        for target in [intake,audit]:(target/'SHA256SUMS').write_text(''.join(m.ce.sha(p)+'  '+str(p.relative_to(target))+'\n' for p in sorted(target.rglob('*')) if p.is_file()))
        clip=obs/'clip.mp4';clip.write_bytes(b'clip');values={'source_pts_seconds':np.array([0.,.04]),'source_frame_ids_0based':np.array([0,1])}
        for name,n in [('pose_image',33),('left_hand_image',21),('right_hand_image',21),('face_image',468)]:values[name]=np.zeros((2,n,3),np.float32);values[name+'_detected']=np.array([True,True])
        np.savez(obs/'observations.npz',**values)
        row={'id':'basic-you','text':'你','source_id':'tutorial-one','source_sha256':digest,'reference_clip':'clip.mp4','reference_sha256':m.ce.sha(clip),'observations':'observations.npz','observations_sha256':m.ce.sha(obs/'observations.npz'),'decoded_frames':2,'reference_fps':25.,'source_pts_seconds':[0.,.04],'source_frame_ids_0based':[0,1],'human_approved':False,'training_ready':False}
        m.write_jsonl(obs/'observations-records.jsonl',[row])
        shapes={'global_orient':(1,3),'body_pose':(21,3),'left_hand_pose':(15,3),'right_hand_pose':(15,3),'jaw_pose':(1,3),'leye_pose':(1,3),'reye_pose':(1,3),'betas':(1,10),'expression':(1,10),'transl':(1,3)}
        candidate=root/'approved/candidate.npz';candidate.parent.mkdir();np.savez(candidate,**{k:np.zeros(s,np.float32) for k,s in shapes.items()})
        display=root/'display/index.html';display.parent.mkdir();display.write_text('<h1>你</h1>')
        review=root/'review.json';m.write_json(review,{'statement':'我已看过，“你”现在的动作是对的','scope':{'candidate_id':'basic-you'},'human_approved':True,'training_ready':False,'boundaries_approved':False,'bound_artifacts':{str(candidate):m.ce.sha(candidate),str(display):m.ce.sha(display)}})
        required=[inv]+[intake/n for n in ['SHA256SUMS','report.json','samples.jsonl','video-inventory.jsonl']]+[base/'label'/f'{split}.csv' for base in [source,intake] for split in m.ce.SPLITS]
        validation=root/'validation.json';m.write_json(validation,{'status':'passed','errors':[],'changes':[],'sources':{'ce_csl_root':str(source),'candidate_library_root':str(intake),'tutorial_inventory':str(inv)},'input_snapshots':[{'path':str(p),'sha256':m.ce.sha(p)} for p in required]})
        return source,intake,audit,inv,obs,review,root/'output',validation

    def test_end_to_end_fixture_preserves_format_review_and_source_files(self):
        import sqlite3
        with tempfile.TemporaryDirectory() as d:
            args=self.fixture(Path(d));probe=SimpleNamespace(stdout=json.dumps({'streams':[{'nb_read_frames':'2','avg_frame_rate':'25/1'}]}))
            with patch.object(m.shutil,'which',return_value='/ffprobe'),patch.object(m.subprocess,'run',return_value=probe):report=m.build(*args)
            self.assertEqual(report['retained_ce_samples'],3)
            out=args[6];self.assertTrue((out/'reviews/displayed/index.html').exists())
            self.assertEqual((out/'provenance/original-ce-csl/label/train.csv').read_bytes(),(args[0]/'label/train.csv').read_bytes())
            c=sqlite3.connect(out/'database.sqlite');self.assertEqual(c.execute('pragma integrity_check').fetchone(),('ok',));self.assertEqual(c.execute('select count(*) from reviews').fetchone(),(1,));c.close()
            self.assertEqual((Path(d)/'approved/candidate.npz').read_bytes(),(out/'motions/basic-you-reviewed-keyframe/candidate.npz').read_bytes())

    def test_full_build_malicious_id_cannot_overwrite_reviewed_parameters(self):
        with tempfile.TemporaryDirectory() as d:
            args=self.fixture(Path(d));native=Path(d)/'approved/candidate.npz';before=native.read_bytes()
            row=json.loads((args[4]/'observations-records.jsonl').read_text());row['id']='basic-x/../../../../approved/candidate';m.write_jsonl(args[4]/'observations-records.jsonl',[row])
            with self.assertRaises(ValueError):m.build(*args)
            self.assertEqual(native.read_bytes(),before);self.assertFalse(args[6].exists())

    def test_full_build_final_validation_failure_has_no_success_report(self):
        with tempfile.TemporaryDirectory() as d:
            args=self.fixture(Path(d));real=m.validate_revalidation;calls=[]
            def last(*a):
                calls.append(1)
                if len(calls)>1:raise ValueError('injected final check failure')
                return real(*a)
            probe=SimpleNamespace(stdout=json.dumps({'streams':[{'nb_read_frames':'2','avg_frame_rate':'25/1'}]}))
            with patch.object(m,'validate_revalidation',side_effect=last),patch.object(m.shutil,'which',return_value='/ffprobe'),patch.object(m.subprocess,'run',return_value=probe):
                with self.assertRaises(ValueError):m.build(*args)
            self.assertFalse(args[6].exists());partial=list(Path(d).glob('output.partial-*'));self.assertEqual(len(partial),1);self.assertTrue((partial[0]/'BUILD-FAILED.json').exists());self.assertFalse((partial[0]/'report.json').exists())



if __name__ == '__main__':
    unittest.main()
