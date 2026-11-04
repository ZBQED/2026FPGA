"""Read-only integrity and local-reference validation; no board access."""
from pathlib import Path
import ast, hashlib, json, re, os, xml.etree.ElementTree as ET

root = Path(__file__).resolve().parents[1]
listed = {}
for line in (root/'files.sha256').read_text('ascii').splitlines():
    digest, name = line.split('  ', 1)
    assert not Path(name).is_absolute() and '..' not in Path(name).parts, name
    listed[name] = digest
for name, digest in listed.items():
    path = root/name
    assert path.is_file(), 'Missing '+name
    assert hashlib.sha256(path.read_bytes()).hexdigest() == digest, 'Modified '+name
actual = set()
for directory, dirs, names in os.walk(root):
    relative=Path(directory).relative_to(root).as_posix()
    dirs[:]=[d for d in dirs if d not in ['.venv','.cache','__pycache__','.git','build_output'] and not(relative=='host_monitor'and d=='runtime')]
    for name in names:
        item=(Path(directory)/name).relative_to(root).as_posix()
        generated=(item.startswith('runtime/project/runs/')or ('/board_workers/qiming/'in item and (name.startswith('qlive_')or name in ['active.json','q_host_ready.json'])))
        if item not in listed and generated:continue
        if not name.endswith(('.pyc','.tmp')):actual.add(item)
assert actual == set(listed)|{'files.sha256'}, 'Unlisted or missing files: '+str(actual.symmetric_difference(set(listed)|{'files.sha256'}))
for name in listed:
    assert re.fullmatch(r'[a-zA-Z0-9_./+-]+', name), name
    path = root/name
    if path.suffix == '.py': ast.parse(path.read_text('utf-8-sig'),filename=name)
    if path.suffix == '.json': json.loads(path.read_text('utf-8-sig'))
    if path.name == 'component.xml':
        for node in ET.parse(path).getroot().findall('{*}fileSets/{*}fileSet/{*}file/{*}name'):
            assert (path.parent/node.text).resolve().is_relative_to(root.resolve()) and (path.parent/node.text).is_file(), (name,node.text)
    if path.suffix == '.qrc':
        for node in ET.parse(path).getroot().iter('file'):
            assert (path.parent/node.text).resolve().is_relative_to(root.resolve()) and (path.parent/node.text).is_file(), (name,node.text)
    if path.name == 'files.prj':
        for ref in re.findall(r'"([^"]+)"',path.read_text('utf-8')):
            assert (path.parent/ref).resolve().is_relative_to(root.resolve()) and (path.parent/ref).is_file(), (name,ref)
for name, item in json.loads((root/'skill/files_sha256.json').read_text('utf-8'))['files'].items():
    file=root/'skill'/name
    assert file.stat().st_size == item['bytes'] and hashlib.sha256(file.read_bytes()).hexdigest()==item['sha256'],name
frame=root/'data/test_inputs/fixed_frame.bin'
assert frame.stat().st_size==800*480*3
expected=json.loads((root/'board/outputs/fastest_visual/result.json').read_text('utf-8'))['test_input_sha256']
assert hashlib.sha256(frame.read_bytes()).hexdigest()==expected
for dep in json.loads((root/'board/external_dependencies.json').read_text('utf-8')):
    for name in dep['binary_paths']:
        assert hashlib.sha256((root/name).read_bytes()).hexdigest()==dep['sha256'], name
for row in json.loads((root/'board/recovery_manifest.json').read_text('utf-8'))['files']:
    assert hashlib.sha256((root/row['destination']).read_bytes()).hexdigest()==row['sha256'], row['destination']
print(json.dumps(dict(status='PASS',files=len(actual),sha256='pass',python_syntax='pass',
    ip_and_qml_references='pass',simulation_sources='pass',skill_original='pass',
    fixed_input='pass',native_dependency_hashes='pass',hardware_accessed=False)))
