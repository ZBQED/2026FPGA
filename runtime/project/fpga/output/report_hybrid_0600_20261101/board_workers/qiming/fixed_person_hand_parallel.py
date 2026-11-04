"""Finite exact comparison of serial vs shared-FD Person/Hand scheduling on Q."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import hashlib,json,os,signal,threading,time,traceback
import numpy as np

def run(root,cfg):
    def stop(*args):raise InterruptedError('Stop after the current bounded native call')
    signal.signal(signal.SIGTERM,stop)
    r=dict(status='FIXTURE_PERSON_HAND_PARALLEL_RUNNING',rows=[],errors=[],actual_NN_PL_RUN=0,TCN_RUN=0,camera_opened=False,full_frame_acceptance=False)
    def save():
        p=root/'rpc_actual.json.tmp';p.write_text(json.dumps(r,separators=(',',':')));p.replace(root/'rpc_actual.json')
    model=clock=pool=None;affinity=None
    try:
        assert Path('/proc/sys/kernel/random/boot_id').read_text().strip()==cfg['boot_id']
        for name,digest in json.loads((root/'package_manifest.json').read_text()).items():assert hashlib.sha256((root/name).read_bytes()).hexdigest()==digest,name
        admission=json.loads((root/'person_raw/shared_admission.json').read_text());assert admission['status']=='Q_PERSON_HAND_TCN_SHARED_SINGLE_FD_PASS'
        for name,digest in admission['qualified_files'].items():assert hashlib.sha256((root/name).read_bytes()).hexdigest()==digest,name
        from shared_perception_tcn import SharedPerceptionTCN,device_fds
        import qualified_clock
        model=SharedPerceptionTCN(root,cfg['session_id'],person_fpga=True)
        clock=qualified_clock.prepare(root);qualified_clock.fast(clock)
        pinned=cfg['fixture_kind'].endswith('_pinned');affinity=os.sched_getaffinity(0);cores=sorted(affinity)
        if pinned:
            assert len(cores)>=2,'Two allowed Q cores required';os.sched_setaffinity(0,{cores[0]})
        r.update(thread_pinning=pinned,original_thread_affinity=cores,person_thread_affinity=sorted(os.sched_getaffinity(0)))
        with np.load(root/'full_palm/fixture.npz',allow_pickle=False)as f:persons=f['inputs'].copy()
        with np.load(root/'full_hand/full_hand_fixture.npz',allow_pickle=False)as f:hands=f['inputs'].copy();hand_gold=f['expected_heads'].copy()
        gold=json.loads((root/'person_raw/shared_references.json').read_text())
        tcn_hash=hashlib.sha256(model.mapping[:6293312]).hexdigest();pool=ThreadPoolExecutor(max_workers=1)
        constants={name:hashlib.sha256(model.mapping[row['base']:row['base']+row['constant_bytes']]).hexdigest()for name,(_,row)in model.models.items()}
        for repeat in range(3):
            for i in range(3):
                j=(i+repeat)%3;px=persons[i];hx=hands[j]
                assert hashlib.sha256(px.tobytes()).hexdigest()==gold[str(i)]['input_sha256']
                begin=time.monotonic_ns();p0,ps0=model.person.infer(px);h0,hs0=model.infer('full_hand',hx);serial=time.monotonic_ns()-begin
                r['actual_NN_PL_RUN']+=ps0['PL_jobs']+hs0['PL_jobs']
                assert hashlib.sha256(p0.tobytes()).hexdigest()==gold[str(i)]['heads_sha256'];np.testing.assert_allclose(h0,hand_gold[j],rtol=0,atol=2e-6)
                barrier=threading.Barrier(2)
                def hand():
                    if pinned:os.sched_setaffinity(0,{cores[1]})
                    barrier.wait(timeout=5);started=time.monotonic_ns();out,stats=model.infer('full_hand',hx)
                    return out,stats,started,time.monotonic_ns()
                begin=time.monotonic_ns();future=pool.submit(hand);barrier.wait(timeout=5)
                person_begin=time.monotonic_ns();p1,ps1=model.person.infer(px);person_end=time.monotonic_ns();h1,hs1,hand_begin,hand_end=future.result(timeout=10);parallel=time.monotonic_ns()-begin
                r['actual_NN_PL_RUN']+=ps1['PL_jobs']+hs1['PL_jobs']
                assert np.array_equal(p0,p1)and np.array_equal(h0,h1),'Concurrent outputs differ'
                assert max(person_begin,hand_begin)<min(person_end,hand_end),'Calls did not overlap'
                assert hashlib.sha256(model.mapping[:6293312]).hexdigest()==tcn_hash,'TCN arena changed'
                assert constants=={name:hashlib.sha256(model.mapping[row['base']:row['base']+row['constant_bytes']]).hexdigest()for name,(_,row)in model.models.items()}
                model.guards();assert model.person.api.yf2_fpga_guards()==0 and device_fds()==[model.fd]
                r['rows'].append(dict(repeat=repeat,person_sample=i,hand_sample=j,serial_ns=serial,parallel_ns=parallel,person=ps1,hand=hs1,heads_exact=True,TCN_arena_unchanged=True,constant_arenas_unchanged=True,single_device_fd=True,call_overlap_ns=min(person_end,hand_end)-max(person_begin,hand_begin)));save()
        r['status']='FIXTURE_PERSON_HAND_PARALLEL_PASS'
    except BaseException as error:r.update(status='FIXTURE_PERSON_HAND_PARALLEL_FAILED',traceback=traceback.format_exc());r['errors'].append(str(error))
    finally:
        if pool:pool.shutdown(wait=True)
        if model:model.close()
        if clock:qualified_clock.restore(clock)
        if affinity is not None:os.sched_setaffinity(0,affinity)
        r['all_device_fds_closed']=not any(p.exists()and os.path.realpath(str(p))=='/dev/gesture-i8-pl0'for p in Path('/proc/self/fd').iterdir());save()
    if r['errors']or not r['all_device_fds_closed']:raise RuntimeError('Person/Hand shared scheduling comparison failed')
