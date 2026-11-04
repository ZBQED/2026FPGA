"""One bounded ABI31 independent cold window, then explicit original restoration. Default plan only."""

from pathlib import Path

import argparse,hashlib,importlib.util,json,shlex,sys,threading,time

H=Path(__file__).resolve().parent;P=next(p for p in H.parents if p.name=='output')

sys.path.insert(0,str(H.parent/'board_workers/host_support'))

from boardctl import connect

PRIVATE='/opt/gesture-nav-report-hybrid-0600-r1';STATE='/run/gesture-nav-report-hybrid-0600-r1'

OLDSTATE='/run/gesture-nav-report-hybrid-0600-r1-restore';OLD='/opt/gesture-nav-h49-cold'

sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()

def dump(name,v):(H/name).write_text(json.dumps(v,indent=2,ensure_ascii=False),encoding='utf-8')



def module(name,p):

 s=importlib.util.spec_from_file_location(name,p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m



def remote(c,code,payload=None,timeout=35):

 wrapper="import sys,json,io;d=json.load(sys.stdin);sys.stdin=io.StringIO(json.dumps(d['payload']));exec(compile(d['code'],'<bounded-operation>','exec'))"

 i,o,e=c.exec_command('/usr/bin/python3 -B -c '+shlex.quote(wrapper),timeout=timeout)

 i.write(json.dumps(dict(code=code,payload=payload)));i.flush();i.channel.shutdown_write();raw=o.read().decode();err=e.read().decode();rc=o.channel.recv_exit_status()

 if rc:raise RuntimeError('Nav bounded operation failed; no automatic retry/reset; '+err[-600:])

 return json.loads(raw)





STAGE=r'''

from pathlib import Path

import hashlib,json,os,shutil,sys,tarfile

p=json.load(sys.stdin);assert os.geteuid()==0

assert Path('/proc/sys/kernel/random/boot_id').read_text(encoding='utf-8').strip()==p['boot']

sha=lambda q:hashlib.sha256(Path(q).read_bytes()).hexdigest()

for name,d in p['old_SD_pins'].items():assert sha(name)==d

root=Path('/opt/gesture-nav-report-hybrid-0600-r1')

assert not root.exists(),'Never overwrite or repair an existing private packet automatically'

upload=Path(p['upload'])

for n,d in p['files'].items():assert sha(upload/n)==d

sd=Path('/media/sd-mmcblk0p1');assert os.path.ismount(sd)

assert shutil.disk_usage(sd).free>sum((upload/n).stat().st_size for n in p['boot_files'])+(16<<20)

assert shutil.disk_usage(root.parent).free>(128<<20)

root.mkdir(mode=0o700)

with tarfile.open(upload/'nav_yolo_fused31_cold_payload.tar.gz','r:gz')as t:

 for m in t.getmembers():assert m.isfile()and not m.name.startswith('/')and'..'not in Path(m.name).parts

 t.extractall(root)

for q in root.rglob('*'):

 if q.is_file():q.chmod(0o700 if q.name.endswith('_arm')or q.name in('maintenance_init.py','restore_original_init.py','medcomm_touch_ui.realtime')else 0o600)

for name,d in p['boot_files'].items():

 target=Path('/media/sd-mmcblk0p1')/name

 if target.exists():assert sha(target)==d

 else:

  with target.open('xb')as f:f.write((upload/name).read_bytes());f.flush();os.fsync(f.fileno())

 assert sha(target)==d

for name,d in p['old_SD_pins'].items():assert sha(name)==d

print(json.dumps(dict(status='NAV_V18_NEW_PRIVATE_PACKET_AND_NEW_SD_NAMES_STAGED_DEFAULTS_UNCHANGED',boot_id=p['boot'])))

'''



REBOOT=r'''

from pathlib import Path

import hashlib,json,os,subprocess,sys

p=json.load(sys.stdin);assert os.geteuid()==0 and Path('/proc/sys/kernel/random/boot_id').read_text(encoding='utf-8').strip()==p['boot']

for n,d in p['utilities'].items():assert hashlib.sha256(Path(n).read_bytes()).hexdigest()==d

subprocess.run(['/bin/sync'],check=True,timeout=20)

print(json.dumps(dict(status='EXACT_SYNC_RETURNED_ABOUT_TO_EXEC_ONE_STANDARD_REBOOT',boot_id=p['boot'],argv=['/sbin/reboot','-f'])),flush=True)

os.execv('/sbin/reboot',['/sbin/reboot','-f'])

'''



HANDOFF=r'''

from pathlib import Path

import json,os,sys

p=json.load(sys.stdin);assert os.geteuid()==0

assert Path('/proc/sys/kernel/random/boot_id').read_text(encoding='utf-8').strip()==p['receipt']['boot_id']

path=Path(p['path']);assert not path.exists();fd=os.open(str(path),os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)

with os.fdopen(fd,'w')as f:json.dump(p['receipt'],f);f.flush();os.fsync(f.fileno())

print(json.dumps(dict(status='ACTUAL_FRESH_SERIAL_FULL_BIT_PROVENANCE_DELIVERED',boot_id=p['receipt']['boot_id'])))

'''



POLL=r'''

from pathlib import Path

import hashlib,json,sys

p=json.load(sys.stdin);root=Path(p['state']);rows=[json.loads(x)for x in(root/'journal.jsonl').read_text(encoding='utf-8').splitlines()if x]

stop=root/'known_idle_stop.json';actual=root/'yolo_actual.json'

print(json.dumps(dict(boot_id=Path('/proc/sys/kernel/random/boot_id').read_text(encoding='utf-8').strip(),last=rows[-1],

 stop=json.loads(stop.read_text(encoding='utf-8'))if stop.exists()else None,actual=json.loads(actual.read_text(encoding='utf-8'))if actual.exists()else None,

 camera_startup=json.loads((root/'camera_startup_actual.json').read_text(encoding='utf-8'))if(root/'camera_startup_actual.json').exists()else None,

 camera_iic_recovery=json.loads((root/'camera_iic_recovery_actual.json').read_text(encoding='utf-8'))if(root/'camera_iic_recovery_actual.json').exists()else None,

 child_log_files=[dict(name=q.name,bytes=q.stat().st_size,sha256=hashlib.sha256(q.read_bytes()).hexdigest())for q in sorted(root.glob('child_*.log'))]if stop.exists()or rows[-1]['state']=='PRESERVED_HOLD_FAILURE'else [])))

'''



def read_manifest():

 m=json.loads((H/'window_manifest.json').read_text(encoding='utf-8'));assert m['status']=='NAV_YOLO79_REALTIME_WINDOW_PREPARED_NOT_STAGED'

 assert sha(H/'nav_yolo_fused31_cold_payload.tar.gz')==m['payload']['sha256']and sha(H/'serial_commands.json')==m['serial_commands_sha256']

 assert sha(H/'current_restore_baseline.json')==m['baseline_sha256']

 assert sha(H/'fresh_admission.json')==m['fresh_admission_sha256']

 assert m['boot_package_ready']is True

 assert not any('--continuous' in r['argv']for r in json.loads((H/'current_restore_baseline.json').read_text(encoding='utf-8'))['roles'])

 for n,d in m['boot_artifacts'].items():assert sha(H/'boot_artifacts'/n)==d['sha256']

 return m,json.loads((H/'current_restore_baseline.json').read_text(encoding='utf-8'))



def absent_admission(snap,boot):

 assert snap['boot_id']==boot and not snap['proc_scan_errors']

 assert not any('--continuous'in r['argv']for r in snap['roles'])

 owners=[r for r in snap['device_owners']if any(f['target'].startswith('/dev/gesture')for f in r['fds'])or any('/dev/gesture'in m for m in r['device_mappings'])]

 assert not owners

 modules=[row.split()for row in snap['modules']]

 assert not any(row[0]in('gesture_nav_i8_driver_v18','gesture_nav_hand_driver','gesture_nav_yolo_fused_v31','gesture_nav_yolo_raw_v30')for row in modules)

 original=[row for row in modules if row[0]=='gesture_pl_driver'];refs=int(original[0][2])if original else None

 assert refs in(None,0)

 return dict(status='NAV_ONLY_CURRENT_PUBLISHER_ABSENT_NO_GESTURE_LEASE',boot_id=boot,publisher_running=False,publisher_exited=False,original_module_refcnt=refs,original_module_absent=refs is None,gesture_FD_VMA=[],resume_old_pid_forbidden=True,Q_Body_packets_sent=0,fresh_snapshot_monotonic_ns=snap['monotonic_ns'])



def stage(m,before):

 admission=json.loads((H/'fresh_admission.json').read_text(encoding='utf-8'));assert 0<=time.monotonic_ns()-admission['PC_observed_monotonic_ns']<=120_000_000_000,'Fresh stage admission expired'

 c=connect('navigator');upload='/home/root/nav-fused31-stage-'+m['payload']['sha256'][:12]

 try:

  snap=remote(c,(H/'nav_snapshot.py').read_text(encoding='utf-8'));assert snap['boot_id']==before['boot_id']and not snap['proc_scan_errors']

  assert snap['source_files']==before['source_files'] and snap['SD_restore_assets']==before['SD_restore_assets'] and snap['PS_clock_registers']==before['PS_clock_registers'] and snap['whole_FDT_sha256']==before['whole_FDT_sha256']

  assert not any('--continuous' in r['argv']for r in snap['roles'])

  assert sorted((r['pid'],r['start_ticks'],r['argv'])for r in snap['roles'])==sorted((r['pid'],r['start_ticks'],r['argv'])for r in before['roles'])

  # The reviewed baseline is immutable. Refuse stale process identities rather

  # than silently adopting another controller's or user's replacement runner.

  oldpub=[r for r in before['roles']if'--continuous'in r['argv']];newpub=[r for r in snap['roles']if'--continuous'in r['argv']]

  assert len(oldpub)==len(newpub)

  if oldpub:assert len(oldpub)==1 and all(oldpub[0][k]==newpub[0][k]for k in('pid','start_ticks','argv'))

  else:

   dump('current_nav_only_admission.json',absent_admission(snap,before['boot_id']))

  files={'nav_yolo_fused31_cold_payload.tar.gz':H/'nav_yolo_fused31_cold_payload.tar.gz'}

  files.update({n:H/'boot_artifacts'/n for n in m['boot_artifacts']if n.endswith(('.bit','.ub','.scr'))})

  sf=c.open_sftp()

  try:

   sf.mkdir(upload,0o700)

   for n,p in files.items():sf.put(str(p),upload+'/'+n)

  finally:sf.close()

  pins={n:r['sha256']for n,r in before['SD_restore_assets'].items()if r is not None}

  result=remote(c,STAGE,dict(boot=before['boot_id'],upload=upload,old_SD_pins=pins,files={n:sha(p)for n,p in files.items()},boot_files={n:sha(p)for n,p in files.items()if n!='nav_yolo_fused31_cold_payload.tar.gz'}))

  dump('staged_actual.json',result);print(json.dumps(result),flush=True)

 finally:c.close()



def entered(mode,m,before,prior_boot,stop=None):

 sys.path.insert(0,str(H.parent/'dependencies/pyserial'));import serial

 from serial.tools import list_ports

 rows=[p for p in list_ports.comports()if p.device.upper()=='COM5'];assert len(rows)==1 and rows[0].vid==0x1a86 and rows[0].pid==0x7523

 seqmodule=module('nav_v18_serial_gate',P/'nav_h49_normal_entry_v1/serial_gate.py')

 commands=json.loads((H/'serial_commands.json').read_text(encoding='utf-8'));port=serial.Serial(port=None,baudrate=115200,timeout=.1,write_timeout=3);port.dtr=False;port.rts=False;port.port='COM5';port.open()

 conn=connect('navigator');request={};thread=None;result={}

 try:

  if mode=='candidate':

   fresh=remote(conn,(H/'nav_snapshot.py').read_text(encoding='utf-8'));result['publisher_stop']=absent_admission(fresh,prior_boot)

   dump('pre_entry_stop_actual.json',result['publisher_stop'])

  else:

   assert stop and stop['boot_id']==prior_boot and stop['quarantined']is False

   healthy=all(stop.get(k)is True for k in('admission_stopped','all_submitted_ioctls_returned','healthy_known_idle','FD_VMA_closed','driver_normally_unloaded','refcnt_zero_before_unload','module_absent'))

   probe_abort=stop.get('no_neural_START_because_model_never_called')is True and stop.get('actual_hardware_RUN')==0 and stop.get('module_absent')is True and stop.get('FD_VMA_closed')is True and stop.get('healthy_known_idle')is True

   assert healthy or probe_abort,'No restoration from unknown DMA or timeout quarantine'

   current=remote(conn,POLL,dict(state=STATE));assert current['stop']==stop and current['boot_id']==prior_boot

  tag=mode

  logpath=H/(tag+'_serial_actual.raw')

  assert not logpath.exists(),'One serial invocation, no automatic retry'

  with logpath.open('xb')as log:

   seq=seqmodule.Sequence(port,log,commands,mode,'v18_'+str(time.monotonic_ns()),before['network']['eth0_MAC'])

   until=time.monotonic()+.4

   while time.monotonic()<until:seq.read()

   def dispatch():

    nonlocal thread

    assert thread is None

    def run():

     try:

      i,o,e=conn.exec_command('/usr/bin/python3 -B -c '+shlex.quote(REBOOT),timeout=40)

      i.write(json.dumps(dict(boot=prior_boot,utilities={n:before['source_files'][n]['sha256']for n in('/bin/sync','/sbin/reboot')})));i.flush();i.channel.shutdown_write()

      ack=json.loads(o.readline());assert ack['status']=='EXACT_SYNC_RETURNED_ABOUT_TO_EXEC_ONE_STANDARD_REBOOT'and ack['boot_id']==prior_boot

      request.update(status='EXACT_SYNC_RETURNED_ONE_RESET_DISPATCHED',ack=ack)

     except BaseException:request.setdefault('status','RESET_TRANSPORT_AMBIGUOUS_REQUIRE_FRESH_SERIAL')

    thread=threading.Thread(target=run,daemon=True);thread.start()

   def confirmed():assert request.get('status')=='EXACT_SYNC_RETURNED_ONE_RESET_DISPATCHED'

   result.update(seq.run(dispatch,confirmed));thread.join(timeout=1)

   prefix=b'NAV_V18_JOURNAL 'if mode=='candidate'else b'NAV_H49_RESTORE '

   expected='PS_MIO_SSH_READY_AWAIT_HOST_PROVENANCE'if mode=='candidate'else'RESTORE_PS_MIO_SSH_READY_AWAIT_EXPLICIT_ORIGINAL_BIT_PROVENANCE'

   def journals(raw):

    out=[]

    for line in raw.splitlines():

     if not line.startswith(prefix):continue

     try:out.append(json.loads(line[len(prefix):]))

     except(ValueError,UnicodeError):pass

    return out

   raw=seq.until(lambda raw:any(r.get('state',r.get('status'))==expected for r in journals(raw)),90,'OBSERVED_NEW_PRIVATE_PID1_MIO_SSH_AWAIT_HANDOFF')

   boot=next(r['boot_id']for r in reversed(journals(raw))if r.get('state',r.get('status'))==expected);assert boot!=prior_boot

  dump(tag+'_reset_actual.json',request)

  proof=dict(result,reset_entry_kind='NORMAL_SYSTEM_SOFT_RESET_OBSERVED_FRESH_UBOOT_EXPLICIT_FULL_BIT',physical_POR_proven=False,physical_POR_and_serial_entry_confirmed=False,

   system_reset_kernel_review_sha256='b19d494b302d144d83c9f2a7f56c7e4576747f7d5c7ceecffbb97875f5b744fc',standard_reboot_requested_once=True,

   prior_boot_id=prior_boot,boot_id=boot,serial_transcript_sha256=sha(logpath),normal_reset_request_receipt_sha256=sha(H/(tag+'_reset_actual.json')))

  if mode=='candidate':

   cfg_member='candidate_bindings.json'

   import tarfile

   with tarfile.open(H/'nav_yolo_fused31_cold_payload.tar.gz','r:gz')as t:cfg=json.load(t.extractfile(cfg_member))

   proof.update(bit_sha256=cfg['bit_sha256'],FIT_sha256=cfg['FIT_sha256'],root_complete_trial_reviewed=True)

   path=STATE+'/host_handoff.json'

  else:

   import tarfile

   with tarfile.open(H/'nav_yolo_fused31_cold_payload.tar.gz','r:gz')as t:cfg=json.load(t.extractfile('candidate_bindings.json'))

   proof.update(original_bit_sha256='9ebc8afd90222ed84f8efc55008400bfc409c1efd99c79edeb442f3492be72d5',original_private_FIT_sha256=cfg['restore_FIT_sha256'])

   path=OLDSTATE+'/host_handoff.json'

  conn.close();conn=connect('navigator');remote(conn,HANDOFF,dict(path=path,receipt=proof));dump(tag+'_entry_actual.json',proof)

  return proof

 finally:port.close();conn.close()



def collect_raw_counters(c,actual,boot):

 assert actual and len(actual['rounds'])==3

 result=dict(status='COLLECTING_REAL_NAV_RAW_COUNTERS_BEFORE_RESTORE',boot_id=boot,source='Real remote files written by measured worker; never regenerated from JSON',before_restore=True,rows=[])

 sf=c.open_sftp()

 try:

  for ordinal,row in enumerate(actual['rounds']):

   desc=row['per_layer_counter_binary'];name='layer_delta_%02d.u64'%ordinal;remote_path=STATE+'/'+name;assert desc['path']==remote_path and desc['shape']==[79,16] and desc['dtype']=='uint64'

   with sf.open(remote_path,'rb')as stream:raw=stream.read(79*16*8+1)

   assert len(raw)==79*16*8 and hashlib.sha256(raw).hexdigest()==desc['sha256'];local=H/name;assert local.write_bytes(raw)==len(raw) and sha(local)==desc['sha256']

   result['rows'].append(dict(index=ordinal,frame_id=row['frame_id'],remote_path=remote_path,local_path=str(local),bytes=len(raw),sha256=sha(local),downloaded_real_bytes=True))

  result['status']='ALL3_REAL_RAW_COUNTERS_DOWNLOADED_HASH_VERIFIED_BEFORE_RESTORE'

 finally:sf.close()

 dump('raw_counter_collection_actual.json',result)

 return result



def collect_failure_child_logs(c,row):

 result=dict(status='COLLECTING_ACTUAL_CHILD_LOGS_BEFORE_RESTORE',boot_id=row['boot_id'],before_restore=True,rows=[]);target=H/'failed_child_logs';target.mkdir(exist_ok=True);sf=c.open_sftp()

 try:

  assert len(row['child_log_files'])<=32

  for desc in row['child_log_files']:

   name=desc['name'];assert Path(name).name==name and name.startswith('child_')and name.endswith('.log')and 0<=desc['bytes']<=1048576

   with sf.open(STATE+'/'+name,'rb')as stream:raw=stream.read(1048577)

   assert len(raw)==desc['bytes'] and hashlib.sha256(raw).hexdigest()==desc['sha256'];path=target/name

   with path.open('xb')as stream:assert stream.write(raw)==len(raw)

   assert sha(path)==desc['sha256'];result['rows'].append(dict(remote=STATE+'/'+name,local=str(path),bytes=len(raw),sha256=desc['sha256'],downloaded_real_bytes=True))

  result['status']='ACTUAL_CHILD_LOGS_DOWNLOADED_HASH_VERIFIED_BEFORE_RESTORE'

 finally:sf.close();dump('child_failure_log_collection_actual.json',result)

 return result



def candidate_wait(after_monotonic_ns=None):

 c=connect('navigator')

 try:

  end=time.monotonic()+700

  while time.monotonic()<end:

   row=remote(c,POLL,dict(state=STATE));dump('candidate_progress_actual.json',row)

   for name in('camera_startup','camera_iic_recovery'):

    if row.get(name)is not None:dump(name+'_actual.json',row[name])

   if row['stop']:

    dump('yolo_actual.json',row['actual']);dump('known_idle_stop_actual.json',row['stop'])

    if not row['stop'].get('numeric_pass'):

     try:collect_failure_child_logs(c,row)

     except BaseException as e:dump('child_failure_log_collection_actual.json',dict(status='FAILURE_LOG_DOWNLOAD_FAILED_ORIGINAL_RESTORE_STILL_REQUIRED',error=type(e).__name__+': '+str(e),boot_id=row['boot_id'],before_restore=True))

    try:collect_raw_counters(c,row['actual'],row['boot_id'])

    except BaseException as e:dump('raw_counter_collection_actual.json',dict(status='RAW_COUNTER_DOWNLOAD_FAILED_NOT_ACCEPTABLE_RESTORE_STILL_REQUIRED',error=type(e).__name__+': '+str(e),boot_id=row['boot_id'],before_restore=True))

    return row['stop']

   if row['last']['state']=='PRESERVED_HOLD_FAILURE'and(after_monotonic_ns is None or row['last']['monotonic_ns']>after_monotonic_ns):

    try:collect_failure_child_logs(c,row)

    except BaseException as e:dump('child_failure_log_collection_actual.json',dict(status='FAILURE_LOG_DOWNLOAD_FAILED_HOLD_RETAINED',error=type(e).__name__+': '+str(e),boot_id=row['boot_id'],before_restore=True))

    raise RuntimeError('Nav candidate retained failure; inspect candidate_progress_actual.json and downloaded child logs; no blind restore')

   time.sleep(2)

  raise RuntimeError('Nav candidate finite deadline; preserve unknown resources, no force reset')

 finally:c.close()



def restore_wait_and_verify(before,proof,stop):

 c=connect('navigator')

 try:

  code="from pathlib import Path\nimport json\np=Path('/run/gesture-nav-report-hybrid-0600-r1-restore/journal.jsonl');r=[json.loads(x)for x in p.read_text(encoding='utf-8').splitlines()if x];print(json.dumps({'last':r[-1]}))"

  end=time.monotonic()+100

  while time.monotonic()<end:

   row=remote(c,code)['last']

   if row['status']=='ORIGINAL_BIT_PRIVATE_FUNCTIONAL_RESTORATION_READY_REQUIRE_ROOT_INDEPENDENT_AUDIT':break

   time.sleep(2)

  else:raise RuntimeError('Original independent restore not READY; no success based on reboot return')

  # PrivatePID1 intentionally does not run rcS. Restore only the exact existing

  # local FAT mount before verifying unchanged recovery/default files.

  mountcode="from pathlib import Path\nimport hashlib,json,os,subprocess,sys\np=json.load(sys.stdin);assert hashlib.sha256(Path('/bin/mount').read_bytes()).hexdigest()==p['mount_sha'];m=p['mounts'];assert len(m)==1 and m[0][0]=='/dev/mmcblk0p1' and m[0][2]=='vfat';d,t,k,o=m[0];Path(t).mkdir(parents=True,exist_ok=True);current=[r.split()[:4]for r in Path('/proc/mounts').read_text(encoding='utf-8').splitlines()if r.split()[0]==d and r.split()[2]=='vfat'];\nif not current:subprocess.run(['/bin/mount','-t',k,'-o',o,d,t],check=True,timeout=12)\ncurrent=[r.split()[:4]for r in Path('/proc/mounts').read_text(encoding='utf-8').splitlines()if r.split()[0]==d and r.split()[2]=='vfat'];assert current==m;print(json.dumps({'original_SD_mount_restored':True}))"

  remote(c,mountcode,dict(mounts=before['SD_mounts'],mount_sha=before['source_files']['/bin/mount']['sha256']))

  publishers=[r for r in before['roles']if'--continuous'in r['argv']];assert not publishers

  dump('publisher_deferred_actual.json',dict(publisher_currently_running=False,publisher_not_started=True,formal_integration_not_authorized=True,Nav_restore_boot_id=proof['boot_id']))

  a=remote(c,(H/'nav_snapshot.py').read_text(encoding='utf-8'));time.sleep(.7);b=remote(c,(H/'nav_snapshot.py').read_text(encoding='utf-8'))

  assert a['boot_id']==b['boot_id']==proof['boot_id']and not b['proc_scan_errors']

  assert a['camera']and b['camera']and b['camera']['sequence']!=a['camera']['sequence']and[b['camera'][k]for k in('width','height','stride')]==[800,480,2400]

  semantic_inputs=lambda v:sorted(json.dumps(x,sort_keys=True)for x in v.values())

  assert b['HDMI']==before['HDMI']and b['framebuffers']==before['framebuffers']and semantic_inputs(b['input_devices'])==semantic_inputs(before['input_devices'])

  assert b['sound_cards']==before['sound_cards']and b['sound_pcm']==before['sound_pcm']

  assert b['PS_clock_registers']==before['PS_clock_registers']

  assert all(b['source_files'][n]==v for n,v in before['source_files'].items())

  assert b['SD_restore_assets']==before['SD_restore_assets']

  old=[r['argv']for r in before['roles']if'--continuous'not in r['argv']];new=[r['argv']for r in b['roles']if'--continuous'not in r['argv']]

  assert sorted(old)==sorted(new)

  result=dict(status='NAV_YOLO79_TRUE_INTEGER_AND_EXPLICIT_ORIGINAL_BIT_VIDEO_INPUT_AUDIO_STATE_RESTORED'if stop.get('numeric_pass')else'NAV_ORIGINAL_VIDEO_INPUT_AUDIO_STATE_RESTORED_AFTER_QUIET_CANDIDATE_FAILURE',diagnostic_YOLO79_numeric_pass=stop.get('numeric_pass',False),

   observed_original_full_bit_loadb=True,original_loaded_bit_proof=proof,camera_advances_after_restore=True,HDMI_EDID_framebuffer_state_exact=True,input_device_names_capabilities_exact=True,

   audio_process_device_state_exact=True,PS_clock_registers_exact=True,physical_touch_or_acoustic_output_not_claimed=True,publisher_not_started=not bool(publishers),

   original_11_nonpublisher_role_commands_restored=True,publisher_deferred_by_formal_integration_hold=not bool(publishers),publisher_restarted_new_PID=bool(publishers),default_boot_and_source_files_unchanged=True,after=b,HDMI_latency_included=False)

  dump('window_restored_actual.json',result);print(json.dumps({k:v for k,v in result.items()if k not in('after','original_loaded_bit_proof')},ensure_ascii=False),flush=True)

  return result

 finally:c.close()



def main():

 ap=argparse.ArgumentParser();ap.add_argument('action',choices=('plan','stage','cycle','restore'),nargs='?',default='plan');ap.add_argument('--execute',action='store_true');a=ap.parse_args()

 if not a.execute or a.action=='plan':

  print(json.dumps(dict(plan_only=True,action=a.action,SSH_connections=0,hardware_RUN=0,ready=(H/'window_manifest.json').exists(),requires='Current successful collect_baseline, fresh prepare_window, then explicit stage/cycle; timeout resources are retained',scope='approved fixed frame3x79 START and restore; publisher absent; no capture or formal integration'),indent=2));return

 m,before=read_manifest()

 if a.action=='stage':stage(m,before);return

 assert (H/'staged_actual.json').exists()

 if a.action=='cycle':

  assert not (H/'candidate_entry_actual.json').exists(),'No automatic repeated cycle'

  entered('candidate',m,before,before['boot_id']);stop=candidate_wait()

 else:stop=json.loads((H/'known_idle_stop_actual.json').read_text(encoding='utf-8'))

 proof=entered('restore',m,before,stop['boot_id'],stop);restore_wait_and_verify(before,proof,stop)

 if not stop.get('numeric_pass'):raise RuntimeError('Candidate failure retained; original restoration verified; inspect yolo_actual.json')

 collection=json.loads((H/'raw_counter_collection_actual.json').read_text(encoding='utf-8'));assert collection['status']=='ALL3_REAL_RAW_COUNTERS_DOWNLOADED_HASH_VERIFIED_BEFORE_RESTORE' and len(collection['rows'])==3,'Rawcounter evidence failed; originals restored, candidate not accepted'

if __name__=='__main__':main()

