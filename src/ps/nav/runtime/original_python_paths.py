"""Reuse the audited original public path setup before original child services."""
from pathlib import Path
import hashlib,importlib.util,os,sys
def configure(expected_sha256):
 root=Path('/opt/gesture-tcn-20261022');source=root/'app_runner/run_gesture.py'
 if hashlib.sha256(source.read_bytes()).hexdigest()!=expected_sha256:raise RuntimeError('Original public path setup changed')
 spec=importlib.util.spec_from_file_location('cold_public_original_paths',source);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);module.configure_paths(root)
 # Child original Python helpers also need the exact existing compatibility
 # modules. No new library is installed or substituted.
 wanted=[root/'stdlib_compat',root/'build_runtime',root/'camera_port',root/'pose_port',root/'app',root/'dual_board']
 os.environ['PYTHONPATH']=':'.join(str(p) for p in wanted if p.is_dir())
