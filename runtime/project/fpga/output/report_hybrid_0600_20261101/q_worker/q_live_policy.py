"""Pure bounds/identity/schema admission; no model or device operations."""
import hashlib,json,re
COCO=('NOSE','LEFT_EYE','RIGHT_EYE','LEFT_EAR','RIGHT_EAR','LEFT_SHOULDER','RIGHT_SHOULDER','LEFT_ELBOW','RIGHT_ELBOW','LEFT_WRIST','RIGHT_WRIST','LEFT_HIP','RIGHT_HIP','LEFT_KNEE','RIGHT_KNEE','LEFT_ANKLE','RIGHT_ANKLE')
class LivePolicy:
 def __init__(self,session):self.session=session;self.stream=None;self.frames={};self.hand_calls=0;self.current_calls=0;self.last_current_id=None;self.last_time=None;self.capture_frames=0
 def admit(self,head,body,operation):
  if head.get('session_id')!=self.session or head.get('operation')!=operation:raise ValueError('Authenticated session/operation differs')
  stream=head.get('stream_id');fid=head.get('frame_id');stamp=head.get('timestamp_us');source=head.get('source_pixels_sha256')
  if not isinstance(stream,str)or not 1<=len(stream)<=128 or type(fid)is not int or not 0<=fid<2**63 or type(stamp)is not int or not 0<stamp<2**63:raise ValueError('Real stream/frame/EOF-us identity required')
  if not isinstance(source,str)or not re.fullmatch('[0-9a-f]{64}',source)or head.get('input_sha256')!=hashlib.sha256(body).hexdigest():raise ValueError('Source/body SHA contract differs')
  if self.stream is not None and stream!=self.stream:raise ValueError('One capture stream per window required')
  row=self.frames.get(fid)
  if row is None:
   if self.last_current_id is not None and fid<=self.last_current_id:raise ValueError('New Hand frame must follow last current frame')
   if any(not x['current_done']for x in self.frames.values()):raise ValueError('Finish current_frame for the previous capture before a new frame')
   row=dict(stream_id=stream,timestamp_us=stamp,source_pixels_sha256=source,hand_calls=0,current_done=False)
  elif any(row[k]!=v for k,v in(('stream_id',stream),('timestamp_us',stamp),('source_pixels_sha256',source))):raise ValueError('Same-frame source identity/time changed')
  if operation=='hand':
   if row['current_done']or row['hand_calls']>=3 :raise ValueError('At most3 Hand calls before one current-frame update')
   if type(head.get('request_id'))is not int or head['request_id']!=self.hand_calls+1:raise ValueError('Monotonic global Hand request_id required')
   if head.get('dtype')!='int8'or head.get('shape')!=[1,224,224,3]or len(body)!=150528:raise ValueError('INT8 NHWC150528B required')
  elif operation=='current_frame':
   if row['current_done'] or len(body)>65536:raise ValueError('At most one bounded current-frame packet per captured frame')
   if self.last_current_id is not None and(fid<=self.last_current_id or stamp<=self.last_time):raise ValueError('Actual current frame IDs/timestamps must increase')
  else:raise ValueError('Unknown live operation')
  return row
 def commit(self,head,row,operation):
  if head['frame_id']not in self.frames:self.capture_frames+=1
  self.stream=head['stream_id'];self.frames[head['frame_id']]=row
  if operation=='hand':row['hand_calls']+=1;self.hand_calls+=1
  else:row['current_done']=True;self.current_calls+=1;self.last_current_id=head['frame_id'];self.last_time=head['timestamp_us'];self.frames={head['frame_id']:row}
def validate_frame(ff,head):
 if not isinstance(ff,dict)or any(ff.get(k)!=head.get(k)for k in('stream_id','frame_id','timestamp_us')):raise ValueError('Feature frame identity differs from authenticated EOF identity')
 def integer(v):return type(v)is int and -2**63<=v<2**63
 def point(v):return isinstance(v,(list,tuple))and len(v)==2 and all(integer(x)for x in v)
 if not isinstance(ff.get('image_size'),list)or not point(ff['image_size'])or min(ff['image_size'])<=0:raise ValueError('Source image geometry required')
 if ff['image_size']!=[800,480]:raise ValueError('Hybrid native_BGR800x480_v1 source geometry required')
 keys=set(COCO+('FOREHEAD','CHEST'));xy=ff.get('body_xy');valid=ff.get('body_valid')
 if not isinstance(xy,dict)or set(xy)!=keys or not all(point(v)for v in xy.values())or not isinstance(valid,dict)or set(valid)!=keys or not all(type(v)is bool for v in valid.values()):raise ValueError('Complete integer COCO17+derived body values/masks required')
 if type(ff.get('body_missing'))is not bool or not point(ff.get('shoulder'))or not integer(ff.get('scale'))or ff['scale']<0:raise ValueError('Current body validity/geometry required')
 hands=ff.get('hands')
 if not isinstance(hands,list)or len(hands)>2:raise ValueError('At most two current hands')
 for hand in hands:
  if not isinstance(hand,dict)or hand.get('side')not in(None,'Left','Right')or type(hand.get('identity_missing'))is not bool:raise ValueError('Current anatomical identity validity required')
  if not isinstance(hand.get('xy'),list)or len(hand['xy'])!=21 or not all(point(p)for p in hand['xy'])or not isinstance(hand.get('valid'),list)or len(hand['valid'])!=21 or not all(type(v)is bool for v in hand['valid']):raise ValueError('Current integer Hand21 values/masks required')
 # Reject floating/opaque fields anywhere; feature computation remains integer.
 def walk(v):
  if type(v)in(str,bool,type(None)):return
  if integer(v):return
  if isinstance(v,list):
   for x in v:walk(x)
   return
  if isinstance(v,dict)and all(type(k)is str for k in v):
   for x in v.values():walk(x)
   return
  raise ValueError('Integer-only JSON feature frame required')
 walk(ff);return ff
