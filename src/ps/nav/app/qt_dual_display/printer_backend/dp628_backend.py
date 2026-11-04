"""DP-628 finite USB backend, Python3.7+, explicit calls only; no import-time I/O."""
from pathlib import Path
import ctypes as C
import errno,hashlib,json,os,re,stat,sys,time

DESCRIPTORS_HEX='1201000200000040850441570001010200010902200001010080320904000002070102000705820240000007050202400000'
DEFAULT_BINDING=dict(vendor=0x0485,product=0x5741,port='1-1.1',configuration=1,interface=0,alternate=0,printer_class=[7,1,2],bulk_out=2,bulk_in=0x82,max_packet=64,descriptors_sha256=hashlib.sha256(bytes.fromhex(DESCRIPTORS_HEX)).hexdigest())
INIT=bytes.fromhex('1b401b21001d21001b61001b3321')
PAPER_QUERY=bytes.fromhex('100401')
TOKENS={bytes.fromhex('fe2312'):'PAPER_PRESENT',bytes.fromhex('ef231a'):'PAPER_EMPTY',bytes.fromhex('fc4f4b'):'PRINT_COMPLETE',bytes.fromhex('fc6e6f'):'PRINT_FAILED'}
class PrinterError(RuntimeError):pass

def digest(raw):return hashlib.sha256(raw).hexdigest()
def descriptor_interfaces(raw):
    if len(raw)<18 or raw[0:2]!=b'\x12\x01':raise PrinterError('Invalid USB device descriptor')
    result=[];offset=18;current=None;config=None;config_end=0
    while offset<len(raw):
        if offset+2>len(raw):raise PrinterError('Truncated USB descriptor header')
        size,kind=raw[offset:offset+2]
        if size<2 or offset+size>len(raw):raise PrinterError('Invalid USB descriptor size')
        d=raw[offset:offset+size]
        if kind==2:
            if size!=9:raise PrinterError('Invalid configuration descriptor')
            config=d[5];config_end=offset+int.from_bytes(d[2:4],'little');current=None
            if config_end>len(raw):raise PrinterError('Truncated USB configuration')
        elif kind==4:
            if size!=9 or offset>=config_end:raise PrinterError('Invalid interface descriptor')
            current=dict(configuration=config,interface=d[2],alternate=d[3],endpoint_count=d[4],printer_class=list(d[5:8]),endpoints=[]);result.append(current)
        elif kind==5:
            if size<7 or current is None:raise PrinterError('Unbound endpoint descriptor')
            current['endpoints'].append(dict(address=d[2],attributes=d[3],max_packet=int.from_bytes(d[4:6],'little')))
        offset+=size
    return result

def probe(binding=None,sysfs_root='/sys/bus/usb/devices'):
    """Only cached sysfs reads. No USB open, claim, control/data requests or printing."""
    b=dict(DEFAULT_BINDING if binding is None else binding);base=Path(sysfs_root);matches=[]
    for p in base.iterdir():
        try:
            if int((p/'idVendor').read_text().strip(),16)==b['vendor']and int((p/'idProduct').read_text().strip(),16)==b['product']:matches.append(p)
        except (FileNotFoundError,ValueError):continue
    if len(matches)!=1:raise PrinterError('Require exactly one matching 0485:5741 printer')
    p=matches[0]
    if p.name!=b['port']:raise PrinterError('Printer USB physical port differs')
    raw=(p/'descriptors').read_bytes()
    if digest(raw)!=b['descriptors_sha256']or int.from_bytes(raw[8:10],'little')!=b['vendor']or int.from_bytes(raw[10:12],'little')!=b['product']:raise PrinterError('Printer descriptor identity differs')
    candidates=[x for x in descriptor_interfaces(raw)if all(x[k]==b[k]for k in('configuration','interface','alternate','printer_class'))]
    if len(candidates)!=1:raise PrinterError('Pinned printer interface is absent or ambiguous')
    row=candidates[0];eps=row['endpoints']
    if row['endpoint_count']!=2 or len(eps)!=2 or {x['address']for x in eps}!={b['bulk_out'],b['bulk_in']}or any((x['attributes']&3)!=2 or x['max_packet']!=b['max_packet']for x in eps):raise PrinterError('Pinned bulk endpoints differ')
    interface=base/(p.name+':%d.%d'%(b['configuration'],b['interface']))
    if int((p/'bConfigurationValue').read_text())!=b['configuration']or int((interface/'bInterfaceNumber').read_text(),16)!=b['interface']or int((interface/'bAlternateSetting').read_text(),16)!=b['alternate']:raise PrinterError('Current configuration/interface/alternate differs; no auto reconfiguration')
    if (interface/'driver').exists():raise PrinterError('Kernel driver already owns printer; no detach/unbind')
    bus=int((p/'busnum').read_text());dev=int((p/'devnum').read_text());node='/dev/bus/usb/%03d/%03d'%(bus,dev)
    return dict(status='PINNED_PRINTER_SYSFS_READY',binding=b,sysfs=str(p),busnum=bus,devnum=dev,device_node=node,descriptor_sha256=digest(raw),interface_descriptor=row,paper_status='UNKNOWN_NOT_QUERIED',USB_open=False,printer_command_bytes_sent=0)

class Bulk(C.Structure):_fields_=[('ep',C.c_uint),('length',C.c_uint),('timeout',C.c_uint),('data',C.c_void_p)]
class Control(C.Structure):_fields_=[('request_type',C.c_uint8),('request',C.c_uint8),('value',C.c_uint16),('index',C.c_uint16),('length',C.c_uint16),('timeout',C.c_uint32),('data',C.c_void_p)]
def ioc(direction,number,size):return(direction<<30)|(size<<16)|(ord('U')<<8)|number

class USBTransport:
    """Linux USBDEVFS synchronous finite transfers; claims only pinned interface, no reset."""
    def __init__(self,observed):self.observed=observed;self.binding=observed['binding'];self.fd=None;self.claimed=False
    def __enter__(self):
        if not sys.platform.startswith('linux')or C.sizeof(C.c_void_p)!=4 or C.sizeof(Bulk)!=16 or C.sizeof(Control)!=16:raise PrinterError('Require verified Linux ARM32 USBDEVFS ABI16')
        libc=C.CDLL(None,use_errno=True);self.call=libc.ioctl;self.call.argtypes=[C.c_int,C.c_ulong,C.c_void_p];self.call.restype=C.c_int
        node=self.observed['device_node'];before=os.stat(node)
        if not stat.S_ISCHR(before.st_mode)or os.major(before.st_rdev)!=189:raise PrinterError('Pinned USB node is not usbfs character device')
        self.fd=os.open(node,os.O_RDWR|os.O_CLOEXEC|os.O_NOFOLLOW)
        try:
            if os.fstat(self.fd).st_rdev!=before.st_rdev:raise PrinterError('USB node changed during open')
            again=probe(self.binding)
            if again['busnum']!=self.observed['busnum']or again['devnum']!=self.observed['devnum']:raise PrinterError('Printer re-enumerated during open')
            self._ioctl(ioc(2,15,4),C.c_uint(self.binding['interface']));self.claimed=True;return self
        except BaseException:os.close(self.fd);self.fd=None;raise
    def _ioctl(self,request,value):
        C.set_errno(0);rc=self.call(self.fd,request,C.byref(value))
        if rc<0:raise OSError(C.get_errno(),'USBDEVFS ioctl 0x%08x'%request)
        return rc
    def port_status(self,timeout_ms=1000):
        buf=(C.c_ubyte*1)();row=Control(0xa1,1,0,self.binding['interface'],1,timeout_ms,C.addressof(buf));size=self._ioctl(ioc(3,0,C.sizeof(Control)),row)
        if size!=1:raise PrinterError('USB printer class status response length differs')
        value=int(buf[0]);return dict(raw=value,paper_empty=bool(value&0x20),selected=bool(value&0x10),no_error=bool(value&0x08),ready=(value&0x38)==0x18)
    def write(self,data,timeout_ms):
        if not data or len(data)>4096:raise PrinterError('Bounded bulk output required')
        buf=C.create_string_buffer(data,len(data));row=Bulk(self.binding['bulk_out'],len(data),timeout_ms,C.addressof(buf));return self._ioctl(ioc(3,2,C.sizeof(Bulk)),row)
    def read(self,timeout_ms):
        buf=(C.c_ubyte*64)();row=Bulk(self.binding['bulk_in'],64,timeout_ms,C.addressof(buf))
        try:size=self._ioctl(ioc(3,2,C.sizeof(Bulk)),row)
        except OSError as exc:
            if exc.errno==errno.ETIMEDOUT:return b''
            raise
        if not 0<=size<=64:raise PrinterError('Invalid bulk input length')
        return bytes(buf[:size])
    def __exit__(self,*unused):
        try:
            if self.fd is not None and self.claimed:self._ioctl(ioc(2,16,4),C.c_uint(self.binding['interface']))
        finally:
            if self.fd is not None:os.close(self.fd);self.fd=None

class StatusStream:
    def __init__(self):self.buffer=b''
    def feed(self,data):
        self.buffer+=data;events=[]
        while len(self.buffer)>=3:
            token=self.buffer[:3]
            if token in TOKENS:events.append(TOKENS[token]);self.buffer=self.buffer[3:]
            else:self.buffer=self.buffer[1:]
        return events

def _text(value):
    if not isinstance(value,str)or not value:raise PrinterError('Nonempty text required')
    value=value.replace('\r\n','\n').replace('\r','\n').replace('\t','    ')
    if any(ord(c)<32 and c!='\n'or 0x7f<=ord(c)<=0x9f for c in value):raise PrinterError('Printer control characters in dialogue are forbidden')
    value.encode('gbk','strict');return value

def render_transcript(dialogue_id,messages):
    """Preserve supplied chronological message order; strict GBK, never truncate/replace."""
    if not isinstance(dialogue_id,str)or re.fullmatch(r'[A-Za-z0-9._:-]{1,96}',dialogue_id)is None:raise PrinterError('Stable ASCII dialogue_id required')
    if not isinstance(messages,list)or not 1<=len(messages)<=500:raise PrinterError('Require complete ordered list of 1..500 dialogue messages')
    roles={'staff':'工','patient':'患','工':'工','患':'患'};normalized=[];lines=[]
    def wrap(text):
        for paragraph in text.split('\n'):
            line='';used=0
            for c in paragraph:
                width=len(c.encode('gbk','strict'))
                if used+width>24:lines.append(line);line='    ';used=4
                line+=c;used+=width
            lines.append(line)
    wrap('对话记录');wrap('ID:'+dialogue_id);lines.append('-'*24);last_seq=None
    for index,row in enumerate(messages):
        if not isinstance(row,dict)or row.get('role')not in roles:raise PrinterError('Only staff/patient dialogue messages may be printed')
        text=_text(row.get('text'))
        if len(text)>4000:raise PrinterError('Message exceeds finite 4000-character limit; never silently truncate')
        if 'seq'in row:
            seq=row['seq']
            if not isinstance(seq,int)or isinstance(seq,bool)or last_seq is not None and seq<=last_seq:raise PrinterError('Supplied message seq must strictly increase')
            last_seq=seq
        item=dict(index=index,role=roles[row['role']],text=text)
        if row.get('kind')=='department_selection':
            department=_text(row.get('department'))
            if roles[row['role']]!='患'or len(department)>128 or department!=department.strip()or '\n'in department:raise PrinterError('Confirmed patient department selection required')
            if department in('其他','其它','其他科室','其它科室'):department='其他科室'
            if text!='患者选择科室为：'+department:raise PrinterError('Department name and transcript text differ')
            item.update(kind='department_selection',department=department);wrap(text)
        else:wrap(roles[row['role']]+'：'+text)
        normalized.append(item)
    lines.extend(['-'*24,'对话结束','','']);encoded=('\r\n'.join(lines)+'\r\n').encode('gbk','strict');payload=INIT+encoded
    if len(payload)>65536:raise PrinterError('Complete transcript exceeds finite 64KiB; no partial print or truncation')
    source=json.dumps(normalized,ensure_ascii=False,separators=(',',':')).encode('utf-8')
    return payload,dict(encoding='gbk_strict',message_count=len(normalized),line_count=len(lines),max_encoded_line_bytes=max(len(x.encode('gbk'))for x in lines),source_sha256=digest(source),payload_sha256=digest(payload),payload_bytes=len(payload),format='chronological 工：/患： and standalone department selection; 24 GBK bytes conservative wrap; CRLF; manual tear/no cut; no UART settings')

class StateLock:
    def __init__(self,root):self.root=root;self.fd=None
    def __enter__(self):
        import fcntl
        self.root.mkdir(parents=True,exist_ok=True)
        self.fd=os.open(str(self.root/'printer.lock'),os.O_WRONLY|os.O_CREAT|os.O_CLOEXEC|os.O_NOFOLLOW,0o600)
        try:fcntl.flock(self.fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BaseException:os.close(self.fd);self.fd=None;raise
        return self
    def __exit__(self,*unused):
        if self.fd is not None:os.close(self.fd);self.fd=None

def sync_directory(path):
    if sys.platform.startswith('linux'):
        fd=os.open(str(path),os.O_RDONLY|os.O_DIRECTORY|os.O_CLOEXEC)
        try:os.fsync(fd)
        finally:os.close(fd)

def atomic_receipt(path,row):
    raw=(json.dumps(row,ensure_ascii=False,indent=2)+'\n').encode('utf-8');tmp=path.with_suffix('.%d.tmp'%os.getpid())
    fd=os.open(str(tmp),os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_CLOEXEC|os.O_NOFOLLOW,0o600)
    try:
        with os.fdopen(fd,'wb')as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
        os.replace(str(tmp),str(path));sync_directory(path.parent)
    finally:
        if tmp.exists():tmp.unlink()

class PrinterBackend:
    def __init__(self,state_dir,binding=None,total_timeout_s=90.0):
        if not 5<=total_timeout_s<=120:raise PrinterError('Finite print timeout must be 5..120 seconds')
        self.state_dir=Path(state_dir);self.binding=dict(DEFAULT_BINDING if binding is None else binding);self.timeout=float(total_timeout_s)
    def probe(self):return probe(self.binding)
    def print_transcript(self,dialogue_id,messages):
        payload,format_receipt=render_transcript(dialogue_id,messages);job_key=digest(dialogue_id.encode('utf-8'));path=self.state_dir/(job_key+'.json')
        if path.exists():old=json.loads(path.read_text(encoding='utf-8'));return dict(old,duplicate_request=True,resubmitted=False,duplicate_content_mismatch=old['format']['source_sha256']!=format_receipt['source_sha256'])
        with StateLock(self.state_dir):
            if path.exists():old=json.loads(path.read_text(encoding='utf-8'));return dict(old,duplicate_request=True,resubmitted=False,duplicate_content_mismatch=old['format']['source_sha256']!=format_receipt['source_sha256'])
            row=dict(status='CLAIMED_NOT_SENT',dialogue_id=dialogue_id,job_key=job_key,format=format_receipt,started_wall_time=time.time(),started_monotonic_ns=time.monotonic_ns(),events=[],confirmed_payload_bytes=0,payload_transfer_attempted=False,printer_reported_complete=False,physical_paper_visually_verified=False,automatic_retry=False,persistent_UART_settings_changed=False,duplicate_request=False)
            # Reservation is durable before any USB request. Crashed/failed/unknown jobs remain deduplicated.
            fd=os.open(str(path),os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_CLOEXEC|os.O_NOFOLLOW,0o600)
            with os.fdopen(fd,'w',encoding='utf-8')as stream:json.dump(row,stream,ensure_ascii=False);stream.flush();os.fsync(stream.fileno())
            sync_directory(path.parent)
            end=time.monotonic()+self.timeout
            def save():atomic_receipt(path,row)
            def timeout_ms(cap=1000):
                left=end-time.monotonic()
                if left<=0:raise TimeoutError('Finite print job deadline')
                return max(1,min(cap,int(left*1000)))
            try:
                row['probe']=self.probe();save()
                with USBTransport(row['probe'])as transport:
                    parser=StatusStream();port=None
                    try:port=transport.port_status(timeout_ms());row['USB_port_before']=port
                    except OSError as exc:row['USB_port_before_error']=dict(errno=exc.errno,error=str(exc))
                    # Drain old completion bytes before sending this job; never credit stale OK.
                    drain_end=min(end,time.monotonic()+0.6)
                    while time.monotonic()<drain_end:
                        data=transport.read(timeout_ms(100));events=parser.feed(data)
                        if events:row['events'].append(dict(phase='before_job_ignored_completion',events=events))
                        if 'PAPER_EMPTY'in events:raise PrinterError('PAPER_EMPTY_BEFORE_CONTENT')
                    paper=bool(port and port['ready'])
                    if port and port['paper_empty']:raise PrinterError('PAPER_EMPTY_BEFORE_CONTENT')
                    if not paper:
                        sent=transport.write(PAPER_QUERY,timeout_ms())
                        if sent!=len(PAPER_QUERY):raise PrinterError('Paper query short write; no content sent')
                        row['manual_paper_query_bytes']=sent;query_end=min(end,time.monotonic()+2)
                        while time.monotonic()<query_end:
                            events=parser.feed(transport.read(timeout_ms(250)))
                            if events:row['events'].append(dict(phase='paper_query',events=events))
                            if 'PAPER_EMPTY'in events:raise PrinterError('PAPER_EMPTY_BEFORE_CONTENT')
                            if 'PAPER_PRESENT'in events:paper=True;break
                        if not paper:raise PrinterError('PAPER_STATUS_UNKNOWN_NO_CONTENT_SENT')
                        # Query may itself cause a firmware idle-OK; consume it before content.
                        quiet_end=min(end,time.monotonic()+0.7)
                        while time.monotonic()<quiet_end:
                            events=parser.feed(transport.read(timeout_ms(100)))
                            if events:row['events'].append(dict(phase='precontent_query_completion_ignored',events=events))
                            if 'PAPER_EMPTY'in events:raise PrinterError('PAPER_EMPTY_BEFORE_CONTENT')
                    parser=StatusStream();row['completion_correlation']='New status stream after exclusive claim and precontent quiet drain; device OK is firmware report, not physical visual proof'
                    row.update(status='SENDING',paper_verified_before_content=True,payload_transfer_attempted=True);save()
                    offset=0
                    while offset<len(payload):
                        part=payload[offset:offset+512];size=transport.write(part,timeout_ms(3000))
                        if not 0<size<=len(part):raise PrinterError('Invalid/zero USB output progress; no resend')
                        offset+=size;row['confirmed_payload_bytes']=offset
                    row.update(status='SENT_WAITING_PRINTER_COMPLETION',last_payload_write_monotonic_ns=time.monotonic_ns());save()
                    while time.monotonic()<end:
                        events=parser.feed(transport.read(timeout_ms(500)))
                        if events:row['events'].append(dict(phase='after_job',monotonic_ns=time.monotonic_ns(),events=events))
                        if 'PRINT_FAILED'in events or 'PAPER_EMPTY'in events:
                            row.update(status='PRINTER_REPORTED_FAILURE_DO_NOT_RETRY',error='Printer reported paper/print failure');break
                        if 'PRINT_COMPLETE'in events:
                            row.update(status='PRINTER_REPORTED_COMPLETE',printer_reported_complete=True);break
                    else:row.update(status='SENT_COMPLETION_UNKNOWN_DO_NOT_RETRY',error='USB payload delivered but no correlated firmware completion before deadline')
                save()
            except Exception as exc:
                row.update(status='TRANSFER_UNCERTAIN_DO_NOT_RETRY'if row['payload_transfer_attempted']else'BLOCKED_BEFORE_CONTENT_NO_AUTORETRY',error_type=type(exc).__name__,error=str(exc));save()
            finally:row['finished_wall_time']=time.time();row['finished_monotonic_ns']=time.monotonic_ns();save()
            return row

_default_backend=None
def configure(state_dir,binding=None,total_timeout_s=90.0):
    """Configuration only. No filesystem creation, USB access or printer commands."""
    global _default_backend
    _default_backend=PrinterBackend(state_dir,binding,total_timeout_s)
def print_transcript(dialogue_id,messages):
    if _default_backend is None:raise PrinterError('Call configure(state_dir) explicitly before printing')
    return _default_backend.print_transcript(dialogue_id,messages)

def main():
    import argparse
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('action',choices=('probe','render','print'),nargs='?',default='probe');ap.add_argument('--input');ap.add_argument('--state-dir');ap.add_argument('--execute-print',action='store_true');args=ap.parse_args()
    if args.action=='probe':result=probe()
    else:
        if not args.input:ap.error('--input dialogue JSON required')
        source=json.loads(Path(args.input).read_text(encoding='utf-8'))
        if args.action=='render':payload,result=render_transcript(source['dialogue_id'],source['messages']);result['printer_bytes_sent']=0
        else:
            if not args.execute_print or not args.state_dir:ap.error('print requires --execute-print and explicit --state-dir')
            result=PrinterBackend(args.state_dir).print_transcript(source['dialogue_id'],source['messages'])
    print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
