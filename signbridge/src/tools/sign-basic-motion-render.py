"""Export native SMPL-X meshes with independent full/sparse LBS parity checks."""
import argparse
import importlib.util
import json
from pathlib import Path
import numpy as np
from scipy.spatial.transform import Rotation


def load_hand():
    spec = importlib.util.spec_from_file_location('native_hand', Path(__file__).with_name('sign-hand-refine.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FullMesh:
    """Full LBS; the sparse helper independently checks joints and ten tips."""
    def __init__(self, model_file):
        h = load_hand()
        self.sparse = h.SparseSMPLX(model_file)
        with np.load(model_file, allow_pickle=False) as a:
            self.template = a['v_template'].astype(float)
            self.shapes = np.concatenate([a['shapedirs'][:, :, :10], a['shapedirs'][:, :, 300:310]], axis=2)
            self.posedirs = a['posedirs'].reshape(-1, 486).astype(float)
            self.weights = a['weights'].astype(float)
            self.regressor = a['J_regressor'].astype(float)
            self.faces = a['f'].astype(np.uint32)

    def vertices(self, params):
        beta = np.concatenate([params['betas'].ravel(), params['expression'].ravel()])
        shaped = self.template + np.einsum('vcd,d->vc', self.shapes, beta)
        joints = self.regressor @ shaped
        keys = ['global_orient', 'body_pose', 'jaw_pose', 'leye_pose', 'reye_pose', 'left_hand_pose', 'right_hand_pose']
        pose = np.concatenate([params[k].reshape(-1, 3) for k in keys]) + self.sparse.mean
        rotation = Rotation.from_rotvec(pose).as_matrix()
        posed = shaped + (self.posedirs @ (rotation[1:] - np.eye(3)).ravel()).reshape(-1, 3)
        local = np.tile(np.eye(4), (55, 1, 1))
        local[:, :3, :3] = rotation
        local[:, :3, 3] = joints
        local[1:, :3, 3] -= joints[self.sparse.parents[1:]]
        world = local.copy()
        for i in range(1, 55):
            world[i] = world[self.sparse.parents[i]] @ local[i]
        js = world[:, :3, 3].copy()
        world[:, :3, 3] -= np.einsum('jcd,jd->jc', world[:, :3, :3], joints)
        blended = (self.weights @ world.reshape(55, 16)).reshape(-1, 4, 4)
        vertices = np.einsum('vij,vj->vi', blended, np.c_[posed, np.ones(len(posed))])[:, :3]
        return vertices + params['transl'].reshape(3), js + params['transl'].reshape(3)


def export(library, correction, model_file, output):
    h = load_hand()
    if h.sha256(model_file) != '376021446ddc86e99acacd795182bbef903e61d33b76b9d8b359c2b0865bd992':
        raise ValueError('Unexpected SMPL-X model')
    if output.exists() or output.is_relative_to(library) or output.is_relative_to(correction):
        raise ValueError('New separate output required')
    output.mkdir(parents=True)
    model = FullMesh(model_file)
    model.faces.tofile(output / 'faces.u32')
    jobs = []
    for sid in ['basic-i', 'basic-you']:
        report = json.loads((correction / sid / 'report.json').read_text())
        for kind in ['baseline', 'candidate']:
            folder = library / 'native-actions' / sid / 'smplx' if kind == 'baseline' else correction / sid / 'candidate'
            files = sorted(folder.glob('*.npz'))
            if [p.name for p in files] != [f'{i:05d}_0.npz' for i in range(1, report['frames'] + 1)]:
                raise ValueError('Incorrect native frame set')
            vertices = []
            max_error = 0.
            hashes = []
            for path in files:
                digest = h.sha256(path)
                p = h.read_native(path)
                v, j = model.vertices(p)
                sparse_j, tips = model.sparse.forward(p)
                error = max(np.max(np.abs(j - sparse_j)), np.max(np.abs(v[model.sparse.tip_ids] - tips)))
                if not np.isfinite(v).all() or error >= 1e-9 or h.sha256(path) != digest:
                    raise ValueError('Full/sparse forward parity or input immutability failed')
                max_error = max(max_error, float(error))
                vertices.append((v * [1, -1, -1]).astype(np.float32))
                hashes.append(digest)
            filename = f'{sid}-{kind}.f32'
            np.stack(vertices).tofile(output / filename)
            jobs.append({'id': sid, 'kind': kind, 'frames': len(files), 'vertices_per_frame': 10475,
                         'full_sparse_parity_max_error': max_error, 'native_hashes': hashes,
                         'mesh_sha256': h.sha256(output / filename), 'cuda_runtime_parity': 'not_run',
                         'correction_report_sha256': h.sha256(correction / sid / 'report.json')})
            print(json.dumps({k:v for k,v in jobs[-1].items() if k != 'native_hashes'}), flush=True)
    (output / 'report.json').write_text(json.dumps({'jobs': jobs, 'model_sha256': h.sha256(model_file),
        'tool_sha256': h.sha256(__file__), 'training_ready': False}, indent=2) + '\n')
    (output / 'tool-source.py').write_bytes(Path(__file__).read_bytes())


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ['library', 'correction', 'model', 'output']:
        parser.add_argument('--' + key, type=Path, required=True)
    a = parser.parse_args()
    export(a.library.resolve(), a.correction.resolve(), a.model.resolve(), a.output.resolve())
