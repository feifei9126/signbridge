"""Sparse OCR text remains unapproved and is grouped independently per caption."""
import importlib.util
from pathlib import Path
import unittest
SCRIPT=Path(__file__).resolve().parents[1]/'src/tools/sign-caption-candidates.py'
spec=importlib.util.spec_from_file_location('caption_candidates',SCRIPT)
module=importlib.util.module_from_spec(spec)
if SCRIPT.exists():spec.loader.exec_module(module)


def line(text,y=.12,x=.2,confidence=1.):
    return {'text':text,'confidence':confidence,'bounding_box':[x,y,.2,.04]}

def observation(seconds,texts):
    return {'source_seconds':seconds,'image':f'frames/{seconds}.jpg','image_sha256':'a'*64,
            'lines':[line(text) for text in texts]}


class CaptionTests(unittest.TestCase):
    def test_parallel_captions_do_not_fragment_each_other(self):
        groups=module.caption_groups([observation(0,['你好','谢谢']),observation(2,['你好','谢谢'])],10,2)
        self.assertEqual(len(groups),2)
        self.assertTrue(all(len(g['evidence'])==2 for g in groups))

    def test_missing_caption_breaks_a_run(self):
        groups=module.caption_groups([observation(0,['你好']),observation(2,[]),observation(4,['你好'])],10,2)
        self.assertEqual(len(groups),2)

    def test_title_and_hand_instruction_are_not_labels(self):
        self.assertIsNone(module.parse_line(line('国家通用手语')))
        self.assertIsNone(module.parse_line(line('伸出右手食指')))
        self.assertIsNotNone(module.parse_line(line('你好')))

    def test_right_panel_caption_has_separate_explicit_rule(self):
        item=module.parse_line(line('谢谢',y=.65,x=.65))
        self.assertEqual(item['rule'],'right_panel_caption_candidate')

    def test_left_vocabulary_panel_is_retained(self):
        item=module.parse_line(line('感动',y=.5,x=.15))
        self.assertIsNotNone(item)
        self.assertEqual(item['rule'],'left_panel_caption_candidate')

    def test_timeline_must_be_ordered_and_in_range(self):
        with self.assertRaises(ValueError):
            module.caption_groups([observation(2,['你好']),observation(0,['你好'])],10,2)

    def test_candidate_is_never_automatically_approved(self):
        group=module.caption_groups([observation(0,['你好']),observation(2,['你好'])],10,2)[0]
        row=module.candidate_record({'source_id':'source-a','sha256':'b'*64,'relative_path':'a.mp4'},group,1,10,2)
        self.assertFalse(row['human_approved'])
        self.assertFalse(row['training_ready'])
        self.assertEqual(row['text_verified'],'')
        self.assertEqual(row['language'],'unconfirmed')
        self.assertEqual(row['mirror_status'],'unknown')

    def test_upper_explicit_sign_caption_keeps_low_confidence_for_review_only(self):
        marker={'text':'手语：你好，欢迎（来）','confidence':.3,'bounding_box':[.12,.77,.78,.06]}
        parsed=module.parse_line(marker)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed['label'],'你好，欢迎（来）')
        self.assertEqual(parsed['rule'],'marked_sign_caption_candidate')
        self.assertEqual(parsed['confidence'],.3)
        self.assertIsNone(module.parse_line({'text':'普通标题','confidence':.3,'bounding_box':[.12,.77,.78,.06]}))

    def test_multiline_sign_caption_joins_only_adjacent_lines_below_the_marker(self):
        rows=[{'source_seconds':0.,'image':'frame.jpg','image_sha256':'a'*64,'lines':[
            {'text':'闪电超人在手语星球','confidence':.9,'bounding_box':[.5,.95,.45,.03]},
            {'text':'手语：你好，欢迎（来）','confidence':.3,'bounding_box':[.12,.77,.78,.06]},
            {'text':'陈家祠参观。我是志愿者。','confidence':1.,'bounding_box':[.08,.73,.87,.054]},
            {'text':'汉语口语解释','confidence':1.,'bounding_box':[.2,.12,.6,.04]},
        ]}]
        groups=module.caption_groups(rows,10.,2.)
        marked=[g for g in groups if g['extraction_rule']=='marked_sign_caption_candidate']
        self.assertEqual(len(marked),1)
        self.assertEqual(marked[0]['label_candidate'],'你好，欢迎（来）陈家祠参观。我是志愿者。')
        self.assertEqual(marked[0]['evidence'][0]['confidence'],.3)
        self.assertNotIn('闪电',marked[0]['label_candidate'])
        self.assertNotIn('汉语',marked[0]['label_candidate'])


if __name__=='__main__':unittest.main()
