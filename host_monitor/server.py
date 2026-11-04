"""Local numeric-only FPGA telemetry host. No camera pixels or control actions."""
from pathlib import Path
import argparse,collections,copy,datetime,hmac,http.server,json,math,os,re,secrets,shlex,socket,sys,threading,time,urllib.parse
ROOT=Path(__file__).resolve().parent;PROJECT=ROOT.parent;RUN=ROOT/'runtime';RUN.mkdir(exist_ok=True)
for key,part in {'TEMP':'tmp','TMP':'tmp','XDG_CACHE_HOME':'cache','MPLCONFIGDIR':'mpl'}.items():
 q=RUN/part;q.mkdir(exist_ok=True);os.environ[key]=str(q)
os.environ['PYTHONDONTWRITEBYTECODE']='1'
sys.path.insert(0,str(PROJECT/'runtime'))
from connection import connect
from display_hand_color import assign_current_color_sides
from pipeline_source import current_session,ingest_pipeline
from audio_stream import AudioStream
NOW=lambda:int(time.time()*1000)

def read_json(path):
 for _ in range(3):
  try:return json.loads(Path(path).read_text(encoding='utf-8'))
  except (OSError,ValueError):time.sleep(.015)
 return None

def number(v):return type(v)in(int,float)and math.isfinite(v)
def delta(new,old):
 if new>=old:return new-old
 if old>0xf0000000 and new<0x0fffffff:return new+(1<<32)-old
 return None
REMOTE=r"""
from pathlib import Path
import json,time,subprocess,sys
p=json.load(sys.stdin);r=dict(boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip(),remote_unix_ms=int(time.time()*1000),monotonic_ns=time.monotonic_ns(),netdev=Path('/proc/net/dev').read_text(),snmp=Path('/proc/net/snmp').read_text(),operstate={f.name:(f/'operstate').read_text().strip()for f in Path('/sys/class/net').iterdir()if(f/'operstate').exists()},power=[],thermal=[],audio_meter=[],ack=None)
for h in Path('/sys/class/hwmon').glob('hwmon*'):
 for f in h.glob('power*_input'):
  try:r['power'].append(dict(path=str(f),watts=int(f.read_text())/1000000.,label=f.with_name(f.name.replace('_input','_label')).read_text().strip()if f.with_name(f.name.replace('_input','_label')).exists()else f.name))
  except(OSError,ValueError):pass
for f in Path('/sys/class/thermal').glob('thermal_zone*/temp'):
 try:r['thermal'].append(dict(path=str(f),temp_c=int(f.read_text())/1000.))
 except(OSError,ValueError):pass
if not r['thermal']:
 for f in Path('/sys/bus/iio/devices').glob('iio:device*/in_temp0_raw'):
  try:r['thermal'].append(dict(path=str(f),temp_c=(float(f.read_text())+float(f.with_name('in_temp0_offset').read_text()))*float(f.with_name('in_temp0_scale').read_text())/1000.))
  except(OSError,ValueError):pass
if p.get('nav_state'):
 try:r['ack']=json.loads((Path(p['nav_state'])/'overlay_draw_ack.json').read_text())
 except(OSError,ValueError):pass
if p.get('pipeline_state'):
 try:
  f=Path(p['pipeline_state'])/'monitor_snapshot.json';raw=f.read_bytes()
  if len(raw)<=1048576:r['pipeline']=json.loads(raw.decode('utf-8'))
 except(OSError,ValueError):pass
if p.get('audio'):
 try:
  q=subprocess.run(['journalctl','-b','-u','b-speech-standby.service','-n','100','--no-pager','-o','json'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=3)
  for line in q.stdout.decode('utf-8','replace').splitlines():
   try:
    v=json.loads(line);m=v.get('MESSAGE','')
    if m.startswith('AUDIO_METER '):r['audio_meter'].append(dict(unix_ms=int(v['__REALTIME_TIMESTAMP'])//1000,values=json.loads(m[12:])))
   except(ValueError,KeyError):pass
 except(OSError,subprocess.TimeoutExpired):pass
for key,path in [('b_receiver','/run/b-seven-extension/state.json'),('b_observer','/run/b-speech-ui/state.json')]:
 try:
  if Path(path).exists():
   with open(path,'rb')as f:raw=f.read(1048577)
   if len(raw)<=1048576:r[key]=json.loads(raw.decode('utf-8'));r[key+'_collected_monotonic_ns']=time.monotonic_ns()
 except(OSError,ValueError):pass
print(json.dumps(r))
"""
ROLE={'navigator':('NAV / 领航者','摄像 · HDMI · 触摸','192.168.1.10'),'qiming':('Q / 启明星','YOLO · Hand · TCN硬件推理','192.168.1.30'),'pynq':('P / PYNQ','Hand硬件推理 · 音频','192.168.1.20')}
class Engine:
 def __init__(self):
  self.lock=threading.RLock();self.stop=threading.Event();self.live={};self.active={};self.derived={};self.prev_live=None;self.remote={};self.prev_remote={};self.board_rows={};self.link_rows={};self.audio=dict(available=False,kind='rms_envelope',source='PYNQ 已有 AudioLevelMeter',status_text='等待音频遥测，未打开额外采音',waveform=[],observed_at_ms=None);self.events=collections.deque(maxlen=80);self.last_event=None;self.event_seq=0;self.prev_receiver=None;self.b_speech={};self.last_b_result=None;self.seen_b_results=set();self.audio_stream=AudioStream(connect,self.stop,RUN/'audio_stream_actual.json')
 def event(self,kind,text,level='info'):
  self.event_seq+=1;self.events.append(dict(id=self.event_seq,t_ms=NOW(),level=level,type=kind,message=text))
 def start(self):
  self.audio_stream.start()
  threading.Thread(target=self.poll_live,daemon=True).start()
  for role in ROLE:threading.Thread(target=self.poll_board,args=(role,),daemon=True).start()
 def poll_live(self):
  while not self.stop.is_set():
   try:
    a=current_session(PROJECT);d=None
    with self.lock:
     self.active=a
     if a.get('status')!='FPGA_PIPELINE_RUNNING':self.link_rows.get('pc_udp',{}).update(status='stopped',rx_Bps=None,tx_Bps=None,rx_pps=None,tx_pps=None)
     if d:
      token=(d.get('session_id'),d.get('heartbeat_unix_ns'));old=self.prev_live
      if not old or token!=(old.get('session_id'),old.get('heartbeat_unix_ns')):
       if old and old.get('session_id')==d.get('session_id'):
        dt=(d['heartbeat_unix_ns']-old['heartbeat_unix_ns'])/1e9
        if dt>0:
         self.derived['inference_fps']=(d['frame_count']-old['frame_count'])/dt
         lo=old.get('last',{});ln=d.get('last',{});source_dt=(ln.get('timestamp_us',0)-lo.get('timestamp_us',0))/1e6
         self.derived['camera_fps']=(ln['frame_id']-lo['frame_id'])/source_dt if source_dt>0 else None
         sent=d.get('PC_business_UDP_messages_sent',ln.get('PC_business_UDP_messages_sent'));sent_old=old.get('PC_business_UDP_messages_sent',lo.get('PC_business_UDP_messages_sent'));byt=d.get('PC_business_UDP_bytes_sent',ln.get('PC_business_UDP_bytes_sent'));byt_old=old.get('PC_business_UDP_bytes_sent',lo.get('PC_business_UDP_bytes_sent'))
         self.link_rows['pc_udp']=dict(id='pc_udp',label='PC → Nav 识别业务',transport='UDP · 业务子集',endpoint='192.168.1.10:5005',status='online',observed_at_ms=d['heartbeat_unix_ns']//1000000,rx_Bps=None,tx_Bps=(byt-byt_old)/dt if number(byt)and number(byt_old)else None,rx_pps=None,tx_pps=(sent-sent_old)/dt if number(sent)and number(sent_old)else None,errors=None,include_in_total=False,rate_source='实际 sendto 成功字节/消息计数差分，非以太网线速')
       else:self.derived={};self.event('session','运行会话 '+str(d.get('session_id')))if a.get('status')=='FPGA_PIPELINE_RUNNING'and 0<=NOW()-d.get('heartbeat_unix_ns',0)/1000000<=3000 else None
       self.prev_live=d;self.live=d
       e=d.get('last',{}).get('TCN_last');eid=(d.get('session_id'),e.get('event_id'))if e else None
       if eid and eid!=self.last_event and a.get('status')=='FPGA_PIPELINE_RUNNING'and 0<=NOW()-d.get('heartbeat_unix_ns',0)/1000000<=3000 and number(e.get('emitted_ms'))and 0<=d.get('last',{}).get('timestamp_us',0)/1000-e['emitted_ms']<=3000:
        self.last_event=eid;self.event('TCN',f"{e.get('gesture','')} · {e.get('confidence',0)*100:.2f}% · "+('接受'if e.get('confidence',0)>=d.get('confidence_min',.8)else'拒绝'))
   except Exception as exc:
    with self.lock:self.live_error=type(exc).__name__+': '+str(exc)
   self.stop.wait(.3)
 def poll_board(self,role):
  client=None
  while not self.stop.is_set():
   try:
    if client is None:client=connect(role)
    with self.lock:state=self.active.get('Nav_active',{}).get('state_root')if role=='navigator'else None
    if state and not re.fullmatch('/run/gesture-pc-demo-[0-9a-f]{16}',state):state=None
    wrapper="import json,sys,io;d=json.load(sys.stdin);sys.stdin=io.StringIO(json.dumps(d['payload']));exec(compile(d['code'],'<numeric-telemetry>','exec'))"
    i,o,e=client.exec_command('python3 -B -c '+shlex.quote(wrapper),timeout=8);i.write(json.dumps(dict(code=REMOTE,payload=dict(nav_state=state,pipeline_state=self.active.get('pipeline_state')if role=='navigator'else None,audio=False))));i.flush();i.channel.shutdown_write();data=o.read();err=e.read();rc=o.channel.recv_exit_status()
    if rc:raise RuntimeError(err.decode('utf-8','replace')[-300:])
    data=json.loads(data);self.ingest_board(role,data)
   except Exception as exc:
    with self.lock:
     label,role_label,ip=ROLE[role];planned=(read_json(RUN/'expected_offline.json')or{}).get(role);self.board_rows[role]=dict(id=role,label=label,role=role_label,status='powered_off_by_user'if planned else'unreachable',status_label='已关机 · 暂不使用'if planned else'不可达',observed_at_ms=NOW(),power_w=None,power_source='遥测未连接',stale_after_ms=10000,temp_c=None,error=type(exc).__name__+': '+str(exc))
     if role=='pynq'and planned:self.audio=dict(available=False,kind='rms_envelope',source='PYNQ 原采音 AudioLevelMeter',observed_at_ms=None,waveform=[],rms_dbfs=None,peak_dbfs=None,status_text='PYNQ已按要求关机，语音与音量监测暂停')
     for k,v in self.link_rows.items():
      if k.startswith(role+':'):v['status']='powered_off_by_user'if planned else'unreachable'
    if client:
     try:client.close()
     except Exception:pass
    client=None
   self.stop.wait(2.2 if role=='navigator'else 6.)
  if client:client.close()
 def ingest_board(self,role,data):
  now=NOW();label,role_label,ip=ROLE[role];interfaces={}
  for line in data['netdev'].splitlines()[2:]:
   if ':'not in line:continue
   name,rest=line.split(':',1);name=name.strip();v=list(map(int,rest.split()))
   if re.fullmatch(r'(eth|en)[A-Za-z0-9_.-]*',name)and not(data.get('operstate',{}).get(name)in('down','notpresent','lowerlayerdown')and v[0]==v[8]==0):interfaces[name]=dict(rx=v[0],rp=v[1],re=v[2],tx=v[8],tp=v[9],te=v[10])
  with self.lock:
   old=self.prev_remote.get(role);dt=(data['monotonic_ns']-old['monotonic_ns'])/1e9 if old and old['boot_id']==data['boot_id']else 0
   for key in list(self.link_rows):
    if key.startswith(role+':')and key.split(':',1)[1]not in interfaces:del self.link_rows[key]
   for name,row in interfaces.items():
    prev=old.get('interfaces',{}).get(name)if old else None;rates={key:None for key in ('rx_Bps','tx_Bps','rx_pps','tx_pps')}
    if dt>0 and prev:
     for key,counter in [('rx_Bps','rx'),('tx_Bps','tx'),('rx_pps','rp'),('tx_pps','tp')]:
      diff=delta(row[counter],prev[counter]);rates[key]=diff/dt if diff is not None else None
    self.link_rows[role+':'+name]=dict(id=role+':'+name,label=label+' / '+name,transport='Ethernet',endpoint=ip,status='online',observed_at_ms=now,stale_after_ms=3000 if role=='navigator'else 10000,errors=row['re']+row['te'],include_in_total=role=='navigator'and name=='eth0',rate_source='/proc/net/dev 实际字节差分；含协议开销及其它业务',**rates)
   data['interfaces']=interfaces;data['host_observed_at_ms']=now;self.prev_remote[role]=data;self.remote[role]=data
   total=[v for v in data['power']if re.search(r'(^|\W)(board|total|input|p_in)(\W|$)',v.get('label',''),re.I)]
   self.board_rows[role]=dict(id=role,label=label,role=role_label,status='online',observed_at_ms=now,stale_after_ms=3000 if role=='navigator'else 10000,power_w=total[0]['watts']if len(total)==1 else None,power_source=(total[0]['path']if len(total)==1 else '未发现可读整板功率传感器'),power_observed_at_ms=now if len(total)==1 else None,power_stale_after_ms=3000 if role=='navigator'else 10000,power_rails=data['power'],temp_c=data['thermal'][0]['temp_c']if data['thermal']else None,temp_source=data['thermal'][0]['path']if data['thermal']else None)
   if role=='navigator':
    self.ingest_b_receiver(data,now)
    ingest_pipeline(self,data,now)
   if role=='pynq':self.ingest_b_observer(data,now)
   if role=='pynq' and data.get('audio_meter'):
    meters=[v for v in data['audio_meter']if isinstance(v,dict)and number(v.get('unix_ms'))and v['unix_ms']<=data['remote_unix_ms']+1000 and isinstance(v.get('values'),dict)and number(v['values'].get('mono_rms'))and 0<=v['values']['mono_rms']<=1 and number(v['values'].get('mono_peak'))and 0<=v['values']['mono_peak']<=1]
    if not meters:return
    last=meters[-1];age=max(0,data['remote_unix_ms']-last['unix_ms']);v=last['values'];self.audio=dict(available=age<6000,observed_at_ms=now-age,source='PYNQ 原采音 AudioLevelMeter · 真实 RMS 包络',stale_after_ms=10000,kind='rms_envelope',sample_rate_hz=None,waveform=[x['values']['mono_rms']for x in meters],rms_dbfs=v.get('mono_dbfs'),peak_dbfs=20*math.log10(max(v.get('mono_peak',0),1e-12)),status_text='原采音电平 · 非 PCM 波形'if age<6000 else'当前未采音或日志过期')
 def ingest_b_receiver(self,data,now):
  b=data.get('b_receiver')
  if not isinstance(b,dict)or b.get('os_boot_id')!=data.get('boot_id'):return
  stamp=b.get('updated_monotonic_ns');age=(data.get('b_receiver_collected_monotonic_ns',data['monotonic_ns'])-stamp)/1e6 if number(stamp)else 1e99
  stats=b.get('stats')or{};valid=0<=age<=3500;active=valid and number(stats.get('active_connections'))and stats['active_connections']>0
  old=self.prev_receiver;dt=(stamp-old.get('updated_monotonic_ns',stamp))/1e9 if old and old.get('receiver_boot_id')==b.get('receiver_boot_id')and number(stamp)else 0
  rates={k:None for k in ('rx_Bps','tx_Bps','rx_pps','tx_pps')}
  if active and dt>0:
   for key,counter in [('rx_Bps','rx_bytes'),('tx_Bps','tx_bytes')]:
    x=stats.get(counter);y=old.get('stats',{}).get(counter)
    if number(x)and number(y)and x>=y:rates[key]=(x-y)/dt
  self.link_rows['b_tcp']=dict(id='b_tcp',label='B 语音 → Nav 接收',transport='TCP · 业务子集',endpoint='192.168.1.20 → .10:9000',status='online'if active else'waiting',observed_at_ms=now-age,stale_after_ms=3500,errors=None,include_in_total=False,rate_source='Nav实际recv字节/成功sendall ACK字节差分，非以太网线速；accepted仅为草稿',**rates)
  self.b_speech['receiver']=dict(available=valid,observed_at_ms=now-age,stale_after_ms=3500,intent_table_version=b.get('intent_table_version'),model_version=b.get('model_version'),stats=stats,turn_authorized=bool((b.get('voice_capture_context')or{}).get('token')))
  for result in b.get('recent_results',[]):
   key=(b.get('receiver_boot_id'),result.get('sequence'))
   received=result.get('received_unix_ms');top=result.get('top3')
   if key not in self.seen_b_results and number(received)and 0<=NOW()-received<=10000 and isinstance(top,list)and top and isinstance(top[0],dict):
    c=top[0];score=c.get('score');catalog=read_json(ROOT/'config/speech_intents.json')or{};name=next((x.get('meaning',x.get('sign_text',''))for x in catalog.get('intents',[])if x.get('intent_id')==c.get('intent_id')),c.get('code',''))
    text=name+' · '+result.get('ack_status','')+(' · %.2f%%'%(score*100)if number(score)else'')
    self.event('B语音',text+(' · 待人工确认'if result.get('ack_status')=='accepted'else''));self.last_b_result=key
   self.seen_b_results.add(key)
  if len(self.seen_b_results)>256:self.seen_b_results={(b.get('receiver_boot_id'),v.get('sequence'))for v in b.get('recent_results',[])}
  self.prev_receiver=b
 def ingest_b_observer(self,data,now):
  b=data.get('b_observer')
  if not isinstance(b,dict):return
  stamp=b.get('updated_monotonic');age=(data.get('b_observer_collected_monotonic_ns',data['monotonic_ns'])/1e9-stamp)*1000 if number(stamp)else 1e99
  self.b_speech['board']=dict(available=0<=age<=10000,observed_at_ms=now-age,stale_after_ms=10000,phase=b.get('phase'),model_version=b.get('model_version'),intent_table_version=b.get('intent_table_version'),event_count=b.get('event_count'),remote_context_available=b.get('remote_context_available'),communication_stats=b.get('communication_stats'),last_result=b.get('last_result'),input_source=b.get('input_source'))
 def snapshot(self):
  with self.lock:
   d=self.live;a=self.active;r=d.get('last',{});packet=r.get('frame_packet',{});body=[]
   for name,p in packet.get('body',{}).get('points',{}).items():
    idx=p.get('index');xy=p.get('pixels');valid=not p.get('missing',True)and isinstance(xy,(list,tuple))and len(xy)==2 and all(number(v)for v in xy)and 0<=xy[0]<800 and 0<=xy[1]<480
    if idx is not None or name in('FOREHEAD','CHEST'):body.append(dict(id=idx if idx is not None else 100 if name=='FOREHEAD'else 101,name=name,x=xy[0]if valid else None,y=xy[1]if valid else None,confidence=p.get('confidence'),valid=valid))
   hands=[]
   for h in packet.get('hands',[]):
    points=[]
    coords=h.get('pixels');coords=coords if isinstance(coords,list)else [];missing=h.get('joint_missing');missing=missing if isinstance(missing,list)else []
    for j,xy in enumerate(coords):
     valid=j<len(missing)and not missing[j]and isinstance(xy,(list,tuple))and len(xy)==2 and all(number(v)for v in xy)and 0<=xy[0]<800 and 0<=xy[1]<480
     points.append(dict(id=j,x=xy[0]if valid else None,y=xy[1]if valid else None,valid=valid,confidence=None))
    hands.append(dict(side=h.get('side')or'Unknown',identity_missing=h.get('identity_missing'),hand_presence=h.get('confidence'),points=points))
   if hands:
    decoded=[[0.,0.,0.]for _ in range(17)];valid_body=[False]*17
    for point in body:
     if isinstance(point['id'],int)and 0<=point['id']<17 and point['valid']:decoded[point['id']]=[point['x'],point['y'],point.get('confidence')or 0.];valid_body[point['id']]=True
    raw=[dict(v,anatomical_side=v.get('side'))for v in packet.get('hands',[])]
    try:
     for hand,color in zip(hands,assign_current_color_sides(raw,decoded,valid_body)):hand.update(color)
    except(ValueError,TypeError,IndexError):pass
   observed=d.get('heartbeat_unix_ns',0)//1000000 or None;frame_id=r.get('frame_id');word=r.get('TCN_last')or{};nav=self.remote.get('navigator',{});ack=nav.get('ack')or{};eof=None
   eof_observed=None
   if ack.get('session_id')==d.get('session_id') and ack.get('boot_id')==a.get('Nav_active',{}).get('boot_id') and ack.get('source_frame_pairing_verified')and ack.get('current_source_valid'):
    try:
     copied=int(ack['framebuffer_copy_done_ns']);age=max(0,(nav['monotonic_ns']-copied)/1e6);eof_observed=nav['host_observed_at_ms']-age
     if NOW()-eof_observed<=3000:eof=(copied-int(ack['source_capture_ns']))/1e6
    except(KeyError,ValueError):pass
   boxes=r.get('person_body_recovery',{}).get('person',{}).get('final_boxes',[]);box=boxes[0][:4]if boxes and isinstance(boxes[0],list)and len(boxes[0])>=4 else None
   if eof is None and number(r.get('capture_to_scanout_ms')):
    eof=r['capture_to_scanout_ms'];eof_observed=observed
   result=dict(schema_version=1,updated_at_ms=NOW(),session=dict(id=d.get('session_id',a.get('session_id')),status=a.get('status','未运行'),mode=('三板FPGA协同 · 固定输入复现'if d.get('source_scope')=='fixed_fixture'else'三板FPGA协同 · PC前段辅助与监控')if a.get('status')=='FPGA_PIPELINE_RUNNING'else'推理已停止 · 显示与音频待机',word_threshold=d.get('confidence_min',.8),TCN_frame_id_kind=d.get('TCN_frame_id_kind')),metrics=dict(observed_at_ms=observed,camera_fps=self.derived.get('camera_fps'),inference_fps=self.derived.get('inference_fps'),frontend_ms=r.get('PC_frontend_ms'),eof_to_overlay_ms=eof,eof_observed_at_ms=eof_observed,eof_stale_after_ms=3000,eof_metric_frame_id=ack.get('source_frame_id'),eof_metric_scope='源EOF至DRM扫描确认，面板光学延迟另计',word=word.get('gesture'),confidence=word.get('confidence'),TCN_state=r.get('TCN_state')),links=list(self.link_rows.values()),boards=[copy.deepcopy(self.board_rows.get(role,dict(id=role,label=v[0],role=v[1],status='connecting',observed_at_ms=None,power_w=None,power_source='等待传感器发现',temp_c=None)))for role,v in ROLE.items()],pose=dict(observed_at_ms=observed,frame_id=frame_id,width=800,height=480,coordinates='image_px_unmirrored',body=body,hands=hands,person_box=box),audio=self.audio_stream.snapshot(),speech=self.b_speech,events=list(self.events)[-30:])
   # Optional real external meter feed: source and sample timestamp are required.
   ext=read_json(RUN/'external_power_actual.json')
   if ext:
    for item in result['boards']:
     v=ext.get(item['id'],{});stamp=v.get('sample_time_unix_ms');watts=v.get('watts');source=v.get('source')
     if number(stamp)and 0<=NOW()-stamp<=3000 and number(watts)and 0<=watts<=300 and isinstance(source,str)and source.strip():item.update(power_w=watts,power_source=source,power_observed_at_ms=stamp)
   return copy.deepcopy(result)
class Handler(http.server.SimpleHTTPRequestHandler):
 def __init__(self,*a,**kw):super().__init__(*a,directory=str(ROOT/'web'),**kw)
 def end_headers(self):
  self.send_header('Cache-Control','no-store');super().end_headers()
 def log_message(self,*args):pass
 def handle(self):
  try:super().handle()
  except(BrokenPipeError,ConnectionResetError,TimeoutError):pass
 def do_POST(self):
  if self.path!='/api/shutdown' or not hmac.compare_digest(self.headers.get('X-Monitor-Token',''),self.server.shutdown_token):self.send_error(403);return
  self.send_response(200);self.send_header('Content-Length','0');self.end_headers();self.server.engine.stop.set();threading.Thread(target=self.server.shutdown,daemon=True).start()
 def do_GET(self):
  path=urllib.parse.urlsplit(self.path).path
  if path=='/api/audio':
   raw=json.dumps(self.server.engine.audio_stream.snapshot(),ensure_ascii=False,allow_nan=False).encode('utf-8');self.send_response(200);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw);return
  if path=='/api/state':
   try:payload=self.server.engine.snapshot();raw=json.dumps(payload,ensure_ascii=False,allow_nan=False).encode('utf-8');status=200
   except Exception as exc:raw=json.dumps(dict(schema_version=1,updated_at_ms=NOW(),error=type(exc).__name__+': '+str(exc)),ensure_ascii=False).encode('utf-8');status=503
   self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw);return
  if path=='/api/health':
   raw=b'{"status":"ok","numeric_only":true}';self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw);return
  if path not in('/','/index.html','/styles.css','/app.js','/favicon.ico'):
   self.send_error(404);return
  super().do_GET()
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--port',type=int,default=8765);a=ap.parse_args();engine=Engine();server=http.server.ThreadingHTTPServer(('127.0.0.1',a.port),Handler);server.daemon_threads=True;server.engine=engine;server.shutdown_token=secrets.token_hex(24);receipt=dict(shutdown_token=server.shutdown_token,pid=os.getpid(),url='http://127.0.0.1:'+str(a.port),root=str(ROOT),started_at_ms=NOW(),bind='127.0.0.1',camera_pixels_accessed=False,board_control_actions=False);(RUN/'server_actual.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8');engine.start();print(json.dumps(receipt,ensure_ascii=False),flush=True)
 try:server.serve_forever(poll_interval=.3)
 except KeyboardInterrupt:pass
 finally:engine.stop.set();engine.audio_stream.close();server.server_close()
if __name__=='__main__':main()
