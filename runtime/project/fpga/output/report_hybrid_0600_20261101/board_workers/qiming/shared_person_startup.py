"""One finite admission check of relocated Person + Hand + unchanged TCN."""
from pathlib import Path
import hashlib,json,time
import numpy as np
from shared_perception_tcn import device_fds

def validate(model,root):
    root=Path(root);start=time.monotonic_ns();gold=json.loads((root/'person_raw/shared_references.json').read_text());rows=[];runs=0;tcn_runs=0
    with np.load(root/'full_palm/fixture.npz',allow_pickle=False)as f:person_inputs=f['inputs'].copy()
    with np.load(root/'full_hand/full_hand_fixture.npz',allow_pickle=False)as f:hand_inputs=f['inputs'].copy();hand_gold=f['expected_heads'].copy()
    inputs={}
    with np.load(root/'tcn508a/seven_words.npz',allow_pickle=False)as f:
        for name,width,key in [('primary',96,'primary_input'),('roof',112,'specialist_input')]:
            x=f[key][0];inputs[name]=(np.ascontiguousarray(np.clip(np.rint(x[:width].T*1024),-32768,32767),np.int16),np.ascontiguousarray(x[width:].T,np.uint8))
    def tcn(name):
        nonlocal runs,tcn_runs
        v=model.tcn.infer(name,*inputs[name]);assert v['class_index']==10;runs+=v['actual_PL_RUNs'];tcn_runs+=1;return v
    baseline={n:tcn(n)for n in inputs};boundary=6293312
    prefix=hashlib.sha256(model.mapping[:boundary]).digest()
    for sample in range(3):
        x=person_inputs[sample];assert hashlib.sha256(x.tobytes()).hexdigest()==gold[str(sample)]['input_sha256']
        heads,stats=model.person.infer(x);assert hashlib.sha256(heads.tobytes()).hexdigest()==gold[str(sample)]['heads_sha256'];runs+=stats['PL_jobs']
        h,hs=model.infer('full_hand',hand_inputs[sample]);np.testing.assert_allclose(h,hand_gold[sample],rtol=0,atol=2e-6);runs+=hs['PL_jobs']
        assert hashlib.sha256(model.mapping[:boundary]).digest()==prefix
        suffix=hashlib.sha256(model.mapping[boundary:]).digest()
        for name in inputs:
            v=tcn(name)
            for k in('class_index','logits_int16','probabilities_Q15'):assert v[k]==baseline[name][k]
        assert hashlib.sha256(model.mapping[boundary:]).digest()==suffix
        prefix=hashlib.sha256(model.mapping[:boundary]).digest();model.guards();assert model.person.api.yf2_fpga_guards()==0 and device_fds()==[model.fd]
        rows.append(dict(sample=sample,Person=stats,Hand=hs,heads_exact=True,opposite_arenas_unchanged=True))
    return dict(status='Q_PERSON_HAND_TCN_SHARED_SINGLE_FD_PASS',rows=rows,PL_RUN=runs,frozen_TCN_RUN=tcn_runs,live_TCN_RUN=0,wall_ns=time.monotonic_ns()-start,person_base=6293376,person_bytes=model.person.api.yf2_fpga_pool_used())
