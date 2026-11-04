"""Package every manifest entry in the complete project; caches remain local."""
from pathlib import Path
import argparse,hashlib,json,subprocess,sys,zipfile

ROOT=Path(__file__).resolve().parents[1]
def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args();target=args.output.resolve()
    if target.is_relative_to(ROOT):parser.error('Write the ZIP outside the project directory')
    for name in ['verify_package.py','audit_release.py','check_release_names.py']:
        subprocess.run([sys.executable,'-B',str(ROOT/'build'/name)],check=True)
    rows={n:d for d,n in(line.split('  ',1)for line in(ROOT/'files.sha256').read_text('ascii').splitlines())}
    target.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(target,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6)as z:
        for name in sorted([*rows,'files.sha256']):
            info=zipfile.ZipInfo('medical_gesture_fpga/'+name,(1980,1,1,0,0,0));info.external_attr=0o100644<<16
            info.compress_type=zipfile.ZIP_STORED if Path(name).suffix in{'.gz','.whl','.mp4','.png','.npz','.xsa'}else zipfile.ZIP_DEFLATED
            z.writestr(info,(ROOT/name).read_bytes())
    with zipfile.ZipFile(target)as z:
        assert z.testzip()is None
        for name,digest in rows.items():assert hashlib.sha256(z.read('medical_gesture_fpga/'+name)).hexdigest()==digest,name
    digest=hashlib.sha256(target.read_bytes()).hexdigest();target.with_suffix('.sha256').write_text(digest+'  '+target.name+'\n','ascii')
    result=dict(status='PASS',path=str(target),bytes=target.stat().st_size,files=len(rows)+1,sha256=digest,zip_crc='PASS',every_file_sha256='PASS')
    print(json.dumps(result),flush=True)
if __name__=='__main__':main()
