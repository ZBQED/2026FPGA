from pathlib import Path
import argparse,json,os,subprocess,sys,time,urllib.request
import psutil
a=argparse.ArgumentParser();a.add_argument("--port",type=int,default=8765);args=a.parse_args()
H=Path(__file__).resolve().parent;R=H/'runtime';R.mkdir(exist_ok=True)
def ready():
 try:
  d=json.loads((R/'server_actual.json').read_text(encoding='utf-8'))
  assert d['url']==f'http://127.0.0.1:{args.port}'
  assert Path(d['root']).resolve()==H
  process=psutil.Process(d['pid'])
  assert any(Path(x).resolve()==(H/'server.py').resolve() for x in process.cmdline() if x.endswith('server.py'))
  v=json.load(urllib.request.urlopen(d['url']+'/api/health',timeout=1))
  assert v.get('status')=='ok'and v.get('numeric_only')is True
  return d
 except Exception:return None
old=ready()
if old:print(json.dumps(dict(status='ALREADY_RUNNING',url=old['url'],pid=old['pid']),ensure_ascii=False));raise SystemExit(0)
env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',PYTHONIOENCODING='utf-8',TEMP=str(R/'tmp'),TMP=str(R/'tmp'));(R/'tmp').mkdir(exist_ok=True)
with(R/'server.log').open('ab',buffering=0)as log:
 p=subprocess.Popen([sys.executable,'-B',str(H/'server.py'),'--port',str(args.port)],cwd=str(H.parent),env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW|subprocess.CREATE_NEW_PROCESS_GROUP)
end=time.monotonic()+15
while time.monotonic()<end:
 d=ready()
 # Windows venv launchers may forward execution to a child Python process.
 owned=[p.pid]
 try:owned.extend(q.pid for q in psutil.Process(p.pid).children(recursive=True))
 except psutil.NoSuchProcess:pass
 if d and d['pid']in owned:print(json.dumps(dict(status='RUNNING',url=d['url'],pid=d['pid']),ensure_ascii=False));break
 if p.poll()is not None:raise RuntimeError('Monitor exited; inspect host_monitor/runtime/server.log')
 time.sleep(.1)
else:raise RuntimeError('Monitor startup deadline; inspect retained host_monitor/runtime/server.log')
