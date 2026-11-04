"""Integer coordinate ingress and original local-palm96 / roof-direction112 rules.

Public input: Q16 ROI-relative pixel coordinates, Q15 body confidences, integer
pixel ROI origins and integer microsecond source timestamps. Internal geometry
is Q32; features are Q30 until resampling, then INT16 Q10 (scale1/1024).
This is a new fixed-point frontend, not a claim of FP32 feature bit identity.
"""
_NATIVE_RESAMPLE = None
if '__file__' in globals():
    import ctypes as _ctypes, sys as _sys
    from pathlib import Path as _Path
    _native_path = _Path(__file__).with_name('libtcn_resample.so')
    if _sys.platform == 'linux' and _native_path.is_file():
        _native_library = _ctypes.CDLL(str(_native_path))
        _NATIVE_RESAMPLE = _native_library.tcn_resample_i64
        _NATIVE_RESAMPLE.argtypes = [_ctypes.c_void_p, _ctypes.c_void_p, _ctypes.c_uint32, _ctypes.c_uint32, _ctypes.c_void_p, _ctypes.c_void_p]
        _NATIVE_RESAMPLE.restype = _ctypes.c_int

Q = 1 << 32
FQ = 1 << 30
COCO = ('NOSE','LEFT_EYE','RIGHT_EYE','LEFT_EAR','RIGHT_EAR',
        'LEFT_SHOULDER','RIGHT_SHOULDER','LEFT_ELBOW','RIGHT_ELBOW',
        'LEFT_WRIST','RIGHT_WRIST','LEFT_HIP','RIGHT_HIP','LEFT_KNEE',
        'RIGHT_KNEE','LEFT_ANKLE','RIGHT_ANKLE')


def rdiv(n, d):
    """Signed nearest division, ties to even, with integer operands only."""
    if d <= 0: raise ValueError('Positive denominator required')
    a, rem = divmod(abs(int(n)), int(d))
    if rem*2 > d or (rem*2 == d and a & 1): a += 1
    return -a if n < 0 else a


def isqrt(n):
    if n < 0: raise ValueError('Negative squared norm')
    if not n: return 0
    x = 1 << ((n.bit_length()+1)//2)
    while True:
        y = (x+n//x)//2
        if y >= x: return x
        x = y


def norm(v): return isqrt(v[0]*v[0]+v[1]*v[1])
def sub(a,b): return (a[0]-b[0], a[1]-b[1])
def mean(points): return tuple(rdiv(sum(p[j] for p in points),len(points)) for j in (0,1))
def ratio(v,scale): return [rdiv(x*FQ,scale) for x in v]


def number_to_fixed(value, bits):
    """Explicit coordinate-edge conversion; no floating feature calculation.

    Existing JSON pixel outputs may be binary floats. as_integer_ratio exposes
    their exact stored value and rounding below uses integers. New producers
    can supply the Q16/Q15 fields directly and bypass this compatibility edge.
    """
    if isinstance(value, bool): raise ValueError('Boolean coordinate')
    if isinstance(value, int): return value << bits
    if not isinstance(value, float): raise ValueError('Numeric pixel coordinate required')
    n,d = value.as_integer_ratio()
    return rdiv(n << bits,d)


def from_roi_replies(body_context, body_reply, hand_context, hand_reply):
    ids = ('stream_id','frame_id','timestamp_ms')
    identity = {k:body_context[k] for k in ids}
    if identity != {k:hand_context[k] for k in ids}:
        raise ValueError('Body and Hand must be the same source frame')
    br = body_reply.get('result',body_reply); hr = hand_reply.get('result',hand_reply)
    for result in (br,hr):
        if result.get('identity') != identity or result.get('coordinate_space') not in ('roi_pixels','roi_pixels_Q16'):
            raise ValueError('Relative-pixel response identity mismatch')
    size = body_context['roi']['source_size']
    if size != hand_context['roi']['source_size']: raise ValueError('Source image sizes differ')
    raw_body = br.get('points_q16',br.get('points_Q16'))
    if raw_body is None:
        raw_body = [[number_to_fixed(p[0],16),number_to_fixed(p[1],16),number_to_fixed(p[2],15)] for p in br['points']]
    hands = []
    for hand in hr.get('points',hr.get('hands',[])):
        pixels = hand.get('pixels_q16',hand.get('pixels_Q16'))
        if pixels is None: pixels = [[number_to_fixed(x,16),number_to_fixed(y,16)] for x,y in hand['pixels']]
        side = hand.get('side')
        hands.append(dict(side=side,identity_missing=hand.get('identity_missing',True),
                          pixels_q16=pixels,joint_missing=hand.get('joint_missing'),
                          native_body_hand_recrop=bool(hand.get('native_body_hand_recrop',False))))
    return make_frame(identity['stream_id'],identity['frame_id'],number_to_fixed(identity['timestamp_ms'],0)*1000
                      if isinstance(identity['timestamp_ms'],int) else
                      rdiv(identity['timestamp_ms'].as_integer_ratio()[0]*1000,identity['timestamp_ms'].as_integer_ratio()[1]),
                      size,raw_body,body_context['roi']['origin'],hands,hand_context['roi']['origin'])


def make_frame(stream_id,frame_id,timestamp_us,image_size,body_q16,body_origin,hands_q16,hand_origin):
    if not isinstance(frame_id,int) or isinstance(frame_id,bool) or not isinstance(timestamp_us,int) or isinstance(timestamp_us,bool): raise ValueError('Integer source ID/time required')
    if len(body_q16)!=17 or len(image_size)!=2: raise ValueError('COCO17 and source size required')
    if not all(isinstance(x,int) and not isinstance(x,bool) for x in list(image_size)+list(body_origin)+list(hand_origin)):
        raise ValueError('Integer image size and ROI pixel origins required')
    if min(image_size)<=0 or len(body_origin)!=2 or len(hand_origin)!=2: raise ValueError('Invalid source geometry')
    def point(p,origin):
        if len(p)<2 or not all(isinstance(x,int) and not isinstance(x,bool) for x in p):
            raise ValueError('Q16/Q15 coordinate ingress must contain integers only')
        return ((p[0]<<16)+origin[0]*Q,(p[1]<<16)+origin[1]*Q)
    width,height=image_size
    valid_xy=lambda p:0<=p[0]<width*Q and 0<=p[1]<height*Q
    xy={name:point(p,body_origin) for name,p in zip(COCO,body_q16)}
    valid={name:p[2]>=16384 and valid_xy(xy[name]) for name,p in zip(COCO,body_q16)}
    def derive(name,names,value): xy[name]=value;valid[name]=all(valid[n] for n in names)
    eyes=mean([xy['LEFT_EYE'],xy['RIGHT_EYE']]);nose=xy['NOSE']
    derive('FOREHEAD',('LEFT_EYE','RIGHT_EYE','NOSE'),tuple(rdiv(9*eyes[j]-4*nose[j],5) for j in (0,1)))
    shoulder=mean([xy['LEFT_SHOULDER'],xy['RIGHT_SHOULDER']]);hip=mean([xy['LEFT_HIP'],xy['RIGHT_HIP']])
    derive('CHEST',('LEFT_SHOULDER','RIGHT_SHOULDER','LEFT_HIP','RIGHT_HIP'),tuple(rdiv(4*shoulder[j]+hip[j],5) for j in (0,1)))
    scale=norm(sub(xy['LEFT_SHOULDER'],xy['RIGHT_SHOULDER']))
    body_valid=scale>=10*Q and valid['LEFT_SHOULDER'] and valid['RIGHT_SHOULDER']
    hands=[]
    for source in hands_q16:
        if len(source['pixels_q16'])!=21: raise ValueError('Hand21 required')
        pixels=[point(p,hand_origin) for p in source['pixels_q16']]
        missing=source.get('joint_missing')
        if missing is not None and len(missing)!=21: raise ValueError('Hand21 missing mask required')
        hv=[valid_xy(p) and not (missing[j] if missing is not None else False) for j,p in enumerate(pixels)]
        hands.append(dict(side=source.get('side'),identity_missing=source.get('identity_missing',True) is not False,
                          native_body_hand_recrop=bool(source.get('native_body_hand_recrop',False)),xy=pixels,valid=hv))
    return dict(stream_id=stream_id,frame_id=frame_id,timestamp_us=timestamp_us,image_size=list(image_size),
                body_xy=xy,body_valid=valid,body_missing=not body_valid,shoulder=shoulder,scale=scale,hands=hands)


def associate_current_body(frame,previous=None):
    """Integer port of frozen associate_hands; never substitutes old coordinates."""
    from itertools import permutations
    predictions=frame['hands']
    if len(predictions)>2: raise ValueError('Original identity contract permits at most two hands')
    if not predictions:return []
    xy=frame['body_xy'];valid=frame['body_valid'];scale=frame['scale'] if not frame['body_missing'] else Q
    costs=[]
    for labels in permutations(('Left','Right'),len(predictions)):
        cost=0
        for hand,label in zip(predictions,labels):
            wrist=label.upper()+'_WRIST';elbow=label.upper()+'_ELBOW'
            if not valid[wrist]:cost+=10*FQ
            else:
                cost+=rdiv(norm(sub(hand['xy'][0],xy[wrist]))*FQ,scale)
                if valid[elbow]:
                    arm=norm(sub(xy[wrist],xy[elbow]));fitted=norm(sub(hand['xy'][0],xy[elbow]))
                    cost+=rdiv(abs(fitted-arm)*FQ,4*scale)
            if hand.get('native_body_hand_recrop') and hand.get('side')!=label:cost+=FQ//2
        costs.append((cost,labels))
    costs.sort();best,labels=costs[0]
    clear=not frame['body_missing'] and 5*best<4*len(predictions)*FQ and 20*(costs[1][0]-best)>3*FQ
    source='body_wrist_assignment' if clear else 'ambiguous'
    if not clear and previous is not None:
        old={h['side']:h['xy'] for h in previous['hands'] if not h['identity_missing'] and h['side'] in ('Left','Right')}
        alternatives=[]
        for _,sides in costs:
            if all(side in old for side in sides):
                d=sum(rdiv(sum(norm(sub(a,b)) for a,b in zip(hand['xy'],old[side]))*FQ,21*scale)
                      for hand,side in zip(predictions,sides))
                alternatives.append((d,sides))
        alternatives.sort()
        if alternatives and 2*alternatives[0][0]<len(predictions)*FQ and (len(alternatives)==1 or 10*(alternatives[1][0]-alternatives[0][0])>FQ):
            labels=alternatives[0][1];clear=True;source='temporal_pose_identity'
    for hand,label in zip(predictions,labels):
        hand.update(side=label if clear else None,identity_missing=not clear,identity_source=source)
    return [dict(side=h['side'],identity_missing=h['identity_missing'],identity_source=h['identity_source']) for h in predictions]


def wrist_velocity(frame,previous):
    values=[0]*4;mask=[0]*4
    if previous is None or frame['body_missing'] or frame['stream_id']!=previous['stream_id']:return values,mask
    dt=frame['timestamp_us']-previous['timestamp_us']
    current_seq=frame.get('processed_sequence');previous_seq=previous.get('processed_sequence')
    adjacent=current_seq==previous_seq+1 if type(current_seq)is int and type(previous_seq)is int else frame['frame_id']==previous['frame_id']+1
    if not adjacent or not 0<dt<=1000000:return values,mask
    for side,offset in (('Left',0),('Right',2)):
        hand=next((h for h in frame['hands'] if h['side']==side and not h['identity_missing']),None)
        old=next((h for h in previous['hands'] if h['side']==side and not h['identity_missing']),None)
        if hand is not None and old is not None and hand['valid'][0]and old['valid'][0]:
            values[offset:offset+2]=[rdiv(x*1000000*FQ,frame['scale']*dt)for x in sub(hand['xy'][0],old['xy'][0])]
            mask[offset:offset+2]=[1,1]
    return values,mask


def feature(frame,previous=None,roof=False):
    values=[0]*(112 if roof else 96);mask=[0]*len(values);wrists={}
    body_ok=not frame['body_missing'];scale=frame['scale'];body=frame['body_xy'];bv=frame['body_valid']
    def put(at,items): values[at:at+len(items)]=items;mask[at:at+len(items)]=[1]*len(items)
    selected={}
    for side,offset,head in (('Left',0,84),('Right',42,86)):
        hand=next((h for h in frame['hands'] if h['side']==side and not h['identity_missing']),None)
        if hand is None: continue
        selected[side]=hand;xy=hand['xy'];valid=hand['valid'];palm=norm(sub(xy[9],xy[0]))
        if palm>=2*Q and valid[0] and valid[9]:
            for j in range(21):
                if valid[j]: put(offset+2*j,ratio(sub(xy[j],xy[0]),palm))
        if not body_ok or not valid[0]: continue
        wrists[side]=xy[0]
        if bv['FOREHEAD']: put(head,ratio(sub(xy[0],body['FOREHEAD']),scale))
    values[92:96],mask[92:96]=wrist_velocity(frame,previous)
    if len(wrists)==2:
        if bv['CHEST']: put(88,ratio(sub(mean([wrists['Left'],wrists['Right']]),body['CHEST']),scale))
        put(90,ratio(sub(wrists['Left'],wrists['Right']),scale))
    if not roof or not body_ok: return values,mask
    lengths={};tips={};distances={}
    for side,centre,size,tip in (('Left',96,100,104),('Right',98,102,106)):
        hand=selected.get(side)
        if hand is None: continue
        xy=hand['xy'];valid=hand['valid']
        if valid[0] and valid[9]:
            lengths[side]=rdiv(norm(sub(xy[9],xy[0]))*FQ,scale);put(size,[lengths[side]])
        if all(valid):
            extent=(max(p[0] for p in xy)-min(p[0] for p in xy),max(p[1] for p in xy)-min(p[1] for p in xy))
            put(size+1,[rdiv(norm(extent)*FQ,scale)])
        if not bv['CHEST']: continue
        if all(valid[j] for j in (0,5,9,13,17)): put(centre,ratio(sub(mean([xy[j] for j in (0,5,9,13,17)]),body['CHEST']),scale))
        if all(valid[j] for j in (4,8,12,16,20)):
            tips[side]=mean([xy[j] for j in (4,8,12,16,20)]);put(tip,ratio(sub(tips[side],body['CHEST']),scale))
        if valid[0]: distances[side]=rdiv(norm(sub(xy[0],body['CHEST']))*FQ,scale)
    if len(tips)==2: put(108,[rdiv(norm(sub(tips['Left'],tips['Right']))*FQ,scale)])
    if len(lengths)==2: put(109,[rdiv(lengths['Left']+lengths['Right'],2)]);put(111,[lengths['Left']-lengths['Right']])
    if len(distances)==2: put(110,[rdiv(distances['Left']+distances['Right'],2)])
    return values,mask


def frame_key(frame):
    return None if frame is None else (frame['stream_id'],frame['frame_id'],frame['timestamp_us'])


def cache_features(frame,previous):
    # Cache current-image geometry. Only velocity depends on the word predecessor.
    import numpy as np
    a,b=feature(frame,previous,True)
    try:a=np.asarray(a,dtype=np.int64)
    except OverflowError:pass
    frame['_feature_cache']=(frame_key(previous),(a,np.asarray(b,dtype=np.uint8)))


def resample_features(rows,valid):
    import numpy as np
    f=len(rows[0]);count=len(rows)
    # Keep arbitrary-integer behavior for extreme ingress rather than overflow.
    try:values=np.asarray(rows,dtype=np.int64)
    except OverflowError:values=None
    if _NATIVE_RESAMPLE is not None and values is not None:
        values=np.ascontiguousarray(values);mask=np.ascontiguousarray(valid,dtype=np.uint8)
        out=np.empty((32,f),np.int16);m=np.empty((32,f),np.uint8)
        clipped=_NATIVE_RESAMPLE(values.ctypes.data,mask.ctypes.data,count,f,out.ctypes.data,m.ctypes.data)
        if clipped>=0:return out,m,clipped
    bound=(2**63-1)//31
    if values is None or np.any(values>bound)or np.any(values < -bound):
        out=np.zeros((32,f),np.int16);m=np.zeros((32,f),np.uint8);clipped=0
        for t in range(32):
            lo,rem=divmod(t*(count-1),31);hi=min(lo+1,count-1)
            for c in range(f):
                if valid[lo][c] and (valid[hi][c] or rem==0):
                    q=rdiv(int(rows[lo][c])*(31-rem)+int(rows[hi][c])*rem,31*(1<<20))
                    clipped+=int(q < -32768 or q > 32767);out[t,c]=max(-32768,min(32767,q));m[t,c]=1
        return out,m,clipped
    mask=np.asarray(valid,dtype=np.uint8)
    lo,rem=np.divmod(np.arange(32,dtype=np.int64)*(count-1),31);hi=np.minimum(lo+1,count-1)
    rem=rem[:,None];m=mask[lo]&((mask[hi]!=0)|(rem==0))
    n=values[lo]*(31-rem)+values[hi]*rem;den=31*(1<<20)
    # ARMv7's 64-bit integer division is software. Saturation bounds the useful
    # quotient, so divide its high bits in UINT32 and retain the exact remainder.
    a=np.minimum(np.abs(n),32769*den)
    q=(a>>20).astype(np.uint32)//np.uint32(31)
    r=(a-q.astype(np.int64)*den).astype(np.uint32)
    q+=((2*r>den)|((2*r==den)&((q&1)!=0)))
    q=q.astype(np.int32)
    q=np.where(n<0,-q,q);clipped=int(np.count_nonzero(((q < -32768)|(q > 32767))&m.astype(bool)))
    return np.where(m,np.clip(q,-32768,32767),0).astype(np.int16),m.astype(np.uint8),clipped


def prepare_word(frames,roof=False):
    """Original 32 evenly spaced index positions and exact-source mask rule."""
    import numpy as np
    if not frames: raise ValueError('Nonempty word required')
    rows=[];valid=[];previous=None
    for frame in frames:
        cached=frame.get('_feature_cache')
        if cached is not None:
            a,b=cached[1];size=112 if roof else 96;a=a[:size];b=b[:size]
            if cached[0]!=frame_key(previous):
                velocity,velocity_mask=wrist_velocity(frame,previous)
                a=a.copy();b=b.copy()
                try:a[92:96]=velocity
                except OverflowError:a=list(a);a[92:96]=velocity
                b[92:96]=velocity_mask
        else:a,b=feature(frame,previous,roof)
        rows.append(a);valid.append(b);previous=frame
    out,m,clipped=resample_features(rows,valid)
    return out,m,dict(source_frames=len(frames),resampled_frames=32,raw_input_scale_denominator=1024,raw_input_clips=clipped,
                      feature='roof_direction112_v1' if roof else 'local_palm96_v1',fixed_point_frontend_new_candidate=True)


def rest_predicate(frame):
    """Original fingertips_below_hips, then arms_down fallback; integer tests."""
    xy=frame['body_xy'];valid=frame['body_valid']
    def arms_down():
        names=[s+'_'+p for s in ('LEFT','RIGHT') for p in ('SHOULDER','ELBOW','WRIST','HIP')]
        if frame['body_missing'] or not all(valid[n] for n in names): return None
        shoulder=mean([xy['LEFT_SHOULDER'],xy['RIGHT_SHOULDER']]);hip=mean([xy['LEFT_HIP'],xy['RIGHT_HIP']])
        axis=sub(hip,shoulder);length=norm(axis);scale=frame['scale']
        if 10*length < 3*scale: return None
        for side in ('LEFT','RIGHT'):
            a=sub(xy[side+'_WRIST'],hip);b=sub(xy[side+'_WRIST'],xy[side+'_ELBOW'])
            if 5*(a[0]*axis[0]+a[1]*axis[1]) < -scale*length: return False
            if 20*(b[0]*axis[0]+b[1]*axis[1]) < 3*scale*length: return False
        return True
    if not valid['LEFT_HIP'] or not valid['RIGHT_HIP'] or len(frame['hands'])!=2: return arms_down()
    for hand in frame['hands']:
        tips=sorted(hand['xy'][j][1] for j in (8,12,16,20) if hand['valid'][j])
        if len(tips)<3: return arms_down()
        side=hand['side'];hip=xy[side.upper()+'_HIP'][1] if side in ('Left','Right') else max(xy['LEFT_HIP'][1],xy['RIGHT_HIP'][1])
        if (2*tips[1] if len(tips)==3 else tips[1]+tips[2]) <= 2*hip: return False
    return True
