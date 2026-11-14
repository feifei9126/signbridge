"""Package a hash-verified public-motion-demo build without discovering private data."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import stat
import zipfile


def sha(data):
    return hashlib.sha256(data).hexdigest()


def package(build, output):
    build, output = Path(build), Path(output)
    sidecars = [Path(str(output) + suffix) for suffix in ['.sha256', '.contents.json']]
    for target in [output, *sidecars]:
        if target.exists() or target.is_symlink():
            raise FileExistsError(target)
    if build.is_symlink():
        raise ValueError('Build root symlink rejected')
    if (build / 'BUILD.json').is_symlink():
        raise ValueError('Build metadata symlink rejected')
    metadata = (build / 'BUILD.json').read_bytes()
    info = json.loads(metadata)
    if (info.get('schema') != 'signbridge-build-v1'
            or info.get('profile') != 'public-motion-demo'
            or info.get('public_motion_release') != 'public-motion-v1'
            or any(info.get(key) is not False for key in
                   ['training_ready', 'model_training_ready', 'deployment_ready'])):
        raise ValueError('Not a bounded public motion build')
    expected = info.get('files')
    if not isinstance(expected, dict) or not expected:
        raise ValueError('Missing build file hashes')
    files = {'BUILD.json': metadata}
    for name, digest in expected.items():
        path = PurePosixPath(name)
        if (not name or path.is_absolute() or '..' in path.parts or '\\' in name
                or str(path) != name or name in ['BUILD.json', '.signbridge-build.json']):
            raise ValueError('Unsafe build member: ' + name)
        source = build / name
        if any(build.joinpath(*path.parts[:i]).is_symlink() for i in range(1, len(path.parts) + 1)):
            raise ValueError('Build member symlink rejected: ' + name)
        data = source.read_bytes()
        if sha(data) != digest:
            raise ValueError('Build file digest differs: ' + name)
        files[name] = data
    for path in build.rglob('*'):
        if path.is_symlink():
            raise ValueError('Build member symlink rejected')
        if path.is_file() and path.relative_to(build).as_posix() not in {*files, '.signbridge-build.json'}:
            raise ValueError('Unlisted build file: ' + path.name)
    with zipfile.ZipFile(output, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data in sorted(files.items()):
            entry = zipfile.ZipInfo(name, date_time=(2026, 10, 27, 0, 0, 0))
            entry.create_system = 3
            mode = 0o755 if name.endswith('.command') else 0o644
            entry.external_attr = (stat.S_IFREG | mode) << 16
            entry.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(entry, data, compresslevel=9)
    digests = {name: sha(data) for name, data in sorted(files.items())}
    with zipfile.ZipFile(output) as archive:
        if set(archive.namelist()) != set(files) or any(sha(archive.read(name)) != digest for name, digest in digests.items()):
            raise ValueError('Archive verification failed')
    archive_hash = sha(output.read_bytes())
    with sidecars[0].open('x') as handle:
        handle.write(f'{archive_hash}  {output.name}\n')
    with sidecars[1].open('x') as handle:
        json.dump({'schema': 'signbridge-public-motion-package-v1', 'release': 'public-motion-v1',
                   'archive_sha256': archive_hash, 'archive_bytes': output.stat().st_size,
                   'files': digests, 'training_ready': False, 'model_training_ready': False,
                   'deployment_ready': False}, handle, indent=2)
        handle.write('\n')
    return archive_hash


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(package(args.build, args.output))


if __name__ == '__main__':
    main()
