"""Typed current-frame integer geometry to native 800x480 UI boundary; no model or network."""
import re

def current_geometry_packet(*,sequence,frame_id,camera_epoch,source_pixels_sha256,source_size,person_boxes_q16,hand_points_q16,body_points_q20):
    if type(sequence)is not int or not 0<=sequence<=0xffffffff or type(frame_id)is not int or frame_id<0:raise ValueError('Current sequence/frame required')
    if not isinstance(camera_epoch,str)or not re.fullmatch(r'[a-f0-9]{32}:[1-9][0-9]*',camera_epoch):raise ValueError('Explicit stream UUID:generation required')
    if not isinstance(source_pixels_sha256,str)or not re.fullmatch(r'[a-f0-9]{64}',source_pixels_sha256):raise ValueError('Same-frame source pixel identity required')
    if len(source_size)!=2 or any(type(v)is not int or not 1<=v<=8192 for v in source_size):raise ValueError('Explicit source width/height required')
    width,height=source_size
    def point(v,scale):
        if len(v)!=2 or any(type(x)is not int for x in v):raise ValueError('Integer XY required')
        return [v[0]*800/(width*scale),v[1]*480/(height*scale)]
    if len(body_points_q20)!=17 or len(hand_points_q16)!=2 or any(len(h)!=21 for h in hand_points_q16):raise ValueError('Current COCO17 and both 21-point hands required')
    body=[point(v,1<<20)for v in body_points_q20];hands=[dict(keypoints=[point(v,1<<16)for v in h])for h in hand_points_q16]
    boxes=[]
    for hand in hands:
        points=hand['keypoints'];xs=[v[0]for v in points];ys=[v[1]for v in points];pad=max(4,(max(max(xs)-min(xs),max(ys)-min(ys)))*0.12)
        boxes.append([max(0,min(xs)-pad),max(0,min(ys)-pad),min(800,max(xs)+pad),min(480,max(ys)+pad)])
    people=[]
    for v in person_boxes_q16:
        if len(v)!=4:raise ValueError('Person Q16 box required')
        a,b=point(v[:2],1<<16),point(v[2:],1<<16)
        if not(0<=a[0]<b[0]<=800 and 0<=a[1]<b[1]<=480):raise ValueError('Person box outside current source')
        people.append(a+b)
    return dict(protocol='SGR1',version=1,source='pc_tcn',type='gesture_state',sequence=sequence,frame_id=frame_id,camera_epoch=camera_epoch,status='watching',image_width=800,image_height=480,source_pixels_sha256=source_pixels_sha256,source_geometry_size=list(source_size),body_boxes=people,body_keypoints=body,hands=hands,boxes=boxes)
