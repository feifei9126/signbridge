"""New-source OCR candidates retain missing verification and conservative source grouping."""
import importlib.util, unittest
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from PIL import Image

SCRIPT=Path(__file__).resolve().parents[1]/'src/tools/sign-source-candidates.py'

class SourceCandidateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec=importlib.util.spec_from_file_location('source_candidates',SCRIPT)
        cls.c=importlib.util.module_from_spec(spec);spec.loader.exec_module(cls.c)

    def test_caption_sampling_preserves_word_and_sentence_sections_as_different_candidates(self):
        rows=[{'source_seconds':20.,'lines':[{'text':'词学习'},{'text':'学校'}]},
              {'source_seconds':220.,'lines':[{'text':'单人演示-A'},{'text':'你在哪儿上学？'}]},
              {'source_seconds':222.,'lines':[{'text':'单人演示-A'},{'text':'你在哪儿上学？'}]},
              {'source_seconds':224.,'lines':[{'text':'单人演示-A'},{'text':'你学习什么专业？'}]}]
        spans=self.c.caption_spans(rows,source_duration=300.,sampling_interval=2.)
        self.assertEqual(len(spans),3)
        self.assertEqual(spans[0]['section'],'vocabulary_or_instruction')
        self.assertEqual(spans[1]['section'],'single_person_demo')
        self.assertEqual(spans[1]['text_candidate'],'你在哪儿上学？')
        self.assertFalse(spans[1]['semantics_approved'])
        self.assertEqual(spans[1]['observed_times'],[220.,222.])

    def test_missing_caption_or_camera_section_breaks_spans_not_interpolated(self):
        rows=[{'source_seconds':10.,'lines':[{'text':'单人演示-A'},{'text':'你好。'}]},
              {'source_seconds':12.,'lines':[]},
              {'source_seconds':14.,'lines':[{'text':'单人演示-A'},{'text':'你好。'}]},
              {'source_seconds':16.,'lines':[{'text':'对话示范'},{'text':'你好。'}]}]
        spans=self.c.caption_spans(rows,source_duration=30.,sampling_interval=2.)
        self.assertEqual(len(spans),3)
        self.assertEqual(spans[2]['section'],'dialogue_or_other')
        self.assertTrue(all(s['end_seconds']<=30. for s in spans))

    def test_positioned_ocr_uses_bottom_caption_and_does_not_join_top_logo_or_chapter_title(self):
        section,text=self.c.section_and_text([
            {'text':'单人演示-A','bounding_box':[.01,.86,.22,.08]},
            {'text':'课程附加标题','bounding_box':[.35,.75,.3,.1]},
            {'text':'你们有问题','bounding_box':[.25,.14,.4,.05]},
            {'text':'可以互相帮助。','bounding_box':[.25,.07,.4,.05]}])
        self.assertEqual(section,'single_person_demo')
        self.assertEqual(text,'你们有问题可以互相帮助。')

    def test_sparse_caption_timelines_reject_nonfinite_or_unordered_samples(self):
        for times in ((2.,2.),(4.,2.),(-1.,2.),(2.,float('nan'))):
            rows=[{'source_seconds':t,'lines':[{'text':'你好'}]} for t in times]
            with self.subTest(times=times),self.assertRaises(ValueError):
                self.c.caption_spans(rows,30.,2.)
        for duration,interval in ((float('inf'),2.),(30.,float('nan'))):
            with self.subTest(duration=duration),self.assertRaises(ValueError):
                self.c.caption_spans([],duration,interval)

    def test_same_text_on_two_sources_is_a_review_link_not_semantic_duplicate_truth(self):
        rows=[{'segment_id':'one','source_id':'s1','text_candidate':'你好！'},
              {'segment_id':'two','source_id':'s2','text_candidate':'你好。'},
              {'segment_id':'three','source_id':'s3','text_candidate':'吃饭了。'}]
        links=self.c.text_overlap_links(rows)
        self.assertEqual(len(links),1)
        self.assertEqual(links[0]['segments'],['one','two'])
        self.assertFalse(links[0]['signing_content_duplicate_confirmed'])

    def test_source_group_is_conservative_without_person_identity_or_test_assignment(self):
        source={'relative_path':'1/第二课 学习《中国手语教程》.mp4','source_id':'s1'}
        r=self.c.candidate_record(source,'candidate1',{'text_candidate':'学校','start_seconds':10.,
             'end_seconds':12.,'section':'single_person_demo','observed_times':[10.]})
        self.assertEqual(r['signer_id'],'unconfirmed-s1')
        self.assertEqual(r['split_group'],'unverified-textbook-family')
        self.assertEqual(r['split'],'unassigned')
        self.assertEqual(r['text_verified'],'')
        self.assertFalse(r['model_training_ready'])
        self.assertFalse(r['independent_source_approved'])

    def test_normalization_does_not_merge_distinct_questions_or_coerce_words_to_sentences(self):
        self.assertNotEqual(self.c.normalized_text('你好吗？'),self.c.normalized_text('你去哪？'))
        row=self.c.candidate_record({'relative_path':'2/tutorial.mp4','source_id':'s2'},'x',
            {'text_candidate':'谢谢','start_seconds':1.,'end_seconds':2.,'section':'vocabulary_or_instruction','observed_times':[1.]})
        self.assertEqual(row['sample_type'],'word_or_instruction_unconfirmed')
        self.assertEqual(row['semantics_status'],'needs_review')

    def test_initial_clip_selection_balances_sources_and_keeps_verified_text_empty(self):
        sources=[{'source_id':'s1','relative_path':'1/course.mp4'},{'source_id':'s2','relative_path':'1/course2.mp4'}]
        rows=[]
        for source in sources:
            for i,text in enumerate(('你好朋友。','你做什么工作？','你在哪里上学？')):
                rows.append(self.c.candidate_record(source,source['source_id']+str(i),
                    {'section':'single_person_demo','text_candidate':text,'start_seconds':10.+i*10,
                     'end_seconds':16.+i*10,'observed_times':[11.+i*10,13.+i*10,15.+i*10]}))
        selected=self.c.select_initial_candidates(rows,per_source=2)
        self.assertEqual(len(selected),4)
        self.assertEqual({r['source_id'] for r in selected},{'s1','s2'})
        self.assertTrue(all(r['text_verified']=='' for r in selected))
        self.assertTrue(all(r['split']=='unassigned' for r in selected))
        self.assertTrue(all(r['model_training_ready'] is False for r in selected))

    def test_two_person_and_sparse_or_overlapping_spans_cannot_enter_sentence_clip_batch(self):
        source={'source_id':'s1','relative_path':'1/course.mp4'}
        def candidate(identity,start,end,section,times):
            return self.c.candidate_record(source,identity,{'section':section,'text_candidate':'你喜欢什么运动？',
                'start_seconds':start,'end_seconds':end,'observed_times':times})
        rows=[candidate('dialogue',1,7,'dialogue_or_other',[2,4,6]),
              candidate('sparse',10,12,'single_person_demo',[11]),
              candidate('good',20,26,'single_person_demo',[21,23,25]),
              candidate('overlap',22,28,'single_person_demo',[23,25,27])]
        selected=self.c.select_initial_candidates(rows,per_source=3)
        self.assertEqual([r['segment_id'] for r in selected],['good'])

    def test_incomplete_caption_continuation_is_not_selected_as_an_initial_sentence(self):
        source={'source_id':'s1','relative_path':'1/course.mp4'}
        row=self.c.candidate_record(source,'continuation',{'section':'single_person_demo',
            'text_candidate':'我经常跟爸爸学习画画，','start_seconds':10.,'end_seconds':18.,
            'observed_times':[11.,13.,15.,17.]})
        self.assertEqual(self.c.select_initial_candidates([row]),[])

    def test_source_inventory_paths_do_not_escape_or_import_without_authorization(self):
        import tempfile,hashlib
        from pathlib import Path
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)/'videos';root.mkdir();file=root/'example.mp4';file.write_bytes(b'example')
            record={'relative_path':'example.mp4','authorization_status':'user_reported',
                    'sha256':hashlib.sha256(b'example').hexdigest()}
            self.assertEqual(self.c.source_file({'source_root':str(root)},record),file.resolve())
            for change in ({'relative_path':'../outside.mp4'},{'authorization_status':'unknown'},{'sha256':'0'*64}):
                with self.subTest(change=change),self.assertRaises(ValueError):
                    self.c.source_file({'source_root':str(root)},{**record,**change})

    def test_unsafe_source_ids_cannot_create_directories_outside_screening_output(self):
        for identity in ('../outside','/absolute','source/a','source\\a',''):
            with self.subTest(identity=identity),self.assertRaises(ValueError):
                self.c.safe_id(identity)
        self.assertEqual(self.c.safe_id('source-1234abcd'),'source-1234abcd')

    def test_quality_flags_report_presence_without_claiming_accuracy_or_approval(self):
        row={'frames':100,'hand_detection_frames':{'left_hand_image':10,'right_hand_image':70},
             'text_verified':'','model_training_ready':False,'label_ready':False,'semantics_status':'needs_review',
             'boundaries_status':'needs_review','mirror_status':'unknown','split':'unassigned'}
        quality={'detections':{'pose_image':{'detected_frames':95},'face_image':{'detected_frames':95}}}
        report=self.c.quality_review_row(row,quality)
        self.assertIn('left_hand_low_observation_coverage',report['review_flags'])
        self.assertFalse(report['sign_accuracy_evaluated'])
        self.assertFalse(report['training_ready'])
        with self.assertRaises(ValueError):self.c.quality_review_row({**row,'text_verified':'人工真值'},quality)

    def test_textbook_group_proposal_links_existing_courses_without_changing_their_split(self):
        sources=[{'source_id':'old','relative_path':'1/第一课.mp4'},{'source_id':'new','relative_path':'1/第二课.mp4'},
                 {'source_id':'tutorial','relative_path':'2/其他教程.mp4'}]
        existing=[{'segment_id':'existing','source_id':'old','split_group':'old-course','split':'unassigned'}]
        result=self.c.group_proposal(sources,existing)
        group=next(x for x in result['proposed_groups'] if x['group_id']=='unverified-textbook-family')
        self.assertEqual(group['source_ids'],['old','new'])
        self.assertFalse(result['production_splits_modified'])
        self.assertFalse(result['actual_person_disjointness_verified'])
        self.assertEqual(existing[0]['split_group'],'old-course')


class SourceReviewIntegrationTests(unittest.TestCase):
    def setUp(self):
        spec=importlib.util.spec_from_file_location('source_candidate_review',SCRIPT)
        self.c=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.c)
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve();self.videos=self.root/'videos';self.videos.mkdir()
        self.screen=self.root/'screen';self.screen.mkdir()
        self.manifest=self.root/'sources.json';self.exposed=self.root/'tasks.jsonl';self.exposed.write_text('')
        sources=[];screen_records=[]
        self.prepared=self.root/'prepared';self.tutorials=self.root/'tutorials'
        for sid,relative,folder,kind in (('s1','1/course.mp4',self.prepared,'sentence'),('s2','2/tutorial.mp4',self.tutorials,'word')):
            file=self.videos/relative;file.parent.mkdir(parents=True,exist_ok=True);file.write_bytes(('source-'+sid).encode())
            sources.append({'source_id':sid,'relative_path':relative,'sha256':self.c.sha(file),
                            'authorization_status':'user_reported','duration_seconds':20.})
            s=self.screen/sid/'frames';s.mkdir(parents=True)
            image=s/'000001.jpg';Image.new('RGB',(160,90),'white').save(image)
            (s.parent/'ocr.jsonl').write_text(json.dumps({'image':sid+'/frames/000001.jpg',
                                                       'image_sha256':self.c.sha(image)})+'\n')
            screen_records.append({'source_id':sid,'source_sha256':self.c.sha(file),'screening_images':1,
                                   'caption_spans':1,'single_person_demo_caption_spans':int(kind=='sentence')})
            folder.mkdir();sample=folder/'samples'/('sample-'+sid);sample.mkdir(parents=True)
            for name in ('clip.mp4','overlay.mp4'):(sample/name).write_bytes(b'synthetic-media-artifact')
            arrays={}
            for name,shape in (('pose_image',(33,4)),('pose_world',(33,4)),('left_hand_image',(21,3)),
                               ('right_hand_image',(21,3)),('face_image',(468,3))):
                mask=np.asarray([True,False]) if name=='left_hand_image' else np.asarray([True,True])
                values=np.zeros((2,)+shape,dtype=np.float32);values[~mask]=np.nan
                arrays[name]=values;arrays[name+'_detected']=mask
            arrays.update(timestamps_seconds=np.asarray([0.,.04]),source_timestamps_seconds=np.asarray([5.,5.04]))
            np.savez_compressed(sample/'landmarks.npz',**arrays)
            quality={'frames':2,'detections':{name:{'detected_frames':int(arrays[name+'_detected'].sum())}
                for name in ('pose_image','pose_world','left_hand_image','right_hand_image','face_image')}}
            (sample/'quality.json').write_text(json.dumps(quality))
            row={'segment_id':'sample-'+sid,'source_id':sid,'source_sha256':self.c.sha(file),
                 'start_seconds':5.,'end_seconds':5.08,'text_candidate':'你好','text_verified':'',
                 'frames':2,'fps':25.,'signer_id':'unconfirmed-'+sid,'split_group':self.c.conservative_group(sources[-1]),
                 'split':'unassigned','mirror_status':'unknown','semantics_status':'needs_review','boundaries_status':'needs_review',
                 'sample_type':kind,'language':'zh-CSL','reviewer':'','authorization_status':'user_reported',
                 'label_ready':False,'model_training_ready':False,
                 'hand_detection_frames':{'left_hand_image':1,'right_hand_image':2},
                 'artifacts':{n:'samples/sample-'+sid+'/'+n for n in ('clip.mp4','overlay.mp4','landmarks.npz','quality.json')}}
            (folder/'prepared.jsonl').write_text(json.dumps(row)+'\n')
            (folder/'verification.json').write_text(json.dumps({'checked_samples':1,'total_frames':2,'results':[
                {'segment_id':row['segment_id'],'frames':2,'decode_shape_and_mask':'passed',
                 'model_training_ready':False,'hand_detected_frames':row['hand_detection_frames']}]}))
        self.manifest.write_text(json.dumps({'source_root':str(self.videos),'sources':sources}))
        (self.screen/'screen.json').write_text(json.dumps({'status':'screened_new_sources_pending_candidate_review',
            'source_manifest_sha256':self.c.sha(self.manifest),'exposed_tasks_sha256':self.c.sha(self.exposed),
            'ocr_tool_sha256':self.c.sha(SCRIPT.with_name('sign-text-ocr.swift')),'sources':screen_records}))
        self.args=SimpleNamespace(manifest=self.manifest,screen=self.screen,prepared=self.prepared,tutorials=self.tutorials,
                                  exposed_tasks=self.exposed,output=self.root/'review')

    def test_complete_review_references_media_preserves_unverified_labels_and_source_hashes(self):
        before={p:self.c.sha(p) for root in (self.videos,self.screen,self.prepared,self.tutorials)
                for p in root.rglob('*') if p.is_file()}
        path=self.c.build_review(self.args);r=json.loads(path.read_text())
        self.assertEqual(r['prepared_sentence_candidates'],1);self.assertEqual(r['prepared_instruction_candidates'],1)
        self.assertEqual(r['prepared_frames'],4);self.assertEqual(r['new_verified_sign_labels'],0)
        self.assertFalse(r['training_ready']);self.assertEqual({p:self.c.sha(p) for p in before},before)
        page=(path.parent/'review.html').read_text()
        self.assertIn('prepared/samples/sample-s1/clip.mp4',page)
        self.assertTrue((path.parent/'annotation-review.csv').exists())
        for line in (path.parent/'SHA256SUMS').read_text().splitlines():
            digest,relative=line.split('  ',1);self.assertEqual(digest,self.c.sha(path.parent/relative))

    def test_existing_output_and_false_semantic_approval_are_rejected(self):
        self.args.output.mkdir();marker=self.args.output/'keep';marker.write_text('keep')
        with self.assertRaisesRegex(ValueError,'separate'):self.c.build_review(self.args)
        self.assertEqual(marker.read_text(),'keep');self.args.output=self.root/'new-review'
        p=self.prepared/'prepared.jsonl';row=json.loads(p.read_text());row['text_verified']='approved without review'
        p.write_text(json.dumps(row)+'\n')
        with self.assertRaisesRegex(ValueError,'unverified'):self.c.build_review(self.args)
        self.assertFalse(self.args.output.exists())

    def test_changed_source_or_mismatched_masks_cannot_be_silently_accepted(self):
        self.videos.joinpath('1/course.mp4').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'digest'):self.c.build_review(self.args)
        self.videos.joinpath('1/course.mp4').write_bytes(b'source-s1')
        p=self.prepared/'samples/sample-s1/landmarks.npz'
        with np.load(p,allow_pickle=False) as a:arrays={k:a[k].copy() for k in a.files}
        arrays['left_hand_image_detected'][1]=True;np.savez_compressed(p,**arrays)
        with self.assertRaisesRegex(ValueError,'mask'):self.c.build_review(self.args)
        self.assertFalse(self.args.output.exists())

    def test_failed_video_audit_or_unlisted_frame_identity_cannot_gain_reviewed_status(self):
        path=self.prepared/'verification.json';value=json.loads(path.read_text())
        value['results'][0]['decode_shape_and_mask']='failed'
        path.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError,'verification not passed'):
            self.c.build_review(self.args)
        self.assertFalse(self.args.output.exists())
        value['results'][0]['decode_shape_and_mask']='passed'
        value['results'][0]['segment_id']='different-frame-identity'
        path.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError,'identities differ'):
            self.c.build_review(self.args)
        self.assertFalse(self.args.output.exists())

if __name__=='__main__':unittest.main()
