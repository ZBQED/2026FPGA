"""Small SSH runner for the authorized three-board live work."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import importlib.util
import json
import shlex
import sys

from connection import connect

def run(role, code, payload=None, python='python3', timeout=40):
    payload = {'source': code, 'payload': payload}
    code = "import io,json,sys;d=json.load(sys.stdin);sys.stdin=io.StringIO(json.dumps(d['payload']));exec(compile(d['source'],'<remote>','exec'))"
    client = connect(role)
    try:
        stdin, stdout, stderr = client.exec_command(shlex.quote(python) + ' -B -c ' + shlex.quote(code), timeout=timeout)
        if payload is not None:
            stdin.write(json.dumps(payload))
        stdin.channel.shutdown_write()
        out, err = stdout.read().decode('utf-8', 'replace'), stderr.read().decode('utf-8', 'replace')
        return dict(rc=stdout.channel.recv_exit_status(), stdout=out, stderr=err[-3000:])
    finally:
        client.close()

INVENTORY = r'''
from pathlib import Path
import json,subprocess
processes=[]
for p in Path('/proc').iterdir():
 if not p.name.isdigit():continue
 try:
  args=(p/'cmdline').read_bytes().replace(b'\0',b' ').decode('utf-8','replace').strip()
  if any(s in args for s in ('gesture','medcomm','speech','touch')) and '-B -c ' not in args:
   st=(p/'stat').read_text().rsplit(')',1)[1].split()
   processes.append(dict(pid=int(p.name),start_ticks=int(st[19]),args=args))
 except OSError:pass
roots=[str(p) for base in ('/opt','/home/root','/home/xilinx') if Path(base).exists() for p in Path(base).glob('*gesture*')]
print(json.dumps(dict(boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip(),processes=processes,roots=roots,tcp=Path('/proc/net/tcp').read_text())))
'''

def main():
    roles=('navigator','qiming','pynq')
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures={r:pool.submit(run,r,INVENTORY) for r in roles}
        result={r:f.result() for r,f in futures.items()}
    (HERE/'live_inventory.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result))

if __name__=='__main__':main()
