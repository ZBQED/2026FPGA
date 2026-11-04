"""Only the early virtual filesystems/directories used by original services."""
from pathlib import Path
import os,subprocess
def prepare():
 if os.getpid()!=1 or os.geteuid()!=0:raise RuntimeError('Private PID1 only')
 for path,kind,source in [('/var/volatile','tmpfs','tmpfs'),('/dev/pts','devpts','devpts')]:
  Path(path).mkdir(exist_ok=True)
  if not os.path.ismount(path):subprocess.run(['/bin/mount','-t',kind,source,path],check=True)
 for name,mode in [('log',0o755),('run',0o755),('lock',0o755),('tmp',0o1777),('runtime-root',0o700)]:
  path=Path('/var/volatile')/name;path.mkdir(mode=mode,exist_ok=True)
  if name in ('tmp','runtime-root'):os.chmod(str(path),mode)
