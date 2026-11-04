"""Resolve archived local manifest paths without changing archived evidence bytes."""
from pathlib import Path
import json
ROOT=Path(__file__).resolve().parent
mapping=json.loads((ROOT/'original_root.json').read_text('utf-8'))
original_loads=json.loads
_PATH_CASE={'EXTERNAL_ASSETS.md': 'external_assets.md', 'LICENSES': 'licenses', 'Apache-2.0.txt': 'apache-2.0.txt', 'CC-BY-4.0.txt': 'cc-by-4.0.txt', 'GPL-2.0-only.txt': 'gpl-2.0-only.txt', 'MIT.txt': 'mit.txt', 'PyNaCl': 'pynacl', 'PyNaCl-1.5.0.dist-info': 'pynacl-1.5.0.dist-info', 'LICENSE.APACHE': 'license.apache', 'LICENSE.BSD': 'license.bsd', 'LICENSE.txt': 'license.txt', 'dragon4_LICENSE.txt': 'dragon4_license.txt', 'LICENSE.md': 'license.md', 'ThirdPartyNotices.txt': 'thirdpartynotices.txt', 'LICENSE-3RD-PARTY.txt': 'license-3rd-party.txt', 'MediaPipe-Apache-2.0.txt': 'mediapipe-apache-2.0.txt', 'PYNQ-BSD-3-Clause.txt': 'pynq-bsd-3-clause.txt', 'PYNQ-third-party.txt': 'pynq-third-party.txt', 'PaddleDetection-Apache-2.0.txt': 'paddledetection-apache-2.0.txt', 'TensorFlow-2.11.0.txt': 'tensorflow-2.11.0.txt', 'LICENSE_SCOPE.md': 'license_scope.md', 'MODEL_AND_DATA_LICENSE.md': 'model_and_data_license.md', 'PUBLISHER_AUTHORIZATION.md': 'publisher_authorization.md', 'THIRD_PARTY_NOTICES.md': 'third_party_notices.md', 'xf86drmMode.h': 'xf86drmmode.h', 'Module.symvers': 'module.symvers', 'FPGA': 'fpga', 'hand_overlay_100MHz.dtbo': 'hand_overlay_100mhz.dtbo'}
def tail(value):return "/".join(_PATH_CASE.get(part,part)for part in value.replace("\\","/").split("/"))
def resolve(value):
 if isinstance(value,str):
  if value.startswith('@project/'):return str(ROOT/'project'/tail(value[9:]))
  if value.startswith('@runtime/'):return str(ROOT/tail(value[9:]))
  normalized=value.removeprefix('\\\\?\\').replace('\\','/')
  if normalized.lower().startswith(ROOT.as_posix().lower()+'/'):return value
  for old,new in [(mapping['project'],ROOT/'project'),(mapping['parent'],ROOT)]:
   prefix=old.replace('\\','/').rstrip('/')
   if normalized.lower()==prefix.lower():return str(new)
   if normalized.lower().startswith(prefix.lower()+'/'):return str(new/tail(normalized[len(prefix)+1:]))
 elif isinstance(value,dict):return {resolve(k)if isinstance(k,str)else k:resolve(v)for k,v in value.items()}
 elif isinstance(value,list):return [resolve(v)for v in value]
 return value
def loads(*args,**kwargs):return resolve(original_loads(*args,**kwargs))
json.loads=loads
