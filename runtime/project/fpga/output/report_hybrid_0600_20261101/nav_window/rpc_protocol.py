"""Bounded authenticated binary RPC; pure import, no socket or key creation.

Wire: uint32BE header length | UTF8 JSON header | raw body | HMAC-SHA256.

HMAC covers the four-byte length, exact header bytes and exact body bytes.

Keys are caller-owned32byte memory objects, never fields/arguments/log files.

"""

import hashlib,hmac,json,socket,struct,time

PROTOCOL='fpga_int8_rpc_v1'

MAX_HEADER=8192

MAX_BODY=2097152  # Camera800x480 transport; no new PL operation

MAC_BYTES=32

class ProtocolError(ValueError):pass

class ConnectionClosed(EOFError):pass



def _key(key):

 if not isinstance(key,(bytes,bytearray,memoryview))or len(key)!=32:raise ProtocolError('32byte in-memory session key required')

 return key



def _deadline(timeout):

 if not isinstance(timeout,(int,float))or not 0<timeout<=600:raise ProtocolError('RPC timeout must be bounded within600seconds')

 return time.monotonic()+timeout



def _remaining(conn,end):

 left=end-time.monotonic()

 if left<=0:raise TimeoutError('RPC packet deadline expired')

 conn.settimeout(left)



def _exact(conn,count,end):

 out=bytearray(count);view=memoryview(out);done=0

 while done<count:

  _remaining(conn,end);got=conn.recv_into(view[done:],count-done)

  if not got:raise ConnectionClosed('Peer closed bounded RPC connection')

  done+=got

 return out if count>=65536 else bytes(out)



def _tag(key,prefix,header,body):

 m=hmac.new(_key(key),digestmod=hashlib.sha256);m.update(prefix);m.update(header);m.update(body);return m.digest()



def send_packet(conn,key,header,body=b'',timeout=10,max_body=MAX_BODY):

 if not isinstance(header,dict):raise ProtocolError('JSON object header required')

 if not isinstance(body,(bytes,bytearray,memoryview)):raise ProtocolError('Raw byte body required')

 if not isinstance(max_body,int)or not 0<=max_body<=MAX_BODY or len(body)>max_body:raise ProtocolError('Body exceeds bounded size')

 h=dict(header)

 if h.get('protocol',PROTOCOL)!=PROTOCOL:raise ProtocolError('RPC protocol differs')

 h['protocol']=PROTOCOL;h['body_bytes']=len(body)

 raw=json.dumps(h,separators=(',',':'),sort_keys=True,ensure_ascii=True,allow_nan=False).encode('utf-8')

 if not 0<len(raw)<=MAX_HEADER:raise ProtocolError('Header exceeds bounded size')

 prefix=struct.pack('!I',len(raw));tag=_tag(key,prefix,raw,body);end=_deadline(timeout);prior=conn.gettimeout()

 try:

  if hasattr(conn,'sendmsg'):

   views=[memoryview(v)for v in(prefix,raw,body,tag)]

   while views:

    _remaining(conn,end);sent=conn.sendmsg(views)

    if sent<=0:raise ConnectionClosed('Packet send made no progress')

    while views and sent>=len(views[0]):sent-=len(views.pop(0))

    if views and sent:views[0]=views[0][sent:]

  else:

   packet=prefix+raw+bytes(body)+tag;_remaining(conn,end);conn.sendall(packet)

 finally:conn.settimeout(prior)

 return tag



def recv_packet(conn,key,timeout=10,max_body=MAX_BODY):

 if not isinstance(max_body,int)or not 0<=max_body<=MAX_BODY:raise ProtocolError('Invalid maximum body size')

 end=_deadline(timeout);prior=conn.gettimeout()

 try:

  prefix=_exact(conn,4,end);length=struct.unpack('!I',prefix)[0]

  if not 0<length<=MAX_HEADER:raise ProtocolError('Header length rejected')

  raw=_exact(conn,length,end)

  try:head=json.loads(raw.decode('utf-8'),parse_constant=lambda x:(_ for _ in ()).throw(ProtocolError('Nonfinite JSON value rejected')))

  except(UnicodeError,ValueError)as e:raise ProtocolError('Invalid bounded JSON header')from None

  if not isinstance(head,dict)or head.get('protocol')!=PROTOCOL:raise ProtocolError('RPC protocol/object differs')

  count=head.get('body_bytes')

  if isinstance(count,bool)or not isinstance(count,int)or not 0<=count<=max_body:raise ProtocolError('Body length rejected')

  body=_exact(conn,count,end);tag=_exact(conn,MAC_BYTES,end)

  if not hmac.compare_digest(tag,_tag(key,prefix,raw,body)):raise ProtocolError('RPC authentication rejected')

  head['_authenticated_wire_mac']=tag.hex()

  return head,body

 finally:conn.settimeout(prior)

