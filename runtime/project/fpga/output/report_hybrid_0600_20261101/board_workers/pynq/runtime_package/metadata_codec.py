"""Lossless typed PL metadata snapshot. Pure import; no PYNQ/device access."""
import hashlib,json,math
FIELDS=('bitfile_name','timestamp','ip_dict','gpio_dict','interrupt_pins','interrupt_controllers','hierarchy_dict','mem_dict')
VERSION='pynq_metadata_typed_canonical_v1'
def _encode(value):return json.dumps(value,ensure_ascii=True,separators=(',',':'),allow_nan=False)
def canonical(value):
 active=set()
 def visit(v,depth):
  if depth>128:raise ValueError('PL metadata nesting exceeds128')
  t=type(v)
  if v is None:return ['none']
  if t is bool:return ['bool',v]
  if t is int:return ['int',str(v)]
  if t is str:return ['str',v]
  if t is float:
   if not math.isfinite(v):raise ValueError('Nonfinite PL metadata float rejected')
   return ['float',v.hex()]
  if t in(bytes,bytearray):return [t.__name__,v.hex()]
  if t not in(dict,list,tuple,set,frozenset):raise TypeError('Unsupported PL metadata type: '+t.__module__+'.'+t.__qualname__)
  identity=id(v)
  if identity in active:raise ValueError('Cyclic PL metadata rejected')
  active.add(identity)
  try:
   if t is dict:
    items=[[visit(k,depth+1),visit(item,depth+1)]for k,item in v.items()];items.sort(key=lambda pair:_encode(pair[0]));return ['dict',items]
   items=[visit(item,depth+1)for item in v]
   if t in(set,frozenset):items.sort(key=_encode)
   return [t.__name__,items]
  finally:active.remove(identity)
 return visit(value,0)
def snapshot_pl_metadata(pl):
 values={name:getattr(pl,name,None)for name in FIELDS};full=canonical(values)
 return dict(bitfile_name=values['bitfile_name'],algorithm=VERSION,canonical_fields=full,digest=hashlib.sha256(_encode(full).encode('utf-8')).hexdigest())
