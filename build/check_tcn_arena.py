"""Check the fixed TCN templates against the shared DMA arena boundary."""
from pathlib import Path
import re,json,hashlib
ROOT=Path(__file__).resolve().parents[1]
source=ROOT/'src/native/tcn/direct_device.cc';text=source.read_text('utf-8')
assert 'const size_t slot0=64,slot1=(2u<<20)+192;'in text
assert 'job.offset[1]=sizes[1]?(4u<<20)+512:0;'in text
assert 'job.offset[2]=(6u<<20)+768;'in text
specs=[list(map(int,re.findall(r'\d+',v)))for v in re.findall(r'\{\{([^{}]+)\}\}',(ROOT/'src/native/tcn/tcn_policy.inc').read_text())]
assert len(specs)==16 and all(len(c)==32 for c in specs)
end=0
for c in specs:
 ni=c[4]*c[5]*c[6];nw=c[9]*c[10]*c[11]*(c[6]if c[2]==0 else 1);no=c[7]*c[8]*c[9]
 sizes=[(ni+7)&~7,(nw+7)&~7,c[23]*8,(no+7)&~7]
 for first,last in [(64,(2<<20)+192),((2<<20)+192,64)]:
  spans=sorted((a,a+n+64)for a,n in zip([first,(4<<20)+512,(6<<20)+768,last],sizes)if n)
  assert all(a[1]<=b[0]for a,b in zip(spans,spans[1:]))
  end=max(end,max(b for a,b in spans))
manifest=json.loads((ROOT/'runtime/project/models/shared_workspace/manifest.json').read_text('utf-8'))
assert end==manifest['boundary_guard']==6293312
print(json.dumps(dict(status='PASS',templates=len(specs),tcn_end_exclusive=end,direct_source_sha256=hashlib.sha256(source.read_bytes()).hexdigest())))
