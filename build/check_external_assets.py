"""Verify declared target inputs without connecting to a board."""
from pathlib import Path
import argparse,hashlib,json
ROOT=Path(__file__).resolve().parents[1]
def check(group='runtime'):
 rows=json.loads((ROOT/'compliance/external_assets.json').read_text('utf-8'))['files']
 groups={'runtime':{'runtime_targets','models_yolo'},'hardware':{'hardware_sources'},'all':{'target_artifacts','runtime_targets','models_yolo','hardware_sources'}}
 missing=[];different=[];present=[]
 for row in rows:
  if row['group']not in groups[group]or group=='runtime'and not row['path'].startswith('runtime/'):continue
  p=ROOT/row['path']
  if not p.is_file():missing.append(row['path'])
  elif hashlib.sha256(p.read_bytes()).hexdigest()!=row['sha256']:different.append(row['path'])
  else:present.append(row['path'])
 return dict(status='READY'if not missing and not different else'EXTERNAL_INPUTS_REQUIRED',group=group,present=len(present),missing=missing,different=different,hardware_accessed=False)
if __name__=='__main__':
 a=argparse.ArgumentParser(description=__doc__);a.add_argument('--group',choices=['runtime','hardware','all'],default='runtime');a.add_argument('--require',action='store_true');args=a.parse_args();result=check(args.group);print(json.dumps(result,ensure_ascii=False,indent=2));raise SystemExit(2 if args.require and result['status']!='READY'else 0)
