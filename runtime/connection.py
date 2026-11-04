"""Pinned SSH host keys and transient credentials supplied by the operator."""
from pathlib import Path
import os,paramiko,json,shlex
ROOT=Path(__file__).resolve().parent
ADDRESSES={'navigator':'192.168.1.10','qiming':'192.168.1.30','pynq':'192.168.1.20'}
class Client(paramiko.SSHClient):
 relay=None
 def close(self):
  super().close()
  if self.relay:self.relay.close();self.relay=None
def password(role):
 value=os.environ.get('MGD_'+role.upper()+'_PASSWORD')
 if value is None:raise RuntimeError('Set MGD_'+role.upper()+'_PASSWORD or configure an SSH key and passwordless sudo')
 return value
def connect(role):
 if role not in ADDRESSES:raise ValueError(role)
 c=Client();c.load_host_keys(str(ROOT/'known_hosts'));c.set_missing_host_key_policy(paramiko.RejectPolicy())
 options=dict(hostname=ADDRESSES[role],username=os.environ.get('MGD_'+role.upper()+'_USER','root'if role=='navigator'else'xilinx'),timeout=8,auth_timeout=8,banner_timeout=8,allow_agent=True,look_for_keys=True)
 if os.environ.get('MGD_'+role.upper()+'_KEY'):options['key_filename']=os.environ['MGD_'+role.upper()+'_KEY']
 if 'MGD_'+role.upper()+'_PASSWORD'in os.environ:options['password']=password(role)
 if role!='navigator'and os.environ.get('MGD_DIRECT_SSH')!='1':
  c.relay=connect('navigator');options['sock']=c.relay.get_transport().open_channel('direct-tcpip',(ADDRESSES[role],22),('127.0.0.1',0),timeout=8)
 try:c.connect(**options);return c
 except BaseException:c.close();raise
def execute(client,code,payload,role,timeout=45):
 wrapper="import io,json,sys;d=json.load(sys.stdin);sys.stdin=io.StringIO(json.dumps(d['payload']));exec(compile(d['source'],'<remote>','exec'))"
 prefix='sudo -n 'if os.environ.get('MGD_'+role.upper()+'_NOPASSWD')=='1'else"sudo -k -S -p '' "
 i,o,e=client.exec_command(prefix+'/usr/local/share/pynq-venv/bin/python3 -B -c '+shlex.quote(wrapper),timeout=timeout)
 if '-S'in prefix:i.write(password(role)+'\n')
 i.write(json.dumps(dict(source=code,payload=payload)));i.flush();i.channel.shutdown_write()
 out=o.read().decode('utf-8','replace');err=e.read().decode('utf-8','replace')
 if o.channel.recv_exit_status():raise RuntimeError(role+' operation failed: '+err[-4000:])
 return out
