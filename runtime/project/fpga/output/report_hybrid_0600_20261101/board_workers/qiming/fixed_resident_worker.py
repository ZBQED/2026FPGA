"""Validate alternating Palm/Body/Hand without weight reloads or camera access."""
from pathlib import Path
import hashlib,json,os,signal,time,traceback
import ctypes as C
import importlib.util
import mmap
import numpy as np
from resident_models import ResidentModels


def run(root,cfg):
    def stop(*args):raise InterruptedError('Stop after current native call')
    signal.signal(signal.SIGTERM,stop)
    r=dict(status='FIXTURE_RESIDENT_CHAIN_RUNNING',rows=[],errors=[],actual_NN_PL_RUN=0,TCN_RUN=0,
           camera_opened=False,full_frame_acceptance=False,weight_loads_per_frame=0)
    def save():(root/'rpc_actual.json').write_text(json.dumps(r,separators=(',',':')))
    models=None;clock=None;owner=None;tcn=None;api=None
    fast_add=cfg['fixture_kind']=='resident_workspace_fastadd'
    workspace=cfg['fixture_kind']in('resident_workspace','resident_workspace_fastadd')
    try:
        assert Path('/proc/sys/kernel/random/boot_id').read_text().strip()==cfg['boot_id']
        for name,digest in json.loads((root/'package_manifest.json').read_text()).items():
            assert hashlib.sha256((root/name).read_bytes()).hexdigest()==digest,name
        import qualified_clock
        clock=qualified_clock.prepare(root);qualified_clock.fast(clock)
        fd=None
        if workspace:
            from fixed_full_tcn_worker import device_fds
            probe=os.memfd_create('workspace_fd_probe');os.ftruncate(probe,4096)
            def probe_count():return sum('workspace_fd_probe'in os.readlink(str(p))for p in Path('/proc/self/fd').iterdir()if p.exists())
            before=probe_count()
            with mmap.mmap(probe,4096)as memory:during=probe_count()
            after=probe_count();os.close(probe)
            r['python_mmap_descriptor_probe']=dict(before=before,during=during,after=after)
            assert not device_fds();folder=root/'tcn508a'
            dependency=C.CDLL(str(folder/'runtime/libgesture_tflite_pl_pointwise.so'))
            api=C.CDLL(str(folder/'runtime/libgesture_lite_i8_v12.so'))
            api.gpo_owner_open.argtypes=[];api.gpo_owner_open.restype=C.c_void_p
            api.gpo_owner_close.argtypes=[C.c_void_p];api.gpo_owner_close.restype=C.c_int
            owner=api.gpo_owner_open();assert owner
            assert len(device_fds())==1;fd=device_fds()[0]
            spec=importlib.util.spec_from_file_location('workspace_tcn',folder/'shared_tcn/shared_tcn.py')
            module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
            tcn=module.SharedTCN(api,owner,folder/'shared_tcn/assets');inputs={}
            with np.load(folder/'seven_words.npz',allow_pickle=False)as f:
                for name,width,key in [('primary',96,'primary_input'),('roof',112,'specialist_input')]:
                    x=f[key][0];inputs[name]=(np.ascontiguousarray(np.clip(np.rint(x[:width].T*1024),-32768,32767),np.int16),np.ascontiguousarray(x[width:].T,np.uint8))
            def infer_tcn(name):
                value=tcn.infer(name,*inputs[name]);r['TCN_RUN']+=1;r['actual_NN_PL_RUN']+=value['actual_PL_RUNs']
                assert value['class_index']==10;return value
            baseline={name:infer_tcn(name)for name in ('primary','roof')}
            boundary=json.loads((root/'shared_workspace/manifest.json').read_text())['boundary_guard']
            with mmap.mmap(fd,16<<20,flags=mmap.MAP_SHARED,prot=mmap.PROT_READ)as memory:
                prefix=hashlib.sha256(memory[:boundary]).digest()
        start=time.monotonic_ns();models=ResidentModels(root,halfadd=cfg['fixture_kind']in('resident_halfadd','resident_lut'),palm_lut=cfg['fixture_kind']=='resident_lut',workspace=workspace,parent_fd=fd,fast_add=fast_add);r['startup_ns']=time.monotonic_ns()-start;r['layout']=models.layout
        if fast_add:
            r['phase']='EXHAUSTIVE_Q24_BYTE_PAIRS';save();started=time.monotonic_ns()
            checked=models.models['full_body_channels_cached'][0].fh_fastadd_selftest()
            r['fastadd_selftest']=dict(coefficient_cases=checked,byte_pair_cases=checked*65536,wall_ns=time.monotonic_ns()-started)
            save();assert checked==6370
        if workspace:
            assert hashlib.sha256(models.mapping[:boundary]).digest()==prefix,'Preloading modified TCN arena'
            r['device_descriptors_after_attach']=device_fds();assert r['device_descriptors_after_attach']==[fd];r['live_TCN_RUN']=0
            constants={row['model']:hashlib.sha256(models.mapping[row['base']:row['base']+row['constant_bytes']]).digest()for row in models.layout}
        fixtures={};hashes={};plans={}
        for row in models.layout:
            name=row['model'];source='full_palm' if name.startswith('full_palm') else 'full_body_channels' if name.startswith('full_body') else name
            with np.load(root/source/('full_hand_fixture.npz'if source=='full_hand'else'fixture.npz'),allow_pickle=False) as f:
                fixtures[name]=(f['inputs'].copy(),f['expected_heads'].copy())
            folder=root/('shared_workspace'if workspace else'resident')/name
            plans[name]=json.loads((folder/'hand_plan.json').read_text())
            hashes[name]=json.loads((folder/'layer_hashes.json').read_text())
        for cycle in range(6):
            names=list(models.models)
            if cycle&1:names.reverse()
            for name in names:
                sample=cycle%3;x,expected=fixtures[name];trace=cycle<3
                heads,stats=models.infer(name,x[sample],trace)
                if workspace:assert hashlib.sha256(models.mapping[:boundary]).digest()==prefix,'Perception modified TCN arena'
                if workspace:
                    for row in models.layout:
                        assert hashlib.sha256(models.mapping[row['base']:row['base']+row['constant_bytes']]).digest()==constants[row['model']],'Resident constant bytes changed'
                    r['all_model_constants_unchanged']=True
                r['actual_NN_PL_RUN']+=stats['PL_jobs']
                np.testing.assert_allclose(heads,expected[sample],rtol=0,atol=2e-6 if name=='full_hand'else 2e-5)
                checked=0
                if trace:
                    native_api=models.models[name][0]
                    for index,digest in hashes[name][sample].items():
                        op=plans[name]['ops'][int(index)];y=np.empty(op['n'],np.int8 if op['cfg'][3]else np.int32)
                        assert native_api.fh_copy_tensor(int(index),y.ctypes.data,y.nbytes)==0
                        assert hashlib.sha256(y.tobytes()).hexdigest()==digest,(name,sample,index)
                        checked+=1
                r['rows'].append(dict(model=name,sample=sample,cycle=cycle,trace=trace,integer_outputs_exact=checked,
                                     heads_max_abs_error=float(abs(heads-expected[sample]).max()),**stats))
                save()
            if workspace:
                suffix=hashlib.sha256(models.mapping[boundary:]).digest()
                for profile in ('primary','roof'):
                    value=infer_tcn(profile)
                    for key in ('class_index','logits_int16','probabilities_Q15'):assert value[key]==baseline[profile][key]
                assert hashlib.sha256(models.mapping[boundary:]).digest()==suffix,'TCN modified resident models'
                prefix=hashlib.sha256(models.mapping[:boundary]).digest();assert device_fds()==[fd]
                r['TCN_opposite_arena_and_outputs_exact']=True
        if fast_add:
            name='full_body_channels_cached';fast_api,row=models.models[name]
            baseline_api=C.CDLL(str(root/'shared_workspace'/name/'libfull_hand_pl.so'))
            for symbol in ('fh_attach_at','fh_run','fh_trace','fh_close'):
                getattr(baseline_api,symbol).argtypes=getattr(fast_api,symbol).argtypes
                getattr(baseline_api,symbol).restype=getattr(fast_api,symbol).restype
            try:
                assert baseline_api.fh_attach_at(fd,os.fsencode(root/'shared_workspace'/name/'hand_weights.bin'),row['base'])==0
                r['paired_body_compare']=[];x,gold=fixtures[name]
                for sample in range(3):
                    for repeat in range(4):
                        order=[('baseline',baseline_api),('fastadd',fast_api)]
                        if repeat&1:order.reverse()
                        for label,selected_api in order:
                            models.models[name]=(selected_api,row);heads,stats=models.infer(name,x[sample]);r['actual_NN_PL_RUN']+=stats['PL_jobs']
                            np.testing.assert_allclose(heads,gold[sample],rtol=0,atol=2e-5)
                            assert hashlib.sha256(models.mapping[:boundary]).digest()==prefix
                            r['paired_body_compare'].append(dict(variant=label,sample=sample,repeat=repeat,**stats))
                        save()
            finally:
                models.models[name]=(fast_api,row);assert baseline_api.fh_close()==0
        models.guards();r['cross_model_fences_pass']=True;r['numeric_checks_pass']=True;save()
    except BaseException as error:
        r.update(status='FIXTURE_RESIDENT_CHAIN_FAILED',traceback=traceback.format_exc());r['errors'].append(str(error))
    finally:
        try:
            if models:
                models.close()
                if workspace:
                    r['borrowed_close_preserved_parent_fd']=device_fds()==[fd]
                    if not r['borrowed_close_preserved_parent_fd']:r['errors'].append('Borrowed model close changed owner FD')
        except BaseException as error:r['errors'].append('Models close: '+str(error))
        try:
            if tcn:tcn.close()
        except BaseException as error:r['errors'].append('TCN close: '+str(error))
        try:
            if owner and api.gpo_owner_close(owner):r['errors'].append('TCN owner close failed')
        except BaseException as error:r['errors'].append('Owner close: '+str(error))
        try:
            if clock:qualified_clock.restore(clock)
        except BaseException as error:r['errors'].append('Clock restore: '+str(error))
        r['all_device_fds_closed']=not any(p.exists()and os.path.realpath(str(p))=='/dev/gesture-i8-pl0'for p in Path('/proc/self/fd').iterdir())
        r['status']='FIXTURE_RESIDENT_CHAIN_PASS'if r.get('numeric_checks_pass')and not r['errors']and r['all_device_fds_closed']else'FIXTURE_RESIDENT_CHAIN_FAILED'
        save()
    if r['errors']or not r['all_device_fds_closed']:raise RuntimeError('Resident chain validation failed')
