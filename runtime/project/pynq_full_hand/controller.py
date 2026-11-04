"""Finite Full Hand test from this PYNQ boot's actual Base firmware, then restore."""
from pathlib import Path
import fcntl
import hashlib
import json
import os
import subprocess
import time
import traceback
import raw_window_helpers as s
import b25_context as speech
from metadata_codec import snapshot_pl_metadata

H=Path(__file__).resolve().parent
DT=Path('/sys/kernel/config/device-tree/overlays')/'light_try_full_hand'
MODULE='gesture_pynq_hand_i8'
UNIT='b-speech-standby.service'


def mapped_owners():
    result=[]
    for p in Path('/proc').iterdir():
        if not p.name.isdigit() or int(p.name)==os.getpid():continue
        try:
            if any(tag in (p/'maps').read_text() for tag in ('/dev/mem','/dev/uio','/dev/gesture')):
                result.append(int(p.name))
        except OSError:pass
    return result


def command(*args):
    return subprocess.check_output(args,stderr=subprocess.STDOUT,text=True,timeout=55).strip()


def main():
    os.environ['XILINX_XRT']='/usr';os.umask(0o077)
    from pynq import PL,Clocks
    cfg=json.loads((H/'window_config.json').read_text())
    key=None
    if cfg.get('fixture_kind')in('same_frame_hand','same_frame_perception','same_frame_perception_balanced'):
        import sys
        key=sys.stdin.buffer.read(32);assert len(key)==32
    restore=json.loads((H/'restore_identity.json').read_text())
    r=dict(status='PREFLIGHT',boot_id=s.boot(),session_id=cfg['session_id'],errors=[],actions=[],
           original_service_restored=False,controller_clock_writes=False,default_boot_written=False,
           new_camera_opened=False,new_audio_probe=False)
    def save():s.dump(H/'window_receipt.json',r)
    changed=stopped=attempted=False;firmware=[];metadata=None;context=None;clock=None
    save()
    lock=os.open('/run/lock/pynq-hand-finite-window.lock',os.O_RDWR|os.O_CREAT,0o600)
    try:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        assert os.geteuid()==0 and s.boot()==cfg['boot_id']==restore['boot_id']
        for name,digest in json.loads((H/'package_manifest.json').read_text()).items():
            assert s.sha(H/name)==digest,name
        for name in ('bit','hwh'):assert s.sha(restore[name])==restore[name+'_sha256']
        assert PL.bitfile_name==restore['bit'] and not list(DT.parent.iterdir())
        assert s.module_refs(MODULE) is None and s.module_refs('gesture_body_pw_layer') is None
        assert not Path('/dev/gesture-i8-pl0').exists() and not s.leases()
        q=json.loads((H/'hardware_qualification.json').read_text())
        assert q['compute_clock_hz']==100000000 and q['compute_clock_source']=='FCLK_CLK3'
        assert q['route']['setup_slack_ns']>=0 and q['route']['hold_slack_ns']>=0
        assert q['route']['all_nets_routed'] and q['route']['DRC_errors']==0
        assert '6.6.10-xilinx-v2024.1-g3c0eca68c652'==os.uname().release
        assert s.sha(H/'hardware/candidate.bit')=='8dba7cd2b9fb4e7b53633f7c92cec7db1c1ffa0e65dd6297a16d80015f7880a0'
        for name,path in [('module','hardware/gesture_pynq_hand_i8.ko'),('dtbo','hardware/hand_overlay_100mhz.dtbo')]:
            assert s.sha(H/path)==q['files'][name]['sha256']
        r['compute_clock_mhz']=Clocks.fclk3_mhz
        assert abs(r['compute_clock_mhz']-100)<.01,'Qualified compute clock must already be 100MHz'
        metadata=snapshot_pl_metadata(PL);clock=s.clocks();context=speech.collect_snapshot(s.process)
        assert mapped_owners()==[context['service_process']['pid']],mapped_owners()
        r['before']=dict(clocks=clock,metadata_digest=metadata['digest'],service=context['service_process'],
                         bit=restore['bit'],bit_sha256=restore['bit_sha256'])
        s.dump(H/'entry_metadata.json',metadata);s.dump(H/'entry_service.json',context)
        firmware=[Path('/lib/firmware')/('light_try_'+cfg['session_id']+'_'+name+'.bin') for name in ('candidate','restore')]
        for path,bit in zip(firmware,(H/'hardware/candidate.bit',Path(restore['bit']))):
            assert not path.exists();path.write_bytes(s.bit2bin(bit.read_bytes()))
        speech.verify_snapshot(context,s.process);speech.read_voice_quiet()
        stopped=True;r['original_service_stop_requested']=True;save()
        command('systemctl','stop',UNIT);r['status']='ORIGINAL_SERVICE_STOPPED';save()
        assert s.mainpid(UNIT)==0 and not mapped_owners()
        attempted=True;r['status']='CANDIDATE_LOAD_STARTED';save()
        s.download_bin(firmware[0],clock);changed=True;r['candidate_loaded']=True;save()
        command('/sbin/insmod',str(H/'hardware/gesture_pynq_hand_i8.ko'))
        DT.mkdir();(DT/'dtbo').write_bytes((H/'hardware/hand_overlay_100mhz.dtbo').read_bytes())
        deadline=time.monotonic()+5
        while not Path('/dev/gesture-i8-pl0').exists() and time.monotonic()<deadline:time.sleep(.05)
        assert (DT/'status').read_text().strip()=='applied'
        assert not s.leases() and s.module_refs(MODULE)==0 and s.core_idle()
        r['candidate_info']=s.info(True)
        assert s.clocks()==clock and snapshot_pl_metadata(PL)==metadata
        r['status']='FULL_HAND_RUNNING';save()
        if cfg.get('fixture_kind')in('same_frame_hand','same_frame_perception','same_frame_perception_balanced'):
            if cfg['fixture_kind']!='same_frame_hand':from same_frame_perception_worker import run
            else:from same_frame_hand_worker import run
            run(H,cfg,key)
        elif cfg.get('fixture_kind')in('person_raw','person_palm_hand'):
            from fixed_person_raw_worker import run
            run(H,cfg)
        else:
            from fixed_full_hand_worker import run
            run(H,cfg)
        r['status']='FULL_HAND_FINISHED';save()
    except BaseException as e:
        r['errors'].append(type(e).__name__+': '+str(e));r['traceback']=traceback.format_exc();save()
    finally:
        try:
            assert s.boot()==r['boot_id'],'Board restarted; do not restore a prior boot'
            assert not (attempted and not changed),'Unknown raw download state; preserve for inspection'
            if changed:
                assert not s.leases() and not mapped_owners(),'Owner remains; no detach'
                if s.module_refs(MODULE) is not None:
                    assert s.module_refs(MODULE)==0 and s.core_idle()
                    if DT.exists():DT.rmdir()
                    command('/sbin/rmmod',MODULE)
                assert not Path('/dev/gesture-i8-pl0').exists()
                s.download_bin(firmware[1],clock)
                assert snapshot_pl_metadata(PL)==metadata
            if stopped:
                speech.verify_files(context)
                r['status']='RESTORING_ORIGINAL_SERVICE';save()
                command('systemctl','start',UNIT);deadline=time.monotonic()+65
                while time.monotonic()<deadline:
                    try:
                        current=speech.collect_snapshot(s.process)
                        assert current['service_process']['cmd_sha256']==context['service_process']['cmd_sha256']
                        assert current['tap_source_end_ns']>context['tap_source_end_ns']
                        assert s.clocks()==clock and PL.bitfile_name==restore['bit']
                        after=snapshot_pl_metadata(PL)
                        fields=lambda m:[v for v in m['canonical_fields'][1] if v[0]!=['str','timestamp']]
                        assert fields(after)==fields(metadata)
                        r['restored_service']=current['service_process'];r['restored_metadata_digest']=after['digest']
                        r['metadata_scope']='All fields restored; startup-owned timestamp may advance';break
                    except (AssertionError,ValueError,OSError,subprocess.CalledProcessError):time.sleep(.25)
                else:raise RuntimeError('Original service did not regain its admitted state')
            assert not s.leases() and s.module_refs(MODULE) is None and not DT.exists()
            r['original_service_restored']=True
            r['status']='FIXTURE_PASS_ORIGINAL_RESTORED' if not r['errors'] else 'FIXTURE_FAILED_ORIGINAL_RESTORED'
        except BaseException as e:
            r['status']='BLOCKED_UNHEALTHY_NO_FORCE';r['restore_error']=type(e).__name__+': '+str(e)
        save();os.close(lock)
    return r


if __name__=='__main__':main()
