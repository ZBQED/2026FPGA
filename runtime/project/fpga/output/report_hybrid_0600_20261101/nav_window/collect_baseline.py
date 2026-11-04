"""Exactly one explicit Nav connection for fresh source/restore facts; no hardware changes."""

from pathlib import Path

import argparse,datetime,hashlib,json,shlex,sys,time

H=Path(__file__).resolve().parent;R=next(p.parent for p in H.parents if p.name=='output')

sha=lambda b:hashlib.sha256(b).hexdigest()

def dump(p,v):p.write_text(json.dumps(v,indent=2)+'\n',encoding='utf-8')

def main():

 ap=argparse.ArgumentParser();ap.add_argument('--execute',action='store_true');ap.add_argument('--attempt-dir',type=Path);a=ap.parse_args()

 if not a.execute:print(json.dumps(dict(plan_only=True,SSH_attempts=0,hardware_RUN=0,requires='--execute --attempt-dir uniqueFdirectory'),indent=2));return

 assert a.attempt_dir is not None and a.attempt_dir.resolve().is_relative_to(H.parent.resolve())

 a.attempt_dir.mkdir(exist_ok=True);p=a.attempt_dir/'nav_connection_once_actual.json';assert not p.exists(),'No automatic repeated connection'

 for n in ('fresh_admission.json','window_manifest.json'):

  assert not(H/n).exists(),'Existing admission/package requires explicit new directory, never overwrite'

 template=json.loads((H/'reviewed_source_template.json').read_text(encoding='utf-8'))

 paths=sorted(set(template['peripherals']['files'])|{'/opt/gesture-tcn-20261022/app_runner/run_gesture.py','/opt/gesture-nav-h49-cold/cold_bindings.json'})

 source=(H/'nav_snapshot.py').read_text(encoding='utf-8');source=source[:source.rindex("if __name__=='__main__':")]

 source+='''\nimport sys\nrequest=json.load(sys.stdin)\nSOURCE_FILES=tuple(sorted(set(SOURCE_FILES)|set(request['paths'])))\ns=snapshot()\nprint(json.dumps(s))\n'''

 r=dict(time=datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).isoformat(),attempts=1,role='navigator',read_only=True,hardware_RUN=0,bit_or_driver_or_service_changed=False,sensor_capture_or_export=False,no_automatic_retry=True)

 dump(p,dict(r,status='ATTEMPT_STARTED_DO_NOT_REPEAT'));c=None;t=time.perf_counter_ns()

 try:

  sys.path.insert(0,str(R/'output/three_board_fast_v7'));from boardctl import connect

  c=connect('navigator');r['connected']=True

  wrapper="import sys,json,io;d=json.load(sys.stdin);sys.stdin=io.StringIO(json.dumps(d['payload']));exec(compile(d['code'],'<readonly-baseline>','exec'))";i,o,e=c.exec_command('/usr/bin/python3 -B -c '+shlex.quote(wrapper),timeout=40);i.write(json.dumps(dict(code=source,payload=dict(paths=paths))));i.flush();i.channel.shutdown_write();raw=o.read();rc=o.channel.recv_exit_status()

  if rc:raise RuntimeError('Fresh restore-facts command failed')

  before=json.loads(raw.decode());dump(H/'current_restore_baseline.json',before)

  assert not before['proc_scan_errors'] and not any('--continuous'in r['argv']for r in before['roles'])

  assert not any(any(f['target'].startswith('/dev/gesture')for f in r['fds'])or any('/dev/gesture'in m for m in r['device_mappings'])for r in before['device_owners'])

  for row in before['modules']:

   fields=row.split();assert fields[0]not in('gesture_nav_yolo_fused_v31','gesture_nav_yolo_raw_v30','gesture_nav_i8_driver_v18','gesture_nav_hand_driver')

   if fields[0]=='gesture_pl_driver':assert int(fields[2])==0

  restore=before['SD_restore_assets']['/media/sd-mmcblk0p1/nav-h49-restore-20261027.bit']

  assert restore and restore['sha256']=='9ebc8afd90222ed84f8efc55008400bfc409c1efd99c79edeb442f3492be72d5' and restore['bytes']==0x3dbb6a,'Original SD restore bit missing or differs'

  assert all(before['SD_restore_assets']['/media/sd-mmcblk0p1/'+n] for n in ('BOOT.BIN','boot.scr','image.ub')),'Default boot assets must exist'

  facts=before['source_files'];assert all(facts[n] is not None for n in paths)

  # Historical facts are a reviewed source whitelist, never a boot/PID admission.

  for n,v in template['peripherals']['files'].items():assert facts[n]==v,'Original reviewed peripheral source changed: '+n

  assert facts['/opt/gesture-tcn-20261022/app_runner/run_gesture.py']['sha256']==template['original_path_setup_sha256']

  assert facts['/opt/gesture-nav-h49-cold/cold_bindings.json']['sha256']==template['old_network_bindings_source_sha256']

  assert len(before['roles'])==11 and before['camera'] and before['SD_mounts']

  bindings=dict(status='CURRENT_FRESH_SOURCE_FACTS_NOT_HISTORICAL_ADMISSION',peripherals=dict(root_original_startup_whitelist_reviewed=True,foreground_display_hpd_reviewed=True,files={n:facts[n]for n in template['peripherals']['files']},expected_original_role_commands=sorted(json.dumps(r['argv'])for r in before['roles'])),original_path_setup_sha256=facts['/opt/gesture-tcn-20261022/app_runner/run_gesture.py']['sha256'],old_network_bindings_source_sha256=facts['/opt/gesture-nav-h49-cold/cold_bindings.json']['sha256'],boot_id=before['boot_id'],source='One current read-only SSH connection and exact reviewed path whitelist')

  dump(H/'current_original_bindings.json',bindings)

  admission=dict(status='FRESH_NAV_PUBLISHER_ABSENT_GESTURE_IDLE_ADMISSION',connected=True,boot_id=before['boot_id'],PC_observed_monotonic_ns=time.monotonic_ns(),remote_monotonic_ns=before['monotonic_ns'],baseline_sha256=sha((H/'current_restore_baseline.json').read_bytes()),original_binding_sha256=sha((H/'current_original_bindings.json').read_bytes()),publisher_running=False,gesture_FD_VMA=[],hardware_RUN=0,connection_receipt=str(p))

  dump(H/'fresh_admission.json',admission);r.update(status='CONNECTED_FRESH_BASELINE_AND_IDLE_ADMISSION_SAVED',baseline_saved=True,boot_id=before['boot_id'])

 except Exception as ex:r.update(connected=r.get('connected',False),error_type=type(ex).__name__,error=str(ex),status='UNREACHABLE_NO_RETRY' if not r.get('connected',False)else'CONNECTED_ADMISSION_REFUSED_NO_HARDWARE_ACTION')

 finally:

  if c is not None:c.close()

  r['elapsed_ms']=(time.perf_counter_ns()-t)/1e6;dump(p,r)

 print(json.dumps(r,indent=2))

if __name__=='__main__':main()