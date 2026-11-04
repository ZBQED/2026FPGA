"""Import only hash-matched target files from a legitimately obtained local source."""
from pathlib import Path,PurePosixPath
import argparse,hashlib,json,zipfile
ROOT=Path(__file__).resolve().parents[1]
def main():
 a=argparse.ArgumentParser(description=__doc__);a.add_argument('--source',type=Path,required=True);a.add_argument('--group',choices=['runtime','hardware','all'],default='all');a.add_argument('--dry-run',action='store_true');args=a.parse_args()
 groups={'runtime':{'runtime_targets','models_yolo'},'hardware':{'hardware_sources'},'all':{'target_artifacts','runtime_targets','models_yolo','hardware_sources'}}
 rows=[v for v in json.loads((ROOT/'compliance/external_assets.json').read_text('utf-8'))['files']if v['group']in groups[args.group]and(args.group!='runtime'or v['path'].startswith('runtime/'))]
 source=args.source.resolve();archive=zipfile.ZipFile(source)if source.is_file()else None
 members=archive.namelist()if archive else[];prepared=[]
 try:
  for row in rows:
   name=row['path'];parts=PurePosixPath(name).parts
   if PurePosixPath(name).is_absolute()or'..'in parts or'\\'in name:raise ValueError('Unsafe manifest path')
   target=ROOT.joinpath(*parts);target.resolve().relative_to(ROOT.resolve())
   if archive:
    candidates=[n for n in members if n.casefold()==name.casefold()or n.casefold().endswith('/'+name.casefold())]
    if len(candidates)!=1:raise RuntimeError('Source archive must contain exactly one copy: '+name)
    data=archive.read(candidates[0])
   else:
    local=source.joinpath(*parts).resolve();local.relative_to(source);data=local.read_bytes()
   if len(data)!=row['bytes']or hashlib.sha256(data).hexdigest()!=row['sha256']:raise RuntimeError('Source checksum differs: '+name)
   if target.exists()and target.read_bytes()!=data:raise RuntimeError('Preserving modified local file: '+name)
   prepared.append((target,data))
  # Check every source first; a missing or mismatched member writes nothing.
  if not args.dry_run:
   for target,data in prepared:
    if target.is_file():continue
    target.parent.mkdir(parents=True,exist_ok=True);temporary=target.with_name(target.name+'.upload');temporary.write_bytes(data);temporary.replace(target)
 finally:
  if archive:archive.close()
 print(json.dumps(dict(status='DRY_RUN_PASS'if args.dry_run else'IMPORTED',files=len(prepared),group=args.group,rights_granted_by_importer=False,hardware_accessed=False)))
if __name__=='__main__':main()
