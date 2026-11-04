"""Physical PS_KEY2 print mode and immutable end-dialogue jobs; no USB on toggle."""
import json,os,queue,select,struct,threading,time,uuid
from pathlib import Path

KEY_CODE=108
EVENT=struct.Struct('@llHHi')

class PressEdge:
    def __init__(self,held=False):
        self.held=held;self.last=-1e30
    def feed(self,kind,code,value,now):
        if kind!=1 or code!=KEY_CODE:return False
        if value==0:self.held=False;return False
        if value!=1 or self.held:return False
        self.held=True
        if now-self.last<0.2:return False
        self.last=now;return True

class ModeLED:
    def __init__(self,path='/sys/class/leds/ps_led0'):
        self.path=Path(path)
        if self.path.name!='ps_led0':raise RuntimeError('Only dedicated PS_LED0 is selected')
        trigger=(self.path/'trigger').read_text()
        if '[none]'not in trigger:raise RuntimeError('PS_LED0 has an active trigger; preserve its owner')
        self.maximum=int((self.path/'max_brightness').read_text())
    def set(self,on):
        value=self.maximum if on else 0
        (self.path/'brightness').write_text(str(value)+'\n')
        if int((self.path/'brightness').read_text())!=value:raise RuntimeError('Print mode LED readback failed')

class DialoguePrinter:
    def __init__(self,backend,state_dir,led=None,notify=None):
        self.backend=backend;self.state_dir=Path(state_dir);self.state_dir.mkdir(parents=True,exist_ok=True)
        self.led=led;self.notify=notify or(lambda:None);self.lock=threading.RLock()
        self.enabled=False;self.dialogue_id=uuid.uuid4().hex;self.messages=[]
        self.status='打印已关闭';self.jobs=queue.Queue(maxsize=8);self.stop=threading.Event();self.key_thread=None
        self.last_receipt=None;self.worker=threading.Thread(target=self._worker,daemon=True,name='DialoguePrinter')
        if self.led:self.led.set(False)
        self.worker.start()
    def snapshot(self):
        with self.lock:return dict(print_enabled=self.enabled,print_status_text=self.status,print_pending_jobs=self.jobs.unfinished_tasks)
    def record(self,role,text):
        if role not in('staff','patient')or not isinstance(text,str)or not text.strip():raise ValueError('Confirmed staff/patient text required')
        with self.lock:self.messages.append(dict(role=role,text=text,sequence=len(self.messages)+1,confirmed_at=time.strftime('%Y-%m-%d %H:%M:%S')))
    def record_department(self,department):
        if not isinstance(department,str)or not department.strip()or len(department)>128 or any(ord(c)<32 or 0x7f<=ord(c)<=0x9f for c in department):raise ValueError('Confirmed department name required')
        department=department.strip()
        if department in('其他','其它','其他科室','其它科室'):department='其他科室'
        with self.lock:self.messages.append(dict(role='patient',kind='department_selection',department=department,text='患者选择科室为：'+department,sequence=len(self.messages)+1,confirmed_at=time.strftime('%Y-%m-%d %H:%M:%S')))
    def toggle(self):
        with self.lock:
            new=not self.enabled
            try:
                if self.led:self.led.set(new)
            except Exception:
                self.enabled=False;self.status='打印指示灯不可用，打印已关闭'
                try:self.led.set(False)
                except Exception:pass
                raise
            self.enabled=new;self.status='打印已开启，结束对话后打印'if new else'打印已关闭'
        self.notify();return new
    def end_dialogue(self):
        # Caller holds the business state lock. The next dialogue cannot mutate this snapshot.
        with self.lock:
            job=dict(dialogue_id=self.dialogue_id,messages=[dict(v)for v in self.messages])
            if self.enabled and job['messages']:
                if self.jobs.full():raise RuntimeError('打印队列已满，请等待当前打印完成后结束对话')
                path=self.state_dir/('queued_'+job['dialogue_id']+'.json');temp=path.with_suffix('.tmp')
                with temp.open('x',encoding='utf-8')as stream:
                    json.dump(job,stream,ensure_ascii=False);stream.flush();os.fsync(stream.fileno())
                os.replace(str(temp),str(path));self.jobs.put_nowait(job);self.status='对话已结束，正在准备打印'
            self.dialogue_id=uuid.uuid4().hex;self.messages=[]
            return job['dialogue_id']
    def _worker(self):
        while not self.stop.is_set()or not self.jobs.empty():
            try:job=self.jobs.get(timeout=0.25)
            except queue.Empty:continue
            try:
                with self.lock:self.status='正在打印对话'
                self.notify()
                receipt=self.backend.print_transcript(job['dialogue_id'],job['messages'])
                with self.lock:
                    self.last_receipt=receipt
                    if receipt.get('printer_reported_complete'):self.status='对话打印完成'
                    elif receipt.get('payload_transfer_attempted'):self.status='打印已发送，请查看纸面；不会自动重打'
                    else:self.status='打印失败，对话记录已保留'
            except Exception as exc:
                with self.lock:self.status='打印失败，对话记录已保留';self.last_receipt=dict(status='CONTROLLER_PRINT_ERROR',error=str(exc),dialogue_id=job['dialogue_id'],automatic_retry=False)
            finally:self.jobs.task_done();self.notify()
    def start_key_adapter(self):
        import fcntl
        root=Path('/sys/firmware/devicetree/base/keys');verified=False
        for p in root.iterdir():
            if p.is_dir()and(p/'label').exists()and(p/'label').read_bytes().rstrip(b'\0')==b'ps_key2':
                code=int.from_bytes((p/'linux,code').read_bytes(),'big');gpio=struct.unpack('>III',(p/'gpios').read_bytes())
                verified=code==KEY_CODE and gpio[1:]==(11,1)
        if not verified:raise RuntimeError('PS_KEY2 code108/MIO11 active-low mapping differs')
        devices=[]
        for p in Path('/sys/class/input').glob('event*'):
            try:
                if(p/'device/name').read_text().strip()=='keys':devices.append('/dev/input/'+p.name)
            except OSError:pass
        if len(devices)!=1:raise RuntimeError('Exactly one original gpio-keys input required')
        fd=os.open(devices[0],os.O_RDONLY|os.O_NONBLOCK)
        def held():
            bits=bytearray(32);fcntl.ioctl(fd,0x80000000|(len(bits)<<16)|(ord('E')<<8)|0x18,bits,True)
            return bool(bits[KEY_CODE//8]&(1<<(KEY_CODE%8)))
        edge=PressEdge(held())
        def run():
            pending=b'';dropped=False
            try:
                while not self.stop.is_set():
                    if not select.select([fd],[],[],0.25)[0]:continue
                    data=os.read(fd,EVENT.size*32)
                    if not data:raise RuntimeError('Physical print key input closed')
                    pending+=data
                    while len(pending)>=EVENT.size:
                        _,_,kind,code,value=EVENT.unpack(pending[:EVENT.size]);pending=pending[EVENT.size:]
                        if kind==0 and code==3:dropped=True
                        elif dropped:
                            if kind==0 and code==0:edge.held=held();dropped=False
                        elif edge.feed(kind,code,value,time.monotonic()):self.toggle()
            except Exception as exc:
                with self.lock:
                    self.enabled=False;self.status='打印按键不可用，打印已关闭'
                    try:
                        if self.led:self.led.set(False)
                    except Exception:pass
                print('PRINT_KEY_ERROR '+str(exc),flush=True);self.notify()
            finally:os.close(fd)
        self.key_thread=threading.Thread(target=run,daemon=True,name='PS_KEY2_PrintMode');self.key_thread.start()
        return dict(key='PS_KEY2',gpio=11,linux_code=KEY_CODE,event_device=devices[0],led='PS_LED0',default_enabled=False)
    def close(self):
        self.stop.set()
        if self.key_thread:self.key_thread.join(timeout=1)
        self.worker.join(timeout=1)
        with self.lock:
            self.enabled=False
            if self.led:self.led.set(False)

def attach_board_printer(service):
    from printer_backend.dp628_backend import PrinterBackend
    folder=Path('/var/lib/medcomm/printing');controller=DialoguePrinter(PrinterBackend(folder/'usb_receipts'),folder/'jobs',ModeLED(),service.emit)
    service.dialogue_printer=controller
    try:identity=controller.start_key_adapter()
    except Exception:
        service.dialogue_printer=None;controller.close();raise
    print('DIALOGUE_PRINT_READY '+json.dumps(identity),flush=True);return controller
