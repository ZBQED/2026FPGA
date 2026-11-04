"""Package the licensed public manifest only, excluding locally imported target files."""
from pathlib import Path
import argparse,hashlib,json,zipfile
from verify_package import main as verify
from audit_release import main as audit
ROOT=Path(__file__).resolve().parents[1]
def main():
 a=argparse.ArgumentParser(description=__doc__);a.add_argument('--output',type=Path,required=True);args=a.parse_args();dest=args.output.resolve()
 if dest.is_relative_to(ROOT):a.error('Write the archive outside the source tree')
 verify();audit()
 names=[line.split('  ',1)[1]for line in(ROOT/'files.sha256').read_text('ascii').splitlines()]+['files.sha256']
 dest.parent.mkdir(parents=True,exist_ok=True)
 with zipfile.ZipFile(dest,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6)as z:
  for name in sorted(names):
   info=zipfile.ZipInfo('medical_gesture_fpga/'+name,(1980,1,1,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED;info.external_attr=0o100644<<16;z.writestr(info,(ROOT/name).read_bytes())
 with zipfile.ZipFile(dest)as z:
  assert z.testzip()is None
  for line in(ROOT/'files.sha256').read_text('ascii').splitlines():
   digest,name=line.split('  ',1);assert hashlib.sha256(z.read('medical_gesture_fpga/'+name)).hexdigest()==digest,name
 digest=hashlib.sha256(dest.read_bytes()).hexdigest();dest.with_suffix('.sha256').write_text(digest+'  '+dest.name+'\n','ascii')
 print(json.dumps(dict(status='PASS',path=str(dest),bytes=dest.stat().st_size,files=len(names),sha256=digest,zip_crc='PASS',every_file_sha256='PASS',scope='public_source_manifest_only')))
if __name__=='__main__':main()
