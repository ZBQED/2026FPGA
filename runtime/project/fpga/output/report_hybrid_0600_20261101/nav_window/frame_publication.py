"""Immutable current-camera image, integer result and source hashes in one inode."""

from pathlib import Path

import hashlib,json,os,struct,time

import numpy as np

MAGIC=0x38464c56

HEADER=struct.Struct('<12I8Q128s4I')

assert HEADER.size==256

WIDTH,HEIGHT,STRIDE=800,480,2400



class FramePublisher:

    def __init__(self,run_dir):

        self.root=Path(run_dir);self.sequence=0

    def publish(self,image,source,identity,inferred_ns,metadata,validated_composite_sha256=None):

        if image.dtype!=np.uint8 or image.shape!=(480,800,3) or not image.flags.c_contiguous:raise ValueError('Owned complete uint8 BGR800x480 required')

        if identity['frame_id']!=source['frame_id'] or identity['timestamp_ms']!=source['capture_ns']//1000000:raise ValueError('Current TIM9 source identity mismatch')

        if not 0<source['capture_ns']<=source['observed_ns']<=inferred_ns:raise ValueError('Source/inference clocks out of order')

        payload=memoryview(image).cast('B');metadata=dict(metadata,identity=identity,capture_pixels_sha256=source['capture_sha256'],logical_pixels_sha256=source['logical_sha256'])

        data=json.dumps(metadata,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()

        if len(data)>16384:raise ValueError('Bounded display metadata required')

        self.sequence+=1

        if self.sequence>0x7fffff:raise ValueError('Bounded publication counter exhausted')

        hashes=bytes.fromhex(source['capture_sha256'])+bytes.fromhex(source['logical_sha256'])+(bytes.fromhex(validated_composite_sha256)if validated_composite_sha256 is not None else hashlib.sha256(payload).digest())+hashlib.sha256(data).digest()

        event=metadata.get('word_event') or {};semantic_start=metadata.get('semantic_start_capture_ns',0)

        temporary=self.root/('.publication.%d.tmp'%self.sequence);target=self.root/'current.frame'

        try:

            with temporary.open('xb') as f:

                f.write(bytes(256));f.write(payload);f.write(data);published=time.monotonic_ns()

                header=HEADER.pack(MAGIC,18,256,WIDTH,HEIGHT,STRIDE,self.sequence,source['frame_id'],image.nbytes,1,int(event.get('event_id',0)),0,

                    source['capture_ns'],source['observed_ns'],source['process_start_ns'],inferred_ns,published,semantic_start,inferred_ns if event else 0,0,

                    hashes,len(data),0,0,0)

                f.seek(0);f.write(header)

            os.replace(str(temporary),str(target))

        finally:

            try:temporary.unlink()

            except FileNotFoundError:pass

        return dict(publication=self.sequence,frame_id=source['frame_id'],published_ns=published,frame_path=str(target),capture_sha256=source['capture_sha256'],logical_sha256=source['logical_sha256'],composite_sha256=hashes[64:96].hex(),metadata_sha256=hashes[96:128].hex(),semantic_start_capture_ns=semantic_start)



    def wait_scan(self,publication,timeout_seconds=2):

        path=self.root/'display_ack.json';deadline=time.monotonic()+timeout_seconds

        while time.monotonic()<deadline:

            try:value=json.loads(path.read_text())

            except (FileNotFoundError,ValueError):time.sleep(.002);continue

            if value.get('publication')==publication['publication']:

                for k in ('frame_id','capture_sha256','logical_sha256','composite_sha256','metadata_sha256'):

                    if value.get(k)!=publication[k]:raise ValueError('Displayed source/hash differs: '+k)

                return value

            time.sleep(.002)

        raise TimeoutError('No current-source UI/scan acknowledgement; FBcopy is not HDMI acceptance')

