"""Measured Q reference clock and a bitstream-bound, reversible divider test."""
from pathlib import Path
import hashlib,json

def prepare(root):
    import window_state as s
    before=s.clocks();c=before['0x170']
    assert ((c>>8)&63)==5 and ((c>>20)&63)==2 and ((c>>4)&3)==0
    reference=int.from_bytes(Path('/proc/device-tree/amba/slcr@f8000000/clkc@100/ps-clk-frequency').read_bytes(),'big')
    assert reference==33333333 and not(before['0x108']&0x13)
    pll=reference*((before['0x108']>>12)&127);assert 999000000<pll<1001000000
    q=json.loads((root/'clock_qualification.json').read_text())
    assert q['bit_sha256']==hashlib.sha256((root/'candidate.bit').read_bytes()).hexdigest()
    assert q['route_setup_ns']>=0 and q['route_hold_ns']>=0 and q['pulse_width_ns']>=0
    assert pll/7<=q['max_clock_hz']==150000000
    return dict(before=before,source_reference_hz=reference,PLL_hz=pll,target_hz=pll/7,qualification=q)

def fast(experiment):
    import window_state as s
    from pynq.ps import Clocks
    assert s.core_idle()
    Clocks.set_pl_clk(0,div0=7,div1=1)
    expected=dict(experiment['before']);mask=(63<<8)|(63<<20)
    expected['0x170']=(expected['0x170']&~mask)|(7<<8)|(1<<20)
    actual=s.clocks();assert actual==expected;experiment['running']=actual

def restore(experiment):
    import window_state as s
    from pynq.ps import Clocks
    loaded=[m for m in ('gesture_pl_i8_driver_v17','gesture_pl_i8_driver_v16',s.NEW_MODULE)if s.module_refs(m)is not None]
    assert len(loaded)==1 and not s.leases() and s.module_refs(loaded[0])==0 and s.core_idle()
    Clocks.set_pl_clk(0,div0=7,div1=2);Clocks.set_pl_clk(0,div0=5,div1=2)
    assert s.clocks()==experiment['before'];experiment['restored_exactly']=True
