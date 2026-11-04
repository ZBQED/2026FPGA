"""Finite existing-camera Nav -> Q/P test using each board's restore lifecycle."""
from pathlib import Path
import concurrent.futures,hashlib,importlib.util,json,os,secrets,shlex,shutil,subprocess,sys,time,traceback

W=Path(__file__).resolve().parents[1];V=W/'fpga/output/report_hybrid_0600_20261101'


def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


def main():
    assert '--fast-render'not in sys.argv or '--neon-swap'in sys.argv,'Fast rendering requires the selected NEON path'
    with_tcn='--with-tcn'in sys.argv
    balanced='--balanced'in sys.argv
    pc_hands='--pc-hands'in sys.argv
    compact_nav='--compact-nav'in sys.argv
    reuse_roi='--reuse-roi'in sys.argv
    offline_roi='--offline-roi'in sys.argv
    nav_body_native='--nav-body-native'in sys.argv
    late_display='--late-display'in sys.argv
    q_parallel='--q-parallel'in sys.argv
    nav_body_post='--nav-body-post'in sys.argv or nav_body_native
    assert not nav_body_post or (compact_nav and not pc_hands)
    if q_parallel:
        assert nav_body_native and late_display and reuse_roi and not pc_hands
        parallel_proof=json.loads((W/'data/reference/parallel_admission.json').read_text())
        assert parallel_proof['numeric_pass']and parallel_proof['restore']['restored']and parallel_proof['model_result']['thread_pinning']
    assert not offline_roi or (reuse_roi and compact_nav and with_tcn and not pc_hands)
    assert not reuse_roi or (compact_nav and not pc_hands)
    fpga_heads='--fpga-heads'in sys.argv or pc_hands or compact_nav
    pc_front='--pc-front'in sys.argv or fpga_heads
    duration=120 if '--two-minutes'in sys.argv else 60 if '--minute'in sys.argv else 0
    assert not pc_front or(with_tcn and not balanced)
    if balanced:
        assert with_tcn
        proof=json.loads((W/'runs/p_person_palm_hand_validation_20261103.json').read_text())
        assert proof['status']=='P_PERSON_PALM_HAND_SHARED_PASS_RESTORED'
        for path,digest in proof['native_sha256'].items():assert hashlib.sha256(Path(path).read_bytes()).hexdigest()==digest
    if with_tcn:
        assert json.loads((W/'runs/hand21_human_observation_20261103.json').read_text())['hand21_current_session_basic_alignment_accepted']
        proof=json.loads((W/'data/reference/workspace_admission.json').read_text())
        assert proof['status']=='FIXTURE_PASS_ORIGINAL_RESTORED'and proof['model_result']['numeric_checks_pass']
        for row in proof['model_result']['layout']:
            assert hashlib.sha256((W/'models/shared_workspace'/row['model']/'libfull_hand_pl.so').read_bytes()).hexdigest()==row['native_library_sha256']
    subprocess.run([sys.executable,'-B',str(W/'tools/refresh_candidate.py')],check=True,cwd=W)
    session='perception_'+secrets.token_hex(8);key=secrets.token_bytes(32)
    run=W/'runs'/('three_board_perception_'+time.strftime('%Y%m%d_%H%M%S'));run.mkdir()
    r=dict(status='PREPARING',session_id=session,errors=[],PC_core_inference=int(pc_front),PC_Hand_RUN=0,PC_TCN_RUN=0,latency_target_ms=200,full_frame_acceptance=False)
    r['source_scope']='fixed_fixture'if offline_roi else'live_nav_ram'
    def save():(run/'result.json').write_text(json.dumps(r,indent=2)+'\n')
    host=module('three_hand_q',V/'board_workers/qiming/q_host.py')
    phost=module('three_hand_p',W/'tools/run_p_fixture.py');phost.SAME_FRAME=dict(session_id=session,key=key,source_scope='fixed_fixture'if offline_roi else'live_nav_ram',fixture_kind='same_frame_perception_balanced'if balanced else'same_frame_perception')
    nav=module('three_hand_nav',V/'board_workers/host_support/boardctl.py')
    active=None;client=None;pool=concurrent.futures.ThreadPoolExecutor(max_workers=2);pf=None;pc_process=None;pc_log=None
    try:
        # Stage Nav code before taking either compute board's finite lease.
        client=nav.connect('navigator');remote='/run/light_try_'+session
        files={'nav_perception.py':W/'three_board_link/nav_perception.py',
               'rpc_protocol.py':V/'pc_runtime/rpc_protocol.py',
               'timed_camera.py':W/'fpga/output/three_board_fast_v8/capture_timing/tim9/timed_camera.py',
               'libcamera_timed_arm.so':W/'fpga/output/three_board_fast_v8/capture_timing/tim9/libcamera_timed_arm.so',
               'shared_camera.py':W/'fpga/output/gesture_board_deploy_20261022/camera_port/shared_camera.py'}
        if offline_roi:
            import numpy as np
            source=W/'fpga/output/pc_fourth_board_probe/complete120_fixture_20261031/candidate_frame_bgr.npy'
            frame=np.load(source,allow_pickle=False);assert frame.shape==(480,640,3)and frame.dtype==np.uint8
            raw=np.pad(frame,((0,0),(80,80),(0,0))).tobytes()
            target=run/'fixed_frame.bin';target.write_bytes(raw);files['fixed_frame.bin']=target
            r['fixed_frame']=dict(original=str(source),original_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),sha256=hashlib.sha256(raw).hexdigest(),transform='80 black pixels left/right; no resize',camera_used=False);save()
        for name in ('perception_geometry.py','drm_scanout.py','inherited_touch.py','feature_transport.py','stable_hand_roi.py'):files[name]=W/'three_board_link'/name
        if nav_body_native:
            d=W/'pc_accel/body_nav_post_20261103';proof=json.loads((d/'native_full_probe.json').read_text())
            assert proof['status']=='NAV_BODY_LAYOUT_PROBE_DONE'and all(x['exact']for x in proof['probe']['rows']+proof['probe']['blur_checks'])
            assert hashlib.sha256((d/'libbody_post.so').read_bytes()).hexdigest()==proof['library_sha256']
            files['libgaussian3.so']=d/'libbody_post.so';files['native_dark.py']=W/'three_board_link/native_dark.py'
        if '--native-hand-crop'in sys.argv:
            d=W/'nav_preprocess_20261103';proof=json.loads((d/'probe.json').read_text())
            assert proof['status']=='NATIVE_HAND_CROP_EXACT'and proof['probe']['exact_cases']==144
            assert hashlib.sha256((d/'libhand_crop.so').read_bytes()).hexdigest()==proof['library_sha256']
            files['libhand_crop.so']=d/'libhand_crop.so';r['Nav_hand_crop_library_sha256']=proof['library_sha256']
        files['libyf2_geometry.so']=W/'models/person_raw_pl/libyf2_raw_pl.so'
        files['body_plan.json']=W/'models/full_body_channels_cached/hand_plan.json'
        files['body_fixture.npz']=W/'models/full_body_channels/fixture.npz'
        files['body_reference.json']=W/'runs/full_body_channels_reference.json'
        if fpga_heads:
            if compact_nav:
                head_dir=W/'nav_split/compact';check=json.loads((head_dir/'admission.json').read_text())
                assert check['status']=='REUSED_NAV_HEADS_AND_REPARTITIONED_PALM_PASS'and check['new_PL_runs']==0
                assert hashlib.sha256((head_dir/'manifest.json').read_bytes()).hexdigest()==check['manifest_sha256']
                for path,digest in check['original_qualification_files'].items():assert hashlib.sha256(Path(path).read_bytes()).hexdigest()==digest
                manifest=head_dir/'manifest.json'
            else:
                proof=max((W/'runs').glob('nav_output_heads_*'),key=lambda p:p.name)
                check=json.loads((proof/'result.json').read_text());assert check['status']=='NAV_REAL_MODEL_HEADS_PASS_CAMERA_HDMI_UNCHANGED'and check['PL_RUN']==9
                head_dir=W/'nav_split/fused';manifest=proof/'manifest.json'
            files['head_manifest.json']=manifest;files['nav_head_runtime.py']=W/'nav_split/nav_head_runtime.py'
            files['libgesture_tflite_pl.so']=W/'models/tcn508a/minimal/runtime/libgesture_tflite_pl.so'
            for name,m in json.loads(manifest.read_text())['models'].items():
                for j in range(len(m['groups'])):files[name+'_0_group'+str(j)+'.npz']=head_dir/(name+'_0_group'+str(j)+'.npz')
        official=W.parent/'workbuddy_21/data/pp_tinypose_trial_20261024/official'
        for name in ('keypoint_preprocess.py','topdown_postprocess.py'):files[name]=official/name
        for path in (V/'nav_window').glob('*.py'):files.setdefault(path.name,path)
        for name in ('medcomm_touch_ui.realtime','liblive_integer_frame.so','libreport_integer_image.so','runtime_assets.json'):files[name]=V/'nav_window'/name
        if '--notify-ui'in sys.argv:
            d=W/'display_accel_20261103';proof=json.loads((d/'candidate_173421/result.json').read_text())
            assert proof['status']=='OFFLINE_DISPLAY_PASS_RESTORED'and proof['display']['directory_notifications_active']
            digest=hashlib.sha256((d/'medcomm_touch_ui.speed').read_bytes()).hexdigest();assert digest==proof['UI_sha256']
            text=(V/'nav_window/nav_live_display.py').read_text(encoding='utf-8').replace('e0507f9035958a57f3397cf05c692181f21f2f3862bc147989bcc770b1ba9931',digest)
            (run/'notify_display.py').write_text(text,encoding='utf-8');files['nav_live_display.py']=run/'notify_display.py'
            assets=json.loads((V/'nav_window/runtime_assets.json').read_text());assets.update(UI_sha256=digest,scope='Directory-notification UI finite candidate test')
            (run/'notify_assets.json').write_text(json.dumps(assets)+'\n');files['runtime_assets.json']=run/'notify_assets.json'
            files['medcomm_touch_ui.realtime']=d/'medcomm_touch_ui.speed';r['notification_UI_candidate']=digest
        if '--fast-render'in sys.argv:
            assert '--notify-ui'not in sys.argv
            d=W/'display_accel_20261103';assert '--neon-swap'in sys.argv;swap=True
            proof=json.loads((W/'data/reference/swap_admission.json').read_text())
            assert proof['status']=='OFFLINE_DISPLAY_PASS_RESTORED'and all(x['paired_copy_ack'].get('render_equivalence_verified')for x in proof['display']['rows'])
            if swap:assert all(x['paired_copy_ack'].get('rgb_swap_method')=='neon16'for x in proof['display']['rows'])
            binary=d/'attempt10_medcomm_touch_ui.speed';digest=hashlib.sha256(binary.read_bytes()).hexdigest();assert digest==proof['UI_sha256']
            text=(V/'nav_window/nav_live_display.py').read_text(encoding='utf-8').replace('e0507f9035958a57f3397cf05c692181f21f2f3862bc147989bcc770b1ba9931',digest)
            text=text.replace("env['MEDCOMM_V18_POLL_MS']='1'","env['MEDCOMM_V18_POLL_MS']='1';env['MEDCOMM_RENDER_FAST']='1';env['MEDCOMM_RENDER_VERIFY']='0';env['MEDCOMM_FB_NEON']='0'")
            if swap:text=text.replace("env['MEDCOMM_V18_POLL_MS']='1'","env['MEDCOMM_V18_POLL_MS']='1';env['MEDCOMM_SWAP_NEON']='1'")
            (run/'render_display.py').write_text(text,encoding='utf-8');files['nav_live_display.py']=run/'render_display.py'
            assets=json.loads((V/'nav_window/runtime_assets.json').read_text());assets.update(UI_sha256=digest,scope='Pixel-exact batched rendering finite candidate test')
            (run/'render_assets.json').write_text(json.dumps(assets)+'\n');files['runtime_assets.json']=run/'render_assets.json'
            files['medcomm_touch_ui.realtime']=binary;r['fast_render_UI_candidate']=digest
        sources=run/'sources';sources.mkdir()
        for name,path in list(files.items()):
            if path.suffix=='.py':
                shutil.copyfile(path,sources/name);files[name]=sources/name
        r['nav_payload_sha256']={name:hashlib.sha256(path.read_bytes()).hexdigest()for name,path in files.items()};save()
        sf=client.open_sftp()
        try:
            sf.mkdir(remote,0o700)
            for name,path in files.items():
                sf.put(str(path),remote+'/'+name)
                if name=='medcomm_touch_ui.realtime':sf.chmod(remote+'/'+name,0o700)
        finally:sf.close()
        i,o,e=client.exec_command('/usr/bin/python3 -B '+shlex.quote(remote+'/nav_perception.py')+(' --check-offline'if offline_roi else' --check'),timeout=20)
        i.channel.shutdown_write();raw=o.read();err=e.read();code=o.channel.recv_exit_status();i.close();o.close();e.close()
        assert code==0,err.decode(errors='replace')
        r['nav_preflight']=json.loads(raw);save()
        if '--nav-preflight-only'in sys.argv:
            r['status']='NAV_PREFLIGHT_ONLY_PASS';save();print(json.dumps(dict(status=r['status'],run=str(run),preflight=r['nav_preflight'])));return
        qf=pool.submit(host.launch,key,session,source_scope='fixed_fixture'if offline_roi else'live_nav_ram',fixture_kind='same_frame_perception_heads'if fpga_heads else'same_frame_perception_tcn'if with_tcn else'same_frame_perception')
        pf=pool.submit(phost.main)
        active=qf.result(timeout=180);r['q_active']=active;r['status']='NAV_DIRECT_FRAMES_RUNNING';save()
        if pf.done():pf.result()  # Fail before starting Nav if the peer launcher failed.
        if pc_front:
            pc_source=W/'pc_accel'/('split_worker.py'if fpga_heads else'vision_worker.py')
            shutil.copyfile(pc_source,sources/pc_source.name);r['pc_source_sha256']=hashlib.sha256(pc_source.read_bytes()).hexdigest()
            pc_log=(run/'pc_vision_console.log').open('wb')
            pc_process=subprocess.Popen([os.environ.get('MGD_PC_PYTHON',sys.executable),'-B',str(W/'pc_accel'/('split_worker.py'if fpga_heads else'vision_worker.py'))],
                        cwd=W,stdin=subprocess.PIPE,stdout=pc_log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW|subprocess.BELOW_NORMAL_PRIORITY_CLASS)
            if '--pc-p-cores'in sys.argv:
                import psutil
                topology=json.loads((W/'pc_accel/body_nav_post_20261103/cpu_scheduling.json').read_text())['cpu_sets']
                selected=[x for x in topology if x['logical']in(4,6)]
                assert len(selected)==2 and len({x['core']for x in selected})==2 and all(x['group']==0 and x['efficiency']==max(c['efficiency']for c in topology)for x in selected)
                owned=psutil.Process(pc_process.pid);assert pc_process.poll()is None and owned.ppid()==os.getpid()
                r['pc_cpu_affinity_before']=owned.cpu_affinity();owned.cpu_affinity([4,6]);assert owned.cpu_affinity()==[4,6]
            pc_process.stdin.write(json.dumps(dict(session_id=session,key=key.hex(),run=str(run),max_frames=1024 if duration else 48,pc_hands=pc_hands,compact_nav=compact_nav,nav_body_post=nav_body_post)).encode());pc_process.stdin.close()
            import psutil
            r['pc_cpu_affinity']=psutil.Process(pc_process.pid).cpu_affinity()
            r['pc_process_pid']=pc_process.pid;save()
        if '--await-live-start'in sys.argv:
            r['status']='BOARDS_READY_AWAIT_LIVE_START';save();deadline=time.monotonic()+90
            print(json.dumps(dict(status=r['status'],run=str(run))),flush=True)
            while not(run/'start_live').exists():
                if time.monotonic()>deadline:raise TimeoutError('No live start signal within finite board window')
                time.sleep(.2)
            r['status']='NAV_DIRECT_FRAMES_RUNNING';save()
        command='/usr/bin/python3 -B '+shlex.quote(remote+'/nav_perception.py')
        monitor_path=W/'runs/monitor_session.json'
        monitor=dict(status='FPGA_PIPELINE_RUNNING',session_id=session,pipeline_state=remote,owner_pid=os.getpid(),owner_create_time=psutil.Process(os.getpid()).create_time(),run_directory=str(run))
        monitor_tmp=monitor_path.with_suffix('.tmp');monitor_tmp.write_text(json.dumps(monitor)+'\n','utf-8');monitor_tmp.replace(monitor_path)
        i,o,e=client.exec_command(command,timeout=180)
        i.write(json.dumps(dict(session_id=session,key=key.hex(),tcn_enabled=with_tcn,balanced=balanced,pc_front=pc_front,fpga_heads=fpga_heads,pc_hands=pc_hands,reuse_roi=reuse_roi,offline_roi=offline_roi,nav_body_post=nav_body_post,late_display=late_display,q_parallel=q_parallel,overlap_seal='--overlap-seal'in sys.argv,fixed_frame_sha256=r.get('fixed_frame',{}).get('sha256'),duration_s=duration)));i.flush();i.channel.shutdown_write()
        raw=o.read();err=e.read();code=o.channel.recv_exit_status();i.close();o.close();e.close()
        r['nav_returncode']=code;r['nav_stderr']=err.decode(errors='replace')[-2500:]
        if raw:r['nav']=json.loads(raw)
        save();assert code==0,r['nav_stderr']
        assert r['nav']['status']==('THREE_BOARD_PERCEPTION_SCANOUT_PASS_TCN_ENABLED'if with_tcn else'THREE_BOARD_PERCEPTION_SCANOUT_PASS')
        pf.result(timeout=150)
        r['status']='DIRECT_THREE_BOARD_PERCEPTION_PASS_AWAIT_Q_RESTORE'
    except BaseException as error:
        r['status']='FAILED';r['errors'].append(type(error).__name__+': '+str(error));r['traceback']=traceback.format_exc()
        save()
        active=active or getattr(host,'last_owned_active',None)
        if active:r['q_active']=active
        r['q_prepare_outcome']=getattr(host,'last_prepare_outcome',None);save()
    finally:
        if client:client.close()
        if pc_process:
            try:
                if r.get('nav',{}).get('status')=='THREE_BOARD_PERCEPTION_SCANOUT_PASS_TCN_ENABLED':
                    assert pc_process.wait(timeout=15)==0
                    r['pc_vision']=json.loads((run/'pc_vision.json').read_text())
                    assert r['pc_vision']['status']=='PC_VISION_PASS'
                    assert [x['frame_id']for x in r['pc_vision']['rows']]==[x['frame_id']for x in r['nav']['rows']]
                    assert all(x['PC_TCN_RUN']==0 and (pc_hands or x['PC_Hand_RUN']==0)for x in r['pc_vision']['rows'])
                    if pc_hands:assert r['pc_vision']['PC_Hand_RUN']==r['nav']['PC_Hand_RUN']
                elif pc_process.poll()is None:pc_process.terminate();pc_process.wait(timeout=10)
            except BaseException as error:r['errors'].append('PC lifecycle: '+str(error))
            finally:
                if pc_log:pc_log.close()
        if active:
            try:
                deadline=time.monotonic()+150;stopped=False
                while time.monotonic()<deadline:
                    try:
                        state=host.status(active,compact=True);r['q_restore']=state;save()
                        if state.get('restored'):break
                        if state.get('restore_error'):raise RuntimeError('Q restore reported an error')
                        if state.get('alive')and not stopped:r['q_stop']=host.stop(active);stopped=True;save()
                    except Exception as error:
                        r.setdefault('q_recovery_transient_errors',[]).append(str(error));save()
                    time.sleep(1)
                else:raise RuntimeError('Q restore not confirmed')
                if r['status']=='DIRECT_THREE_BOARD_PERCEPTION_PASS_AWAIT_Q_RESTORE':assert state['worker']['status']=='SAME_FRAME_PERCEPTION_PASS'
            except BaseException as error:r['errors'].append('Q restore: '+type(error).__name__+': '+str(error))
        if pf:
            try:pf.result(timeout=240)
            except BaseException as error:r['errors'].append('P lifecycle: '+type(error).__name__+': '+str(error))
            if hasattr(phost.main,'last_run'):
                p_run=phost.main.last_run;r['p_run']=str(p_run);r['p_restore']=json.loads((p_run/'result.json').read_text()).get('state',{}).get('window_receipt.json',{})
        pool.shutdown(wait=True)
        r['boards_restored']=bool((not active or r.get('q_restore',{}).get('restored'))and(not pf or r.get('p_restore',{}).get('original_service_restored')))
        if r['status']=='DIRECT_THREE_BOARD_PERCEPTION_PASS_AWAIT_Q_RESTORE' and not r['errors']:r['status']='DIRECT_THREE_BOARD_PERCEPTION_PASS_BOTH_RESTORED'
        save()
        if 'monitor_path'in locals():
            monitor.update(status='FPGA_PIPELINE_STOPPED'if r['boards_restored']else'FPGA_PIPELINE_RECOVERY_REQUIRED',result_status=r['status']);monitor_path.write_text(json.dumps(monitor)+'\n','utf-8')
    print(json.dumps(dict(status=r['status'],run=str(run),errors=r['errors'])))
    if r['status']!='DIRECT_THREE_BOARD_PERCEPTION_PASS_BOTH_RESTORED':raise SystemExit(1)


if __name__=='__main__':
    import psutil
    queue=None
    try:
        for p in psutil.process_iter(['name','cmdline']):
            if p.info['name'].lower()=='python.exe' and any(str(a).replace('\\','/').lower()==str(W/'tools/continue_single_after_add.py').replace('\\','/').lower() for a in p.info['cmdline']or[]):
                assert not p.children() and p.status()!=psutil.STATUS_STOPPED
                assert json.loads((W/'runs/single_round_continuation.json').read_text())['status']=='WAITING_EXISTING_ADD_ROUTE'
                queue=p;created=p.create_time();p.suspend();break
        main()
    finally:
        if queue:
            assert queue.create_time()==created
            queue.resume()

