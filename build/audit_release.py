"""Verify complete component inclusion and license scope; preserve original component terms."""
from pathlib import Path
import hashlib,json

ROOT=Path(__file__).resolve().parents[1]
def main():
    listed={n:d for d,n in(line.split('  ',1)for line in(ROOT/'files.sha256').read_text('ascii').splitlines())}
    licenses=json.loads((ROOT/'compliance/file_licenses.json').read_text('utf-8'))['files']
    assert set(licenses)==set(listed)|{'files.sha256'}
    for name,row in licenses.items():
        assert row['license']and all((ROOT/p).is_file()for p in row['license_files']),name
    bundled=json.loads((ROOT/'compliance/bundled_inputs.json').read_text('utf-8'))['files']
    for row in bundled:
        p=ROOT/row['path'];assert p.stat().st_size==row['bytes']and hashlib.sha256(p.read_bytes()).hexdigest()==row['sha256'],row['path']
    deps=json.loads((ROOT/'build/dependencies/manifest.json').read_text('utf-8'))['archives']
    for row in deps:
        p=ROOT/row['path'];assert p.stat().st_size==row['bytes']and hashlib.sha256(p.read_bytes()).hexdigest()==row['sha256'],row['path']
    media=json.loads((ROOT/'compliance/model_and_media_rights.json').read_text('utf-8'))
    for row in media['models_and_test_data']+media['videos']:
        assert hashlib.sha256((ROOT/row['path']).read_bytes()).hexdigest()==row['sha256'],row['path']
    assert len(media['videos'])==8 and all(row['publisher_confirmed_all_performers_consented']for row in media['videos'])
    for name in json.loads((ROOT/'compliance/upstream_modifications.json').read_text('utf-8'))['files']:
        text=(ROOT/name).read_text('utf-8');assert'Copyright (c) 2021 PaddlePaddle'in text and text.startswith('# Modified for Medical Gesture FPGA:'),name
    print(json.dumps(dict(status='PASS',scope='complete_reproduction_bundle',license_scope_entries=len(licenses),bundled_components=len(bundled),local_build_archives=len(deps),demonstration_videos=8,original_terms='retained',distribution_basis='publisher_confirmation',hardware_accessed=False)))
if __name__=='__main__':main()
