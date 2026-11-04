"""Current-frame display colors only. Never mutates a neural side or packet."""
from itertools import combinations,permutations
import math
SIDES=('Left','Right')

def point(x,width,height):
 try:
  if len(x)!=2:return None
  a,b=map(float,x)
  return (a,b)if math.isfinite(a)and math.isfinite(b)and 0<=a<width and 0<=b<height else None
 except(TypeError,ValueError):return None

def wrist(raw,width,height):
 xy=raw.get('pixels',[]);missing=raw.get('joint_missing')
 if missing is not None and (len(missing)!=21 or missing[0]):return None
 return point(xy[0],width,height)if len(xy)==21 else None

def position(raw,width,height):
 w=wrist(raw,width,height)
 if w is not None:return w[0],'current_raw_wrist0'
 pts=[v for i,p in enumerate(raw.get('pixels',[]))if (raw.get('joint_missing')is None or not raw['joint_missing'][i])for v in[point(p,width,height)]if v is not None]
 if not pts:raise ValueError('A displayed hand needs current valid raw points for color position')
 return (min(p[0]for p in pts)+max(p[0]for p in pts))*.5,'current_raw_points_box_center'

def assign_current_color_sides(raw_hands,decoded_body17,body_valid,width=800,height=480):
 if len(raw_hands)>2:raise ValueError('Original maximum two displayed hands retained')
 out=[None]*len(raw_hands);used=set()
 for i,raw in enumerate(raw_hands):
  side=raw.get('anatomical_side')
  if side in SIDES:out[i]=dict(color_side=side,color_side_source='current_true_side');used.add(side)
 available=[s for s in SIDES if s not in used]
 unknown=[i for i,v in enumerate(out)if v is None]
 body={}
 if decoded_body17 is not None and len(decoded_body17)==17 and len(body_valid)==17:
  for side,index in(('Left',9),('Right',10)):
   row=decoded_body17[index]
   if side in available and body_valid[index]and len(row)>=3 and math.isfinite(float(row[2]))and float(row[2])>=.5:
    p=point(row[:2],width,height)
    if p is not None:body[side]=p
 hands={i:wrist(raw_hands[i],width,height)for i in unknown};hands={i:v for i,v in hands.items()if v is not None}
 k=min(len(hands),len(body))
 if k:
  options=[]
  for indexes in combinations(hands,k):
   for sides in permutations(body,k):
    cost=sum((hands[i][0]-body[s][0])**2+(hands[i][1]-body[s][1])**2 for i,s in zip(indexes,sides))
    options.append((cost,indexes,sides))
  cost,indexes,sides=min(options)
  for i,side in zip(indexes,sides):
   out[i]=dict(color_side=side,color_side_source='current_frame_body_wrist_match',color_side_distance2=(hands[i][0]-body[side][0])**2+(hands[i][1]-body[side][1])**2)
   available.remove(side)
 remaining=[i for i,v in enumerate(out)if v is None]
 if len(remaining)==len(available)==1:
  out[remaining[0]]=dict(color_side=available[0],color_side_source='current_frame_remaining_side')
 elif remaining:
  # Screen-right -> anatomical Left color, screen-left -> Right color.
  # This is an explicitly labelled display heuristic, never an identity.
  order=sorted((position(raw_hands[i],width,height)[0],i)for i in remaining)
  choices=list(available)
  for rank,(x,i)in enumerate(order):
   wanted=('Right'if rank==0 else'Left')if len(order)==2 else('Left'if x>=width*.5 else'Right')
   side=wanted if wanted in choices else choices[0]
   out[i]=dict(color_side=side,color_side_source='current_frame_position_fallback',color_side_position_source=position(raw_hands[i],width,height)[1])
   choices.remove(side)
 return out
