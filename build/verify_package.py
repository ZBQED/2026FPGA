"""Verify public-source integrity, license coverage, and declared local references."""
from pathlib import Path
import ast,hashlib,json,os,re,xml.etree.ElementTree as ET
ROOT=Path(__file__).resolve().parents[1]
def main():
 listed={name:digest for digest,name in[line.split('  ',1)for line in(ROOT/'files.sha256').read_text('ascii').splitlines()]}
 external={v['path']:v for v in json.loads((ROOT/'compliance/external_assets.json').read_text('utf-8'))['files']}
 coverage=json.loads((ROOT/'compliance/file_licenses.json').read_text('utf-8'))['files']
 assert set(coverage)==set(listed)|{'files.sha256'},'License coverage differs from the release tree'
 for name,digest in listed.items():
  assert re.fullmatch(r'[a-zA-Z0-9_./+-]+',name)and'..'not in Path(name).parts,name
  p=ROOT/name;assert p.is_file()and hashlib.sha256(p.read_bytes()).hexdigest()==digest,'Modified or missing: '+name
  row=coverage[name];assert row['license']and all((ROOT/v).is_file()for v in row['license_files']),name
 seen=set()
 for base,dirs,names in os.walk(ROOT):
  relative=Path(base).relative_to(ROOT).as_posix();dirs[:]=[d for d in dirs if d not in ['.venv','.cache','__pycache__','.git']and not(relative=='host_monitor'and d=='runtime')]
  for name in names:
   p=Path(base)/name;rel=p.relative_to(ROOT).as_posix()
   if name.endswith(('.pyc','.tmp','.upload')):continue
   if rel not in listed and rel!='files.sha256':
    if rel in external:
     assert hashlib.sha256(p.read_bytes()).hexdigest()==external[rel]['sha256'],'External checksum differs: '+rel
     continue
    if rel.startswith('runtime/project/runs/')or'/board_workers/qiming/'in rel and(name.startswith('qlive_')or name in ['active.json','q_host_ready.json']):continue
    raise AssertionError('Unlisted file: '+rel)
   seen.add(rel)
 assert seen==set(listed)|{'files.sha256'}
 declared_refs=0
 def reference(path):
  nonlocal declared_refs
  rel=path.resolve().relative_to(ROOT.resolve()).as_posix()
  if path.is_file():return
  assert rel in external,'Undeclared missing reference: '+rel;declared_refs+=1
 for name in listed:
  p=ROOT/name
  if p.suffix in ['.py','.pyw']:ast.parse(p.read_text('utf-8-sig'),filename=name)
  if p.suffix=='.json':json.loads(p.read_text('utf-8-sig'))
  if p.name=='component.xml':
   for node in ET.parse(p).getroot().findall('{*}fileSets/{*}fileSet/{*}file/{*}name'):reference(p.parent/node.text)
  if p.suffix=='.qrc':
   for node in ET.parse(p).getroot().iter('file'):reference(p.parent/node.text)
  if p.name=='files.prj':
   for ref in re.findall(r'"([^"]+)"',p.read_text('utf-8')):reference(p.parent/ref)
 for name,row in json.loads((ROOT/'skill/files_sha256.json').read_text('utf-8'))['files'].items():
  p=ROOT/'skill'/name;assert p.stat().st_size==row['bytes']and hashlib.sha256(p.read_bytes()).hexdigest()==row['sha256'],name
 assert (ROOT/'data/test_inputs/fixed_frame.bin').stat().st_size==800*480*3
 print(json.dumps(dict(status='PASS',release_type='public_source',files=len(seen),file_sha256='PASS',license_file_coverage='PASS',syntax_and_local_references='PASS',declared_external_references=declared_refs,skill_original_sha256='PASS',hardware_accessed=False)))
if __name__=='__main__':main()
