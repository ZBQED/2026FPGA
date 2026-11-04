"""Report delivery readiness without importing runtime code or accessing boards."""
from pathlib import Path
import hashlib
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
status = json.loads((ROOT/'board/completion_status.json').read_text('utf-8'))
manifest = json.loads((ROOT/'board/recovery_manifest.json').read_text('utf-8'))
errors = []
for row in manifest['files']:
    path = ROOT/row['destination']
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != row['sha256']:
        errors.append('Recovered file differs: '+row['destination'])
for relative, expected in status['bound_files'].items():
    path = ROOT/relative
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        errors.append('Bound file differs: '+relative)
pending = [item for item in status['requirements'] if not item['complete']]
print(json.dumps(dict(status='INTEGRITY_ERROR' if errors else 'INCOMPLETE' if pending else 'READY',
                      recovered_file_integrity=not errors, errors=errors,
                      pending=pending, scope=status.get('scope'),hardware_accessed=False), ensure_ascii=False, indent=2))
sys.exit(1 if errors else 2 if pending else 0)
