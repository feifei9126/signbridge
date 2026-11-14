"""Conservative temporal alternatives select existing poses, never invent hand tracks."""
import importlib.util,json
import unittest
from pathlib import Path
from types import SimpleNamespace
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
SCRIPT=ROOT/'src/tools/sign-sequence-curate.py'


class SequenceCurateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec=importlib.util.spec_from_file_location('sequence_curate',SCRIPT)
        cls.c=importlib.util.module_from_spec(spec);spec.loader.exec_module(cls.c)

    def parameters(self,n):
        return {k:np.zeros((n,)+s,dtype=np.float32) for k,s in self.c.align.hand.SHAPES.items()}

    def test_no_new_large_jump_keeps_every_existing_candidate(self):
        a=self.parameters(4);b={k:v.copy() for k,v in a.items()}
        b['left_hand_pose'][:,:,0]=np.arange(4)[:,None]*.1
        mask=np.ones((4,2),dtype=bool)
        selection=self.c.choose_existing_poses(a,b,mask)
        self.assertTrue(selection.all())

    def test_new_jump_can_only_be_removed_by_selecting_an_existing_baseline(self):
        a=self.parameters(4);b={k:v.copy() for k,v in a.items()}
        b['left_hand_pose'][2,:,0]=np.deg2rad(140.)
        mask=np.ones((4,2),dtype=bool)
        selection=self.c.choose_existing_poses(a,b,mask)
        self.assertFalse(selection[2]);self.assertEqual(int(selection.sum()),3)
        self.assertEqual(b['left_hand_pose'][2,0,0],np.float32(np.deg2rad(140.)))

    def test_root_translation_shape_and_missing_masks_cannot_change(self):
        a=self.parameters(3);b={k:v.copy() for k,v in a.items()}
        b['transl'][1,0,2]=1.
        with self.assertRaisesRegex(ValueError,'Protected'):
            self.c.choose_existing_poses(a,b,np.ones((3,2),dtype=bool))
        with self.assertRaises(ValueError):
            self.c.choose_existing_poses(a,a,np.ones((3,2),dtype=np.int8))

    def test_unaccepted_hand_cannot_be_relabelled_as_a_temporal_candidate(self):
        a=self.parameters(3);b={k:v.copy() for k,v in a.items()}
        b['right_hand_pose'][1,:,0]=.2
        with self.assertRaisesRegex(ValueError,'Unaccepted'):
            self.c.choose_existing_poses(a,b,np.zeros((3,2),dtype=bool))


class SequenceCurateIntegrationTests(unittest.TestCase):
    def setUp(self):
        s=importlib.util.spec_from_file_location('curate_runtime',SCRIPT);self.c=importlib.util.module_from_spec(s);s.loader.exec_module(self.c)
        s=importlib.util.spec_from_file_location('curate_export_fixture',ROOT/'tests/sign-sequence-export.test.py')
        fixtures=importlib.util.module_from_spec(s);s.loader.exec_module(fixtures)
        self.f=fixtures.SequenceExportIntegrationTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        exported=self.f.run_export().parent
        self.args=SimpleNamespace(motions=exported,output=exported.parent/'curated')

    def test_curated_output_never_overwrites_inputs_or_creates_accepted_missing_hands(self):
        source=self.args.motions;before={p:self.c.evidence.digest(p) for p in source.rglob('*') if p.is_file()}
        p=self.c.curate(self.args);r=json.loads(p.read_text())
        self.assertFalse(r['training_ready']);self.assertTrue(r['temporal_selection']['no_pose_interpolation'])
        self.assertEqual({p:self.c.evidence.digest(p) for p in before},before)
        for segment in self.f.counts:
            folder=p.parent/'samples'/segment
            self.assertFalse(np.load(folder/'feature-valid-mask.npy',allow_pickle=False)[:,30:120].any())
        self.c.evidence.verify_manifest(p.parent,p.parent/'SHA256SUMS')

    def test_numeric_or_changed_selection_masks_are_rejected_before_any_output(self):
        segment='pilot-greeting-hello-001';p=self.args.motions/'samples'/segment/'fused-smplx-series.npz'
        with np.load(p,allow_pickle=False) as a:values={k:a[k].copy() for k in a.files}
        values['candidate_applied_mask']=values['candidate_applied_mask'].astype(np.int8)
        np.savez_compressed(p,**values);self.f.f.f.fixture.write_manifest(self.args.motions)
        with self.assertRaisesRegex(ValueError,'mask'):
            self.c.curate(self.args)
        self.assertFalse(self.args.output.exists())


if __name__=='__main__':unittest.main()
