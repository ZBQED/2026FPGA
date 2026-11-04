"""Lossless zero-word packing for authenticated FP32 feature transport."""
import numpy as np

def pack_features(values):
    values=np.ascontiguousarray(values,dtype='<f4').reshape(-1)
    words=values.view('<u4');mask=words!=0
    packed=np.packbits(mask).tobytes()+words[mask].tobytes()
    return (packed,'zero_words')if len(packed)<values.nbytes else(values.tobytes(),'raw')

def unpack_features(data,encoding,count):
    assert 0<count<=524288
    if encoding=='raw':
        assert len(data)==4*count
        return np.frombuffer(data,'<f4')
    assert encoding=='zero_words'
    size=(count+7)//8;assert len(data)>=size
    mask=np.unpackbits(np.frombuffer(data,np.uint8,count=size))[:count].astype(bool)
    assert len(data)==size+4*int(mask.sum())
    words=np.zeros(count,dtype='<u4');words[mask]=np.frombuffer(data,'<u4',offset=size)
    return words.view('<f4')
