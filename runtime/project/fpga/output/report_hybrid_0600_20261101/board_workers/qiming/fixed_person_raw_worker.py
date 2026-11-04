"""Board CPU oracle vs all 79 PL convolutions on three unchanged frozen tensors."""
from pathlib import Path
import ctypes as C,hashlib,json,os,signal,time,traceback
import numpy as np


def run(root,cfg):
    def stop(*args):raise InterruptedError('Stop after finite native call')
    signal.signal(signal.SIGTERM,stop)
    r=dict(status='FIXTURE_PERSON_RAW_RUNNING',rows=[],errors=[],actual_NN_PL_RUN=0,board_PS_reference_calls=0,
           camera_opened=False,TCN_RUN=0,full_frame_acceptance=False,accuracy_acceptance=False,
           input_scope='three original frozen Palm INT8 tensors reused only for YOLO arithmetic validation; no changed fixtures')
    def save():
        p=root/'rpc_actual.json.tmp';p.write_text(json.dumps(r,separators=(',',':')));os.replace(p,root/'rpc_actual.json')
    api=clock=hand=owner=None
    try:
        assert Path('/proc/sys/kernel/random/boot_id').read_text().strip()==cfg['boot_id']
        for name,digest in json.loads((root/'package_manifest.json').read_text()).items():assert hashlib.sha256((root/name).read_bytes()).hexdigest()==digest,name
        shared=cfg.get('peer_board')=='pynq'
        balanced=cfg['fixture_kind']=='person_palm_hand'
        if not shared:
            import qualified_clock
            clock=qualified_clock.prepare(root);qualified_clock.fast(clock)
        api=C.CDLL(str(root/'person_raw/libyf2_raw_pl.so'))
        api.yf2_pc_infer_quantized.argtypes=[C.c_void_p];api.yf2_pc_copy_workspace.argtypes=[C.c_void_p];api.yf2_pc_copy_heads.argtypes=[C.c_void_p]
        api.yf2_fpga_open_at.argtypes=[C.c_int,C.c_uint32];api.yf2_fpga_stats.argtypes=[C.c_void_p]
        assert api.yf2_pc_input_size()==192 and api.yf2_pc_workspace_bytes()==1750972
        if shared:owner=os.open('/dev/gesture-i8-pl0',os.O_RDWR)
        rc=api.yf2_fpga_open_at(owner if shared else -1,0);assert rc==0,('open',rc)
        r['DMA_region_bytes']=api.yf2_fpga_pool_used()
        if shared:
            assert r['DMA_region_bytes']<7<<20
            from full_hand_runtime import FullHand
            if balanced:
                from resident_models import ResidentModels
                assert r['DMA_region_bytes']<json.loads((root/'shared_workspace/manifest.json').read_text())['boundary_guard']
                hand=ResidentModels(root,workspace=True,parent_fd=owner)
                constants={row['model']:hashlib.sha256(hand.mapping[row['base']:row['base']+row['constant_bytes']]).hexdigest()for row in hand.layout}
            else:hand=FullHand(root/'full_hand',parent_fd=owner);hand.trace(False)
            with np.load(root/'full_hand/full_hand_fixture.npz',allow_pickle=False)as f:hand_inputs=f['inputs'].copy();hand_gold=f['expected_heads'].copy()
        with np.load(root/'full_palm/fixture.npz',allow_pickle=False) as f:inputs=f['inputs'].copy();palm_gold=f['expected_heads'].copy()
        layers=json.loads((root/'person_raw/layers.json').read_text());expected=np.empty(1750972,np.int8);actual=np.empty_like(expected)
        head_count=sum(int(np.prod(l['shape']))for l in layers if l['name']in('Conv_256','Conv_257','Conv_258','Conv_259','Conv_260','Conv_261'))
        assert head_count>0;heads=np.empty(head_count,np.int8);gold=np.empty_like(heads)
        def stats():
            v=(C.c_uint64*7)();assert api.yf2_fpga_stats(v)==7;return list(v)
        for sample,x in enumerate(inputs[:3]):
            x=np.ascontiguousarray(x);assert x.size==192*192*3
            assert api.yf2_fpga_enable(0)==0 and api.yf2_pc_clear_workspace(90)==0
            t=time.monotonic_ns();assert api.yf2_pc_infer_quantized(x.ctypes.data)==0;ps=time.monotonic_ns()-t;r['board_PS_reference_calls']+=1
            assert api.yf2_pc_copy_workspace(expected.ctypes.data)==expected.size;n=api.yf2_pc_copy_heads(gold.ctypes.data);assert 0<n<=heads.size
            assert api.yf2_fpga_enable(1)==0
            for repeat in range(2 if balanced else 6):
                assert api.yf2_pc_clear_workspace(90)==0
                before=stats();t=time.monotonic_ns();rc=api.yf2_pc_infer_quantized(x.ctypes.data);elapsed=time.monotonic_ns()-t
                after=stats();delta=[b-a for a,b in zip(before,after)];r['actual_NN_PL_RUN']+=delta[0]
                assert rc==0 and delta[0]==79 and not after[6],('PL execution',rc,delta)
                assert api.yf2_fpga_guards()==0 and api.yf2_pc_copy_workspace(actual.ctypes.data)==actual.size
                assert api.yf2_pc_copy_heads(heads.ctypes.data)==n
                mismatches=int(np.count_nonzero(actual!=expected));head_mismatches=int(np.count_nonzero(heads[:n]!=gold[:n]))
                layer_bad=[l['name']for l in layers if not np.array_equal(actual[l['offset']:l['offset']+int(np.prod(l['shape']))],expected[l['offset']:l['offset']+int(np.prod(l['shape']))])]
                row=dict(sample=sample,repeat=repeat,input_sha256=hashlib.sha256(x.tobytes()).hexdigest(),board_PS_reference_ns=ps,
                         complete_quantized_model_ns=elapsed,stats=delta,workspace_mismatches=mismatches,head_mismatches=head_mismatches,
                         layers_checked=len(layers),bad_layers=layer_bad,heads_sha256=hashlib.sha256(heads[:n].tobytes()).hexdigest())
                r['rows'].append(row);save();assert mismatches==head_mismatches==0 and not layer_bad,row
                if hand:
                    if balanced:
                        palm,palm_stats=hand.infer('full_palm_fused_cached',x);r['actual_NN_PL_RUN']+=palm_stats['PL_jobs']
                        np.testing.assert_allclose(palm,palm_gold[sample],rtol=0,atol=2e-6)
                        row['shared_Palm']=dict(stats=palm_stats,head_max_abs_error=float(abs(palm-palm_gold[sample]).max()))
                        h,hs=hand.infer('full_hand',hand_inputs[sample])
                        assert constants=={v['model']:hashlib.sha256(hand.mapping[v['base']:v['base']+v['constant_bytes']]).hexdigest()for v in hand.layout}
                        hand.guards()
                    else:h,hs=hand.infer(hand_inputs[sample])
                    r['actual_NN_PL_RUN']+=hs['PL_jobs']
                    np.testing.assert_allclose(h,hand_gold[sample],rtol=0,atol=2e-6)
                    assert api.yf2_fpga_guards()==0
                    row['shared_Hand']=dict(stats=hs,head_max_abs_error=float(abs(h-hand_gold[sample]).max()))
        r.update(status='FIXTURE_PERSON_RAW_PASS',DMA_guards_pass=True,person_palm_hand_shared=balanced)
    except BaseException as error:r['status']='FIXTURE_PERSON_RAW_FAILED';r['errors'].append(str(error));r['traceback']=traceback.format_exc()
    finally:
        if hand:hand.close()
        if api:api.yf2_fpga_close()
        if owner is not None:os.close(owner)
        if clock:qualified_clock.restore(clock)
        r['all_device_fds_closed']=not any(p.exists()and os.path.realpath(str(p))=='/dev/gesture-i8-pl0'for p in Path('/proc/self/fd').iterdir());save()
    if r['errors']or not r['all_device_fds_closed']:raise RuntimeError('Person RAW validation failed')
