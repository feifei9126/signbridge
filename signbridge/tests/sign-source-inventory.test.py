"""New intake inventories must not classify themselves as previous sources."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

SCRIPT=Path(__file__).resolve().parents[1]/'src/tools/sign-source-inventory.py'
spec=importlib.util.spec_from_file_location('source_inventory',SCRIPT)
module=importlib.util.module_from_spec(spec)
if SCRIPT.exists():
    spec.loader.exec_module(module)


class InventoryTests(unittest.TestCase):
    def test_relative_dataset_paths_exclude_current_batch(self):
        with tempfile.TemporaryDirectory(dir='.') as tmp:
            dataset=Path(tmp)
            current=dataset/'current'
            current.mkdir()
            prior=dataset/'previous'
            prior.mkdir()
            (current/'sources.json').write_text('{}')
            (current/'inventory.json').write_text('{}')
            (prior/'sources.json').write_text('{}')
            files=module.discover_manifests(dataset,(current.resolve(),))
            self.assertEqual(files,[(prior/'sources.json').resolve()])

    def test_same_batch_duplicate_is_distinct_from_prior_duplicate(self):
        sources=[{'source_id':'a','sha256':'a'*64,'relative_path':'a.mp4'},
                 {'source_id':'b','sha256':'a'*64,'relative_path':'b.mp4'},
                 {'source_id':'c','sha256':'c'*64,'relative_path':'c.mp4'}]
        groups=module.group_sources(sources,{'c'*64:[{'source_id':'old-c'}]})
        self.assertEqual(len(groups),2)
        new=[r for r in groups if not r['duplicate_with_prior_registry']]
        self.assertEqual(len(new),1)
        self.assertEqual(new[0]['same_content_paths'],['a.mp4','b.mp4'])

    def test_song_language_and_handshape_routes_remain_separate(self):
        self.assertEqual(module.classify('国际手语简单教学'),'cross_language_or_international_unconfirmed')
        self.assertEqual(module.classify('《这世界那么多人》手语版'),'song_or_choreography_candidate')
        self.assertEqual(module.classify('有趣的自然手语手形_A_'),'handshape_or_alphabet_reference')
        self.assertEqual(module.classify('国家通用手语01'),'standard_csl_tutorial_candidate')
        self.assertEqual(module.classify('自然手语-01'),'regional_natural_sign_candidate')

    def test_unsupported_digest_is_rejected(self):
        with self.assertRaises(ValueError):
            module.group_sources([{'source_id':'x','sha256':'not-a-digest','relative_path':'x.mp4'}],{})

    def test_source6_analysis_and_song_videos_are_not_auto_screened_as_sign_labels(self):
        titles = [
            '手语和汉语语序差别在哪 re给你看（一）',
            '【闪记手语鉴定】鉴定一下网络热门手语视频（1）',
            '不知道如何避雷麻麻地的手语教学视频？来学怎么选择有质量的资源！',
            '【手语】私信评论的高频问题Q&A',
            '«老爹大战米奇»之手语翻译究竟在忙什么',
        ]
        for title in titles:
            with self.subTest(title=title):
                self.assertEqual(module.classify(title), 'explanation_or_service_unconfirmed')
        self.assertEqual(module.classify('【手语教学】闪电版本的«世界赠予我的»'), 'song_or_choreography_candidate')
        self.assertEqual(module.classify('【Day 1】公共服务类手语教学（一）'), 'tutorial_content_unconfirmed')


if __name__=='__main__':
    unittest.main()
