"""Preserve the existing patient UI input route; no device/service handoff."""
from pathlib import Path
import os,socket,stat,struct,time


class InheritedTouch:
    def __init__(self,g):
        self.g=g;self.suspended=False
        self.receipt=dict(mode='inherit_current_patient_input_route',services_changed=False,synthetic_clicks=0,input_grab=False)

    def state(self,pid):
        env=dict(x.decode().split('=',1)for x in Path('/proc',str(pid),'environ').read_bytes().split(b'\0')if b'='in x)
        keys=('MEDCOMM_TOUCH_SOCKET','QT_QPA_FB_DISABLE_INPUT','QT_QPA_EVDEV_MOUSE_PARAMETERS','QT_QPA_EVDEV_TOUCHSCREEN_PARAMETERS','QT_QPA_GENERIC_PLUGINS')
        devices=[]
        for fd in Path('/proc',str(pid),'fd').iterdir():
            try:
                target=os.readlink(str(fd))
                if target.startswith('/dev/input/'):devices.append(target)
            except FileNotFoundError:pass
        return {k:env.get(k)for k in keys},sorted(devices)

    def snapshot(self):
        rows=[]
        for p in Path('/proc').iterdir():
            if not p.name.isdigit():continue
            row=self.g.identity(int(p.name))
            if row and row['argv'][0]==self.g.TARGET and '--patient'in row['argv']:rows.append(row)
        assert len(rows)==1
        self.before=self.state(rows[0]['pid']);self.receipt.update(environment=self.before[0],input_devices=self.before[1])

    def suspend(self):pass
    def private_ui(self,env,args):return env,args

    def verify_private(self,record,log_path=None):
        assert self.g.same(record) and self.state(record['pid'])==self.before, 'Original input route changed'
        path=self.before[0].get('MEDCOMM_TOUCH_SOCKET')
        if path:
            deadline=time.monotonic()+8
            while True:
                try:
                    info=os.stat(path);assert stat.S_ISSOCK(info.st_mode)and info.st_uid==0
                    with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)as probe:
                        probe.settimeout(.3);probe.connect(path);pid,uid,gid=struct.unpack('3i',probe.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))
                    assert pid==record['pid']and uid==0
                    self.receipt.setdefault('touch_socket_checks',[]).append(dict(pid=pid,ready_monotonic_ns=time.monotonic_ns(),sent_bytes=0));break
                except (OSError,AssertionError):
                    if time.monotonic()>=deadline:raise
                    time.sleep(.05)
        self.receipt['private_input_route_preserved']=True

    def verify_restored(self,record):
        self.verify_private(record);self.receipt['original_input_route_restored']=True
