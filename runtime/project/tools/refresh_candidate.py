from pathlib import Path
import json,hashlib,sys
W=Path(__file__).resolve().parents[1];R=W.parent
sys.path.insert(0,str(R));import sitecustomize
H=W/'fpga/output/report_hybrid_0600_20261101/board_workers/qiming';S=H.parent/'host_support'
p=H/'q_host_ready.template.json';q=json.loads(p.read_text('utf-8'))
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
q['host_sha256']=sha(H/'q_host.py')
q['host_helper_files']={n:sha(S/n)for n in ['boardctl.py','qiming_root.py','pynq_root.py']}
for n,row in q['files'].items():
 pth=Path(row['path']);assert sha(pth)==row['sha256'],n
 row['path']='@project/'+pth.relative_to(W).as_posix()
(H/'q_host_ready.json').write_text(json.dumps(q,indent=2)+'\n','utf-8')
print(json.dumps(dict(status='PACKAGED_RUNTIME_BINDINGS_VERIFIED',files=len(q['files']))))
