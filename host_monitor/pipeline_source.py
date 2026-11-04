"""Adapt numeric, same-frame Nav telemetry to the monitor schema."""
from pathlib import Path
import json,math,re
import psutil

def finite(v):return type(v)in(int,float)and math.isfinite(v)
def current_session(project):
 try:
  value=json.loads((Path(project)/'runtime/project/runs/monitor_session.json').read_text('utf-8'))
  if value.get('status')!='FPGA_PIPELINE_RUNNING':return value
  if not re.fullmatch('/run/light_try_perception_[0-9a-f]{16}',value.get('pipeline_state','')):return {}
  if psutil.Process(value['owner_pid']).create_time()!=value['owner_create_time']:return {}
  return value
 except(OSError,ValueError,KeyError,psutil.Error):return {}

def ingest_pipeline(engine,remote,observed_ms):
 d=remote.get('pipeline');active=engine.active
 if not isinstance(d,dict)or active.get('status')!='FPGA_PIPELINE_RUNNING'or d.get('session_id')!=active.get('session_id'):return
 stamp=d.get('published_monotonic_ns');clock=remote.get('monotonic_ns')
 if not finite(stamp)or not finite(clock):return
 age=(clock-stamp)/1e6
 if age < -50 or age>3000:return
 published_ms=observed_ms-max(0,age);old=engine.prev_live
 if old and old.get('session_id')==d['session_id']and old.get('frame_count')==d.get('frame_id'):return
 body={}
 values=d.get('body_points',[]);valid=d.get('body_valid',[])
 if len(values)!=17 or len(valid)!=17:return
 for i,p in enumerate(values):
  good=bool(valid[i])and len(p)==3 and all(finite(v)for v in p)
  body['COCO_'+str(i)]=dict(index=i,pixels=p[:2]if good else[None,None],missing=not good,confidence=p[2]if good else None)
 hands=[]
 for h in d.get('hands',[]):
  points=h.get('points',[]);flags=h.get('valid',[])
  if len(points)!=21 or len(flags)!=21:continue
  hands.append(dict(pixels=points,joint_missing=[not v for v in flags],side=h.get('side'),identity_missing=h.get('side')not in('Left','Right'),confidence=h.get('hand_presence')))
 semantic=d.get('Semantic')or{};event=semantic.get('event');word=None
 if event:
  score=event.get('confidence_Q15');word=dict(event,gesture=event.get('display_gesture',event.get('gesture')),confidence=score/32768. if finite(score)else None,event_id=event.get('event_id',d['frame_id']),emitted_ms=d.get('capture_ns',0)/1e6)
 last=dict(frame_id=d['frame_id'],timestamp_us=d.get('capture_ns',0)//1000,frame_packet=dict(body=dict(points=body),hands=hands),TCN_last=word,TCN_state=semantic.get('state'),PC_frontend_ms=d.get('PC_frontend_ms'),person_body_recovery=dict(person=dict(final_boxes=d.get('person_boxes',[]))),capture_to_scanout_ms=d.get('capture_to_scanout_ms'))
 value=dict(session_id=d['session_id'],heartbeat_unix_ns=int(published_ms*1000000),frame_count=d['frame_id'],last=last,confidence_min=.8,TCN_frame_id_kind='same_frame',capture_ns=d.get('capture_ns'),driver_sequence=d.get('v4l2_driver_sequence'),published_monotonic_ns=stamp,source_scope=d.get('source_scope'))
 if old and old.get('session_id')==d['session_id']:
  dt=(stamp-old.get('published_monotonic_ns',stamp))/1e9
  if dt>0:engine.derived['inference_fps']=(d['frame_id']-old['frame_count'])/dt
  capture_dt=(d.get('capture_ns',0)-old.get('capture_ns',0))/1e9;current=value.get('driver_sequence');previous=old.get('driver_sequence')
  engine.derived['camera_fps']=(current-previous)/capture_dt if d.get('source_scope')=='live_nav_ram'and type(current)is int and type(previous)is int and current>=previous and capture_dt>0 else None
 elif active:engine.derived={};engine.event('session','三板推理会话 '+d['session_id'])
 if word and engine.last_event!=(d['session_id'],word['event_id']):
  engine.last_event=(d['session_id'],word['event_id']);engine.event('TCN',str(word.get('gesture')or'')+(' · 已确认'if event.get('accepted_by_original_gate')else' · 待确认'))
 engine.prev_live=value;engine.live=value
