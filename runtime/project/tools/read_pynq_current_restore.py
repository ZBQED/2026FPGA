"""Capture this boot's actual PYNQ restore identity. No service or FPGA mutations."""
from pathlib import Path
import importlib.util
import json

WORK=Path(__file__).resolve().parents[1]
V=WORK/'fpga/output/report_hybrid_0600_20261101'
spec=importlib.util.spec_from_file_location('p_restore_root',V/'board_workers/host_support/pynq_root.py')
host=importlib.util.module_from_spec(spec);spec.loader.exec_module(host)
source=r'''
from pathlib import Path
import hashlib,json,os,subprocess
os.environ['XILINX_XRT']='/usr'
from pynq import PL
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
bit=Path(PL.bitfile_name);hwh=bit.with_suffix('.hwh')
r=dict(boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip(),bit=str(bit),hwh=str(hwh),
       bit_sha256=sha(bit),hwh_sha256=sha(hwh),PL_timestamp=PL.timestamp,
       manager=Path('/sys/class/fpga_manager/fpga0/state').read_text().strip(),mapped_owners=[])
for p in Path('/proc').iterdir():
 if not p.name.isdigit() or int(p.name)==os.getpid():continue
 try:
  maps=[v for v in (p/'maps').read_text().splitlines() if '/dev/mem' in v or '/dev/uio' in v or '/dev/gesture' in v]
  if maps:r['mapped_owners'].append(dict(pid=int(p.name),argv=(p/'cmdline').read_bytes().replace(bytes([0]),b' ').decode(),maps=maps))
 except OSError:pass
config=Path('/home/xilinx/jupyter_notebooks/2026FPGA_project/03_b_smoke_test/b_standby_config.json')
r['service_config_sha256']=sha(config)
print(json.dumps(r))
'''
client=host.connect('pynq')
try:
    result=json.loads(host.execute(client,source,None,timeout=20))
    (WORK/'runs/pynq_current_restore.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result))
finally:client.close()
