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


if __name__=='__main__':unittest.main()
