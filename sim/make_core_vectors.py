from pathlib import Path
import argparse,hashlib,json,struct
p=argparse.ArgumentParser()
p.add_argument("output")
a=p.parse_args()
D=Path(a.output).resolve();D.mkdir(parents=True,exist_ok=False)
cases=[('PW16',0,1,5,8,16,1,1,0,0),('DW3x3',1,3,5,8,8,3,3,1,1),('TCN1x3',0,1,7,8,16,1,3,0,1)]
info=[]
for case,(name,op,h,w,ci,co,kh,kw,pt,pl) in enumerate(cases):
 x=[(i*7+case*3)%31-15 for i in range(h*w*ci)]
 weight=[(i*5+case)%9-4 for i in range(kh*kw*co*(1 if op else ci))]
 bias=[oc*3-20 for oc in range(co)];out=[]
 for y in range(h):
  for z in range(w):
   for oc in range(co):
    acc=0
    for ky in range(kh):
     for kx in range(kw):
      yy,xx=y+ky-pt,z+kx-pl
      if not (0<=yy<h and 0<=xx<w):continue
      for ic in ([oc] if op else range(ci)):
       wi=(ky*kw+kx)*co+oc if op else ((oc*kh+ky)*kw+kx)*ci+ic
       acc+=(x[(yy*w+xx)*ci+ic]+3)*weight[wi]
    v=acc+bias[oc];prod=v*(1<<30)
    high=-((-prod+1073741823)>>31) if prod<0 else (prod+1073741824)>>31
    out.append(max(-128,min(127,high-3))&255)
 n=len(out);ny=(n+7)//8;mem=bytearray([0xa5])*65536
 def put(addr,b):mem[addr:addr+len(b)]=b
 put(0x1000,bytes(v&255 for v in x));put(0x2000,bytes(v&255 for v in weight))
 put(0x3000,b''.join(struct.pack('<iiii',b,1<<30,0,0)for b in bias))
 cfg=[0x3849504b,2,op,1,h,w,ci,h,w,co,kh,kw,1,1,pt,pl,-3,-3,-128,127,(len(x)+7)//8,(len(weight)+7)//8,ny,2*co,0]+[0]*7
 put(0x5000,struct.pack('<32I',*(v&0xffffffff for v in cfg)))
 (D/f'case{case}_mem.hex').write_text('\n'.join(f'{int.from_bytes(mem[i:i+8],"little"):016x}'for i in range(0,len(mem),8))+'\n')
 expected=bytes(out)+bytes(ny*8-n)
 (D/f'case{case}_expected.hex').write_text('\n'.join(f'{int.from_bytes(expected[i:i+8],"little"):016x}'for i in range(0,len(expected),8))+'\n')
 info.append({'case':case,'name':name,'shape':[h,w,ci,co,kh,kw],'output_bytes':n,'output_words':ny,'reference_sha256':hashlib.sha256(expected).hexdigest()})
(D/'cases.json').write_text(json.dumps(info,indent=2))
