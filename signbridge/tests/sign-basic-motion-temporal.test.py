"""Continuity never upgrades a pixel-only proposal into a complete sign approval."""
import importlib.util
from pathlib import Path
import unittest
import numpy as np

ROOT=Path(__file__).resolve().parents[1]/'src/tools'
def load(name):
 s=importlib.util.spec_from_file_location(name,ROOT/name);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
m=load('sign-basic-motion-temporal.py')
r=load('sign-basic-motion-render.py')


class TemporalCorrectionTests(unittest.TestCase):
 def test_contiguous_runs_do_not_bridge_missing_frames(self):
  self.assertEqual(m.contiguous([False,True,True,False,True,False]),[[1,2],[4]])
  self.assertEqual(m.contiguous([False,False]),[])

 def test_optimizer_timeout_cannot_pass_source_projection_gate(self):
  class Model:
   mean=np.zeros((55,3))
   def hand(self,p,side):return p['points']
  a={'points':np.c_[np.arange(21),np.zeros(21),np.ones(21)],'left_hand_pose':np.zeros((15,3))}
  b={k:v.copy() for k,v in a.items()};b['points'][:,:2]+=.1
  target=b['points'][:,:2].copy();target=np.c_[target,np.zeros(21)]
  cam={'focal':np.ones(2),'princpt':np.zeros(2)}
  self.assertFalse(m.frame_gate(Model(),a,b,target,cam,0)['passed'])

 def test_bad_fingertip_projection_cannot_pass(self):
  class Model:
   mean=np.zeros((55,3))
   def hand(self,p,side):return p['points']
  a={'points':np.c_[np.arange(21),np.ones(21),np.ones(21)],'left_hand_pose':np.zeros((15,3))}
  b={k:v.copy() for k,v in a.items()};b['points'][8,0]+=30
  target=a['points'].copy();cam={'focal':np.ones(2),'princpt':np.zeros(2)}
  self.assertFalse(m.frame_gate(Model(),a,b,target,cam,2)['passed'])

 def test_full_lbs_identity_and_translation(self):
  from types import SimpleNamespace
  full=r.FullMesh.__new__(r.FullMesh)
  full.template=np.array([[1.,2.,3.],[-1.,0.,2.]])
  full.shapes=np.zeros((2,3,20));full.posedirs=np.zeros((6,486));full.weights=np.zeros((2,55));full.weights[:,0]=1
  full.regressor=np.zeros((55,2));full.sparse=SimpleNamespace(mean=np.zeros((55,3)),parents=np.r_[-1,np.zeros(54,dtype=int)])
  shapes=m.c.SHAPES;p={k:np.zeros(shape) for k,shape in shapes.items()};p['transl'][:]=[.2,.3,.4]
  vertices,joints=full.vertices(p)
  np.testing.assert_allclose(vertices,full.template+[.2,.3,.4]);np.testing.assert_allclose(joints,np.tile([.2,.3,.4],(55,1)))

 def test_boundary_missing_is_still_reported_when_observed_segment_is_stable(self):
  baseline=np.zeros((4,15,3));candidate=baseline.copy();candidate[1:3,:,0]=np.pi/2
  angles=m.c.angular_change(candidate,np.zeros((15,3)));mask=np.array([False,True,True,False])
  self.assertEqual(float(angles[mask[:-1]&mask[1:]].max()),0.)
  self.assertGreater(float(angles.max()),80.)


if __name__=='__main__':unittest.main()
