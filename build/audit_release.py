"""Check actual public payloads against license and model/media release decisions."""
from pathlib import Path
import json,hashlib,ast,zipfile
ROOT=Path(__file__).resolve().parents[1]
def main():
 listed=[line.split('  ',1)[1]for line in(ROOT/'files.sha256').read_text('ascii').splitlines()]
 excluded=json.loads((ROOT/'compliance/external_assets.json').read_text('utf-8'))['files']
 assert all(v['path']not in listed for v in excluded if v['group']!='archives'), 'External component leaked into public payload'
 checked=0
 for name in listed:
  p=ROOT/name;data=p.read_bytes()
  if name.startswith('licenses/'):continue
  assert data[:4]!=b'\x7fELF'and p.suffix.lower()not in ['.whl','.so','.ko','.ub','.xsa','.gz'],name
  if p.suffix.lower()=='.docx':
   assert name=='report/design/system_report.docx',name
   coverage=json.loads((ROOT/'compliance/file_licenses.json').read_text('utf-8'))['files']
   assert coverage[name]['license']=='CC-BY-4.0',name
   digests={n:d for d,n in(line.split('  ',1)for line in(ROOT/'files.sha256').read_text('ascii').splitlines())}
   assert hashlib.sha256(data).hexdigest()==digests[name],name
   with zipfile.ZipFile(p)as document:
    assert document.testzip()is None
    assert '[Content_Types].xml'in document.namelist()and'word/document.xml'in document.namelist()
    assert not any('vbaproject'in n.lower()or n.startswith('word/embeddings/')for n in document.namelist()),name
  assert p.name!='yf2_weights.h'and not name.startswith('src/rtl/ip/'),name
  if p.suffix in ['.c','.h','.cpp','.cc','.v','.vhd','.sv']:
   assert b'This file contains confidential and proprietary information'not in data[:16000],name
  if p.suffix in ['.py','.pyw']:
   for node in ast.walk(ast.parse(data.decode('utf-8-sig'),filename=name)):
    if isinstance(node,ast.keyword)and node.arg=='password'and isinstance(node.value,ast.Constant):assert not node.value.value,'Literal password in '+name
  checked+=1
 rights=json.loads((ROOT/'compliance/model_and_media_rights.json').read_text('utf-8'))
 for row in rights['models_and_test_data']+rights['videos']:
  assert row['path']in listed and hashlib.sha256((ROOT/row['path']).read_bytes()).hexdigest()==row['sha256'],row['path']
 assert len(rights['videos'])==8 and all(v['publisher_confirmed_all_performers_consented']for v in rights['videos'])
 assert rights['yolo']['redistributed_pretrained_weights']is False
 for dependency in json.loads((ROOT/'compliance/python_dependencies.json').read_text('utf-8')):
  assert dependency['license_files']and all((ROOT/n).is_file()for n in dependency['license_files']),dependency['name']
 for name in json.loads((ROOT/'compliance/upstream_modifications.json').read_text('utf-8'))['files']:
  text=(ROOT/name).read_text('utf-8');assert 'Copyright (c) 2021 PaddlePaddle'in text and text.startswith('# Modified for Medical Gesture FPGA:'),name
 print(json.dumps(dict(status='PASS',checked_public_payloads=checked,license_texts='present',upstream_notices='retained',unlicensed_yolo_parameters='not_distributed',vendor_ip_and_target_binaries='not_distributed',demonstration_videos=8,performer_consent_basis='publisher_confirmation',model_provenance_basis='publisher_declaration',training_lineage_independently_reconstructed=False,hardware_accessed=False)))
if __name__=='__main__':main()
