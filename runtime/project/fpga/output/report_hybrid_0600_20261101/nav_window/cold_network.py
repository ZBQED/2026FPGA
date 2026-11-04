"""Explicit private PID1 PS-MIO network and existing Dropbear, no rcS/rc5."""
from pathlib import Path
import hashlib,json,os,stat,subprocess,time

class RetainedChild(RuntimeError):pass
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def require_file(path,pins):
 row=pins[path];p=Path(path);s=p.stat()
 if s.st_uid!=row['uid'] or stat.S_IMODE(s.st_mode)!=int(row['mode'],8) or s.st_size!=row['bytes'] or sha(p)!=row['sha256']:raise RuntimeError('Pinned original file differs: '+path)

class ColdNetwork:
 def __init__(self,state,bindings):self.state=Path(state);self.bindings=bindings;self.children=[];self.streams=[];self.dropbear=None
 def run_returned(self,args,timeout):
  p=subprocess.Popen(args,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,close_fds=True)
  self.children.append(p)
  try:out,err=p.communicate(input=b'',timeout=timeout)
  except subprocess.TimeoutExpired:raise RetainedChild('Retain live original helper; no kill/retry: '+args[0])
  if p.returncode:raise RuntimeError('Original helper rejected: '+args[0]+': '+err.decode('utf-8','replace')[-1000:])
  return out
 def start(self):
  b=self.bindings
  if os.getpid()!=1 or os.geteuid()!=0 or b.get('root_network_source_reviewed') is not True or b.get('dropbear_exact_flags_reviewed') is not True:raise RuntimeError('Private PID1 + source-reviewed MIO network/Dropbear binding required')
  if str(Path('/sys/class/net/eth0/device').resolve())!='/sys/devices/soc0/amba/e000b000.ethernet' or str(Path('/sys/class/net/eth0/device/driver').resolve())!='/sys/bus/platform/drivers/macb':raise RuntimeError('PS GEM0 identity differs; no PL/other interface configuration')
  for path in ['/sbin/ifconfig','/usr/sbin/dropbear']:require_file(path,b['files'])
  hostkeys=b['hostkeys']
  if not hostkeys:raise RuntimeError('Existing host key binding missing; never generate/replace keys')
  for path in hostkeys:require_file(path,hostkeys)
  self.run_returned(['/sbin/ifconfig','lo','127.0.0.1','up'],8)
  self.run_returned(['/sbin/ifconfig','eth0','192.168.1.10','netmask','255.255.255.0','up'],8)
  # Original host keys and authentication; bind only the existing board IP,
  # no local/remote SSH forwarding, foreground child stays owned by PID1.
  if b.get('preserved_original_extra_args')!=['-B']:raise RuntimeError('Actual original Dropbear authentication arguments differ')
  args=['/usr/sbin/dropbear','-F','-E','-j','-k','-B','-p','192.168.1.10:22','-P',str(self.state/'dropbear.pid')]
  for path in sorted(hostkeys):args+=['-r',path]
  log=(self.state/'dropbear.log').open('xb');self.streams.append(log)
  self.dropbear=subprocess.Popen(args,stdin=subprocess.PIPE,stdout=log,stderr=log,close_fds=True);self.children.append(self.dropbear)
  time.sleep(.2)
  if self.dropbear.poll() is not None:raise RuntimeError('Original Dropbear exited; no retry')
  return dict(eth0='192.168.1.10/24',PS_GEM0_MIO=True,dropbear_pid=self.dropbear.pid,forwarding=False,original_rcS_rc5_invoked=False)
