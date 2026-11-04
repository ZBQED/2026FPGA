"""Independent fixed-fixture integer checks; never used in the live inference path."""
import json
import numpy as np


class MACReference:
    def __init__(self, folder):
        self.rows = json.loads((folder/'jobs.json').read_text())['jobs']
        with np.load(folder/'parameters.npz', allow_pickle=False) as data:
            self.parameters = {k:data[k].astype(np.int64) for k in data.files}

    def verify(self, captures, profile):
        exact = 0
        for row in self.rows:
            if row['profile'] != profile: continue
            key = row['key'];cfg = row['config']
            signed = lambda n:n if n < 2**31 else n-2**32
            zero = signed(cfg[16]);positions = row['positions'];ci = row['ci']
            source = np.frombuffer((captures/(key+'.input.i8')).read_bytes(), np.int8).reshape(positions, ci)
            packed = np.full((positions,row['kw'],ci),zero,np.int64)
            for t in range(positions):
                for k in range(row['kw']):
                    index = t+(k-row['kw']//2)*row['dilation']
                    if 0 <= index < positions: packed[t,k] = source[index]
            weight = self.parameters[key+'_weight'];post = self.parameters[key+'_post']
            acc = (packed.reshape(positions,-1)-zero) @ weight.T + post[:,0]
            assert np.all((acc >= -(2**31)) & (acc < 2**31))
            product = acc*post[:,1]
            adjusted = product + np.where(product >= 0,1<<30,1-(1<<30))
            high = np.where(adjusted < 0,-((-adjusted)//(1<<31)),adjusted//(1<<31))
            right = -post[:,2];assert np.all((right >= 0) & (right <= 31))
            mask = (1<<right)-1;remainder = high & mask
            rounded = (high>>right) + (remainder > ((mask>>1)+(high<0)))
            expected = np.clip(rounded+signed(cfg[17]),signed(cfg[18]),signed(cfg[19])).astype(np.int8)
            actual = np.frombuffer((captures/(key+'.output.i8')).read_bytes(),np.int8).reshape(expected.shape)
            assert np.array_equal(actual,expected), ('TCN MAC differs',key,int(np.max(np.abs(actual.astype(int)-expected))))
            exact += 1
        assert exact == 8
        return exact
