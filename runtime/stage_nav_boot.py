"""Stage verified one-time Nav boot assets without restarting or reprogramming it."""
from pathlib import Path
import hashlib,json,posixpath
from connection import connect

def main():
 root=Path(__file__).resolve().parents[1];source=root/'board/nav/boot'
 import sys
 sys.path.insert(0,str(root/'build'))
 from check_external_assets import check
 if check('runtime')['status']!='READY':raise SystemExit('Provide the declared licensed target inputs first; see external_assets.md')
 manifest=json.loads((source/'manifest.json').read_text('utf-8'))
 files={name:(source/name).read_bytes()for name in manifest['files']}
 for name,data in files.items():
  assert name==Path(name).name and '/'not in name and '\\'not in name
  assert len(data)==manifest['files'][name]['bytes'] and hashlib.sha256(data).hexdigest()==manifest['files'][name]['sha256'],name
 c=connect('navigator');target='/media/sd-mmcblk0p1/medical_gesture'
 try:
  sf=c.open_sftp()
  try:
   try:sf.mkdir(target)
   except OSError:sf.stat(target)
   for name,data in files.items():
    dest=posixpath.join(target,name)
    try:
     with sf.open(dest,'rb')as f:existing=f.read()
     if existing==data:continue
     raise RuntimeError('Existing boot asset differs; preserve it: '+dest)
    except FileNotFoundError:pass
    temporary=dest+'.upload'
    with sf.open(temporary,'wb')as f:f.write(data);f.flush()
    with sf.open(temporary,'rb')as f:assert hashlib.sha256(f.read()).hexdigest()==manifest['files'][name]['sha256']
    sf.rename(temporary,dest)
  finally:sf.close()
  _,out,err=c.exec_command('sync',timeout=15)
  assert out.channel.recv_exit_status()==0,err.read().decode('utf-8','replace')
 finally:c.close()
 print(json.dumps(dict(status='STAGED',directory=target,uboot_command=manifest['uboot_command'],default_boot_modified=False,fpga_programmed=False)))
if __name__=='__main__':main()
