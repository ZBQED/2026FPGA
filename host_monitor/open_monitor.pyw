from pathlib import Path
import os,sys,subprocess,json,ctypes,time
H=Path(__file__).resolve().parent;R=H/'runtime';R.mkdir(exist_ok=True);tmp=R/'tmp';tmp.mkdir(exist_ok=True)
env=dict(os.environ,PYTHONIOENCODING='utf-8',PYTHONDONTWRITEBYTECODE='1',TEMP=str(tmp),TMP=str(tmp))
try:
 result=subprocess.run([str(Path(sys.executable).with_name('python.exe')),'-B',str(H/'launch_monitor.py')],cwd=str(H.parent),env=env,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=16,creationflags=subprocess.CREATE_NO_WINDOW)
 if result.returncode:raise RuntimeError(result.stderr.decode('utf-8','replace')[-1500:])
 owner=json.loads((R/'server_actual.json').read_text(encoding='utf-8'));url=owner['url'];assert url=='http://127.0.0.1:8765'
 candidates=[Path(os.environ.get('ProgramFiles(x86)',r'C:\Program Files (x86)'))/'Microsoft/Edge/Application/msedge.exe',Path(os.environ.get('ProgramFiles',r'C:\Program Files'))/'Microsoft/Edge/Application/msedge.exe']
 browser=next((p for p in candidates if p.is_file()),None)
 if browser is None:raise RuntimeError('Microsoft Edge executable not found; open http://127.0.0.1:8765 manually.')
 profile=R/'browser_profile';cache=R/'browser_cache';crash=R/'browser_crash'
 for q in (profile,cache,crash):q.mkdir(exist_ok=True)
 args=[str(browser),'--app='+url+'/?view=overview','--user-data-dir='+str(profile),'--disk-cache-dir='+str(cache),'--crash-dumps-dir='+str(crash),'--no-first-run','--no-default-browser-check','--start-maximized']
 q=subprocess.Popen(args,cwd=str(H.parent),env=env,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
 (R/'open_ui_actual.json').write_text(json.dumps(dict(browser_pid=q.pid,browser=str(browser),url=url,profile=str(profile),cache=str(cache),opened_at_ms=int(time.time()*1000),project_local_runtime=True),ensure_ascii=False,indent=2),encoding='utf-8')
except Exception as exc:
 (R/'open_error.log').write_text(str(exc),encoding='utf-8');ctypes.windll.user32.MessageBoxW(None,'上位机打开失败：'+str(exc)+'\n日志：'+str(R/'open_error.log'),'FPGA 上位机',16)
