"""ABI31 FIT/payload binder: fresh live admission required; no board connection or defaults."""

from pathlib import Path

import argparse,hashlib,importlib.util,io,json,shutil,struct,sys,tarfile,time,zlib

H=Path(__file__).resolve().parent;P=next(p for p in H.parents if p.name=='output');TOP=P/'three_board_fast_v18/nav_hand_split';SOURCE=P/'pc_fourth_board_probe/provided_yolo_delivery_20261030/linux_fused_r1'

sha=lambda b:hashlib.sha256(b).hexdigest()

def load(n,p):

 s=importlib.util.spec_from_file_location(n,p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m

def pin(p):return dict(file=p.name,bytes=p.stat().st_size,sha256=sha(p.read_bytes()))

def walk(v):

 if isinstance(v,dict):

  yield v

  for x in v.values():yield from walk(x)

 elif isinstance(v,list):

  for x in v:yield from walk(x)

def main():

 ap=argparse.ArgumentParser();ap.add_argument('--fresh-admission',type=Path);a=ap.parse_args()

 if a.fresh_admission is None:

  request=dict(status='AWAIT_FRESH_NAV_BASELINE_NO_BOOT_PACKAGE',boot_package_ready=False,stage_allowed=False,board_operations=0,requires='collect_baseline.py --execute once when reachable; then supply its fresh_admission.json')

  (H/'binding_request.json').write_text(json.dumps(request,indent=2)+'\n',encoding='utf-8');print(json.dumps(request,indent=2));return

 selection=json.loads((H/'candidate_software_binding.json').read_text(encoding='utf-8'));assert selection['status']=='ROOT_SELECTED_RT1_DRIVER_AND_NATIVE','Root software selection differs'

 driver_source=SOURCE/selection['driver_directory'];native_source=SOURCE/selection['native_directory'];software_manifest=SOURCE/selection['manifest_file']

 admission=json.loads(a.fresh_admission.read_text(encoding='utf-8'))

 assert admission['status']=='FRESH_NAV_PUBLISHER_ABSENT_GESTURE_IDLE_ADMISSION' and admission['connected'] is True

 assert 0<=time.monotonic_ns()-admission['PC_observed_monotonic_ns']<=120_000_000_000,'Admission is stale; no implicit reconnect or reuse'

 assert a.fresh_admission.resolve().parent==H

 beforepath=H/'current_restore_baseline.json';before=json.loads(beforepath.read_text(encoding='utf-8'));bindings=json.loads((H/'current_original_bindings.json').read_text(encoding='utf-8'))

 assert sha(beforepath.read_bytes())==admission['baseline_sha256'] and sha((H/'current_original_bindings.json').read_bytes())==admission['original_binding_sha256']

 assert before['boot_id']==admission['boot_id'] and not before['proc_scan_errors']

 assert not any('--continuous' in r['argv'] for r in before['roles'])

 assert not any(any(f['target'].startswith('/dev/gesture') for f in r['fds'])or any('/dev/gesture' in m for m in r['device_mappings'])for r in before['device_owners'])

 restore=before['SD_restore_assets']['/media/sd-mmcblk0p1/nav-h49-restore-20261027.bit']

 assert restore and restore['sha256']=='9ebc8afd90222ed84f8efc55008400bfc409c1efd99c79edeb442f3492be72d5' and restore['bytes']==0x3dbb6a,'Original SD restore bit missing or differs'

 assert all(before['SD_restore_assets']['/media/sd-mmcblk0p1/'+n] for n in ('BOOT.BIN','boot.scr','image.ub')),'Default boot assets must exist'

 fresh=True

 qpath=SOURCE/'hardware_r3_burst_full/qualification.hardware_only.json';q=json.loads(qpath.read_text(encoding='utf-8'))

 assert q['qualified_for_bounded_independent_board_window'] and q['numeric_or_latency_qualified'] is False

 assert q['route']['setup_WNS_ns']>=0 and q['route']['hold_WHS_ns']>=0 and q['route']['DRC_errors']==0 and q['original_all222IO_PS_MMCM_clocks_exact']

 bp0=Path(q['bit']['file']);assert sha(bp0.read_bytes())==q['bit']['sha256']

 qualified=json.loads((software_manifest).read_text(encoding='utf-8'))

 assert qualified['qualified']is True and qualified['ABI']==31 and qualified['hardware_qualification_sha256']==sha(qpath.read_bytes())

 assert qualified['bit_sha256']==q['bit']['sha256'] and qualified['hwh_sha256']==q['hwh']['sha256']

 assert sha(Path(q['hwh']['file']).read_bytes())==q['hwh']['sha256']

 assert sha((native_source/'libperson192_navfused_input_i8.so').read_bytes())==qualified['lib_sha256']

 assert sha((driver_source/'gesture_nav_yolo_fused_v31.ko').read_bytes())==qualified['driver_sha256']

 assert sha((SOURCE/'driver/nav_yolo_fused31_proposal.dtb').read_bytes())==qualified['DT_proposal_sha256']

 helper=json.loads((H/'clock_helpers/build_result.json').read_text(encoding='utf-8'))

 profile_check=json.loads((H/'clock_helpers/guard_profile.json').read_text(encoding='utf-8'))

 assert helper['profile']['profile_sha256']==profile_check['profile_sha256']

 for name,row in helper['files'].items():assert sha((H/'clock_helpers'/name).read_bytes())==row['sha256']



 assert before['source_files']['/opt/gesture-nav-h49-cold/cold_bindings.json']['sha256']==bindings['old_network_bindings_source_sha256']

 assert bindings['peripherals']['expected_original_role_commands']==sorted(json.dumps(r['argv'])for r in before['roles'])

 for n,row in bindings['peripherals']['files'].items():assert row==before['source_files'][n]

 (H/'qualified_hardware_binding.json').write_text(json.dumps(dict(status='FUSED31_R2_HARDWARE_BOUND_TO_FRESH_BASELINE_OFFLINE',qualification=str(qpath),qualification_sha256=sha(qpath.read_bytes()),admission_sha256=sha(a.fresh_admission.read_bytes()),bit=q['bit'],hwh=q['hwh'],board_operations=0),indent=2),encoding='utf-8')

 boot=P/'gesture_board_deploy_20261022/deployment/boot_trial_v3';codec=load('nav16_fdt_codec',boot/'fdt_codec.py');sys.modules['fdt_codec']=codec

 fmt=load('nav16_boot_fmt',boot.parent/'boot_trial/prepare_trial.py');patcher=load('nav16_dt_patch',P/'three_board_v4_20261025/optimization_20261025/pl/nav_tile_runtime_v1/prepare_dt.py');encoder=load('nav16_entry_format',TOP/'window/prepare_boot.py')

 fit=codec.Fdt((boot/'trial-cnn-v3-original-kernel-cma128-20261022.ub').read_bytes());base=codec.Fdt((boot/'candidate-system.dtb').read_bytes())

 assert sha(base.blob)=='0fe699b2d36a8802fdbac0f6a7661d4713d946e2d9276a1f5cc7217a87a49c35'

 profile=json.loads((H/'clock_helpers/guard_profile.json').read_text());node='/amba_pl/keypoint-conv@80000000'

 proposal=codec.Fdt((SOURCE/'driver/nav_yolo_fused31_proposal.dtb').read_bytes())

 changes={(node,'compatible'),(node,'reg'),(node,'reg-names'),(node,'gesture,verified-handoff'),(node,'gesture,pool-bytes')}

 assert proposal.get(node,'reg')==struct.pack('>IIII',0x80000000,0x10000,0x80020000,0x10000)

 assert proposal.get(node,'reg-names')==b'pointers\0control\0'

 candidate=proposal.replace({('/chosen','bootargs'):profile['bootargs'].encode()+b'\0'});dt=codec.Fdt(candidate)

 assert {k for k in set(base.props)|set(dt.props)if base.props.get(k)!=dt.props.get(k)or(k in base.props)!=(k in dt.props)}==changes|{('/chosen','bootargs')}

 assert dt.nodes==base.nodes and dt.reserve==base.reserve

 out=H/'boot_artifacts';assert not out.exists(),'Never overwrite a bound cold packet';out.mkdir()

 def make_fit(raw,path):

  ip='/images/fdt@system-top.dtb';blob=fit.replace({(ip,'data'):raw,(fit.image_hash_node(ip),'value'):hashlib.sha256(raw).digest()})

  assert sha(codec.Fdt(blob).get('/images/kernel@1','data'))=='dbcc444a47a6f3f622dee984fdac1c4c266914bed878e471c44d3b9b232d8586'

  path.write_bytes(blob);return path

 def make_script(bp,fp,args,marker,stem):

  fmt.BIT_NAME=bp.name;fmt.FIT_NAME=fp.name;cmd=fmt.commands(dict(crc32='%08x'%(zlib.crc32(fp.read_bytes())&0xffffffff),size_hex=hex(fp.stat().st_size)),dict(crc32='%08x'%(zlib.crc32(bp.read_bytes())&0xffffffff),size_hex=hex(bp.stat().st_size)),args)

  needle='if fpga loadb 0 0x02000000 ${filesize}; then\n          setenv trial_ok 1';assert cmd.count(needle)==1

  cmd=cmd.replace(needle,'if fpga loadb 0 0x02000000 ${filesize}; then\n          echo '+marker+'\n          setenv trial_ok 1')

  cp=out/(stem+'.cmd');sp=out/(stem+'.scr');cp.write_bytes(cmd.encode());sp.write_bytes(fmt.script_image(cmd));return cmd,sp

 stem='nav-report-hybrid-0600-r1-candidate-20261101';bp=out/(stem+'.bit');shutil.copyfile(bp0,bp);fp=make_fit(candidate,out/(stem+'.ub'));(out/(stem+'.dtb')).write_bytes(candidate)

 _,sp=make_script(bp,fp,profile['bootargs'],'NAV16_SPLIT_CANDIDATE_FULL_BIT_LOAD_RETURNED_SUCCESS',stem)

 oldbit=P/'nav_h49_cold_entry_v5/proposed_private_upgrade/boot_files/nav-h49-restore-20261027.bit';assert sha(oldbit.read_bytes())=='9ebc8afd90222ed84f8efc55008400bfc409c1efd99c79edeb442f3492be72d5'

 restoreargs=base.get('/chosen','bootargs').rstrip(b'\0').decode()+' init=/opt/gesture-nav-report-hybrid-0600-r1/restore_original_init.py gesture_nav_yolo_fused31_restore=1'

 restoreraw=base.replace({('/chosen','bootargs'):restoreargs.encode()+b'\0'});assert{k for k in base.props if base.props[k]!=codec.Fdt(restoreraw).props[k]}=={('/chosen','bootargs')}

 rfp=make_fit(restoreraw,out/'nav-report-hybrid-0600-r1-restore-20261101.ub');rcmd,rsp=make_script(oldbit,rfp,restoreargs,'NAV16_SPLIT_ORIGINAL_FULL_BIT_LOAD_RETURNED_SUCCESS','nav-report-hybrid-0600-r1-restore-20261101')

 cut='if test "${trial_ok}" = "1"; then\n  setenv trial_ok 0\n  if fatload mmc 0:1 0x02000000';verify=rcmd[:rcmd.index(cut)]+'''if test "${trial_ok}" = "1"; then

 setenv trial_ok 0

 if fatload mmc 0:1 0x02000000 nav-h49-restore-20261027.bit; then

  if itest.l ${filesize} == 0x3dbb6a; then

   crc32 0x02000000 ${filesize} 0x01f0000c

   if itest.l *0x01f0000c == ${trial_bit_crc}; then setenv trial_ok 1; fi

  fi

 fi

fi

if test "${trial_ok}" = "1"; then echo NAV16_SPLIT_CURRENT_ORIGINAL_RECOVERY_ASSETS_VERIFIED; else echo NAV_H49_RECOVERY_ASSETS_CHECK_FAILED_HOLD_UBOOT; fi

'''

 assert'fpga loadb'not in verify and'bootm'not in verify;vs=out/'nav-report-hybrid-0600-r1-recovery-check.scr';vs.with_suffix('.cmd').write_bytes(verify.encode());vs.write_bytes(fmt.script_image(verify))

 commands=dict(candidate=encoder.entry_line(sp,'NAV16_SPLIT_CANDIDATE_FULL_BIT_LOAD_RETURNED_SUCCESS'),restore=encoder.entry_line(rsp,'NAV16_SPLIT_ORIGINAL_FULL_BIT_LOAD_RETURNED_SUCCESS'),recovery_verify=encoder.entry_line(vs,'unused'))

 commands['recovery_verify']['asset_verified_marker']='NAV16_SPLIT_CURRENT_ORIGINAL_RECOVERY_ASSETS_VERIFIED';(H/'serial_commands.json').write_text(json.dumps(commands,indent=2))

 private_ready_binding=json.loads((H/'nav_ready_private_contract.json').read_text(encoding='utf-8'))

 assert private_ready_binding['original_source_sha256']=='d4aadc1d5888706d48594f50d7f7d431f44abc94ed95509084a7bd47b37aa02c' and sha((H/'nav_ready_private.py').read_bytes())=='b2f56caef4e68c9cfc237e7e1bec81aa8d362251952d5615e325be0bdf852e9e'==private_ready_binding['private_clone_sha256']

 assert private_ready_binding['original_source_changed']is False and private_ready_binding['original_attempted_single_recover_fatal_and_result_READY_logic_byte_exact']is True

 payload={}

 payload['nav_ready_private.py']=(H/'nav_ready_private.py').read_bytes()

 payload['nav_ready_private_contract.json']=(H/'nav_ready_private_contract.json').read_bytes()

 for n in('maintenance_init.py','restore_original_init.py','cold_peripherals_current.py','current_original_bindings.json','nav_snapshot.py','cold_fs.py','cold_network.py','reset_entry.py','original_python_paths.py','clock_observer.py'):payload[n]=(H/n).read_bytes()

 for n in('cold_mode_helper_arm','cold_shadow_reader_arm'):payload['runtime/'+n]=(H/'clock_helpers'/n).read_bytes()

 source=SOURCE

 payload['measure_person_fused.py']=(H/'measure_person_fused.py').read_bytes()

 payload['rpc_protocol.py']=(H/'rpc_protocol.py').read_bytes()

 for name in ('nav_live_display.py','frame_publication.py','integer_image.py','liblive_integer_frame.so','libreport_integer_image.so','medcomm_touch_ui.realtime','runtime_assets.json','nav_demo_common.py','nav_direct_touch.py','evdev_source.py','diagnostic_io.py'):payload[name]=(H/name).read_bytes()

 payload['startup_residency.py']=(H/'startup_residency.py').read_bytes()

 payload['thread_usage_libc.py']=(H/'thread_usage_libc.py').read_bytes()

 payload['candidate_camera_recovery.py']=(H/'candidate_camera_recovery.py').read_bytes()

 lib=native_source/'libperson192_navfused_input_i8.so';payload['native/libperson192_navfused.so']=lib.read_bytes()


 payload['driver/gesture_nav_yolo_fused_v31.ko']=(driver_source/'gesture_nav_yolo_fused_v31.ko').read_bytes()

 payload['qualified_manifest.json']=(software_manifest).read_bytes();assert json.loads(payload['qualified_manifest.json'])['lib_sha256']==sha(lib.read_bytes())

 payload['hardware/qualification.hardware_only.json']=qpath.read_bytes();hwh=Path(q['hwh']['file']);payload['hardware/'+hwh.name]=hwh.read_bytes()

 for name,data in list(payload.items()):

  if name.endswith(('.py','.sh')):payload[name]=data.replace(b'\r\n',b'\n').replace(b'\r',b'\n')

 cfg=dict(root_execution_authorized=True,arm_watchdog=False,model_warmup_RUN=0,expected_complete_frames=None,expected_hardware_RUN=None,approved_frame_input_path=None,realtime_authorized=True,source_scope="actual_TIM9_camera_local_PC_RAM",Q_Body_dependency=False,bootargs=profile['bootargs'],prior_boot_id=before['boot_id'],candidate_script_sha256=sha(sp.read_bytes()),bit_sha256=q['bit']['sha256'],FIT_sha256=sha(fp.read_bytes()),restore_script_sha256=sha(rsp.read_bytes()),restore_FIT_sha256=sha(rfp.read_bytes()),old_cold_bindings_sha256=bindings['old_network_bindings_source_sha256'],payload_files={n:sha(b)for n,b in payload.items()},restore_baseline_sha256=sha(beforepath.read_bytes()))

 cfg['private_nav_ready']=dict(file='nav_ready_private.py',sha256=sha(payload['nav_ready_private.py']),original_source_path=private_ready_binding['original_source_path'],original_source_sha256=private_ready_binding['original_source_sha256'],validated_by='frozen ctor',contract_sha256=sha(payload['nav_ready_private_contract.json']))

 payload['candidate_bindings.json']=json.dumps(cfg,indent=2).encode();tar=H/'nav_yolo_fused31_cold_payload.tar.gz'

 with tarfile.open(tar,'w:gz')as t:

  for n,b in payload.items():m=tarfile.TarInfo(n);m.size=len(b);m.mode=0o700 if n=='medcomm_touch_ui.realtime'else 0o600;m.mtime=0;t.addfile(m,io.BytesIO(b))

 manifest=dict(boot_package_ready=True,fresh_admission_sha256=sha(a.fresh_admission.read_bytes()),status='NAV_YOLO79_REALTIME_WINDOW_PREPARED_NOT_STAGED',private_root='/opt/gesture-nav-report-hybrid-0600-r1',state_root='/run/gesture-nav-report-hybrid-0600-r1',hardware_qualification_sha256=sha(qpath.read_bytes()),payload=pin(tar),boot_artifacts={p.name:pin(p)for p in out.iterdir()},serial_commands_sha256=sha((H/'serial_commands.json').read_bytes()),baseline_sha256=sha(beforepath.read_bytes()),baseline_fresh_for_Nav_only=fresh,publisher_template_historical=False,publisher_running_count_in_fresh_snapshot=sum('--continuous'in r['argv']for r in before['roles']),requires_fresh_current_boot_publisher_and_lease_admission_before_stage=True,Q_Body_legacy_barrier_used=False,approved_fixed_full_frame_Person192_three_calls_only=False,realtime_authorized=True,selected_frame_limit=None,Q_Body_called=False,all_other_FDT_properties_and_FIT_kernel_exact=True,board_actions=0,approved_historical_fixed_frame_uploads=0,current_sensor_image_exports=0,private16_ROI_uploads=0,default_boot_changed=False,original_video_caveats=q['inherited_video_caveats'])

 (H/'window_manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8');print(json.dumps(manifest,indent=2))

if __name__=='__main__':main()

