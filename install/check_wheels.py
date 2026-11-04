"""Check the exact local offline dependency cache using Python's standard library."""
from pathlib import Path
import hashlib,json

root=Path(__file__).resolve().parents[1]
manifest=json.loads((root/'install/wheel_manifest.json').read_text('utf-8'))
for row in manifest['files']:
    path=root/'install/wheels'/row['file']
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=row['sha256']:
        raise SystemExit('Offline dependency differs from the fixed manifest: '+row['file'])
print(json.dumps(dict(status='PASS',files=len(manifest['files']))))
