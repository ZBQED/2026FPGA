"""Run the packaged three-board coordinator using the existing camera publisher."""
from pathlib import Path
import os,sys,runpy,argparse
if not sys.flags.utf8_mode:
 os.execv(sys.executable,[sys.executable,'-X','utf8','-B',str(Path(__file__).resolve()),*sys.argv[1:]])
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT));import sitecustomize
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('mode',choices=['live','fixed','tcn','hand','restore'])
args=parser.parse_args()
if args.mode!='restore':
 sys.path.insert(0,str(ROOT.parent/'build'))
 from check_external_assets import check
 admission=check('runtime')
 if admission['status']!='READY':
  parser.exit(2,'Target inputs are required. See external_assets.md and run build/check_external_assets.py --group runtime.\n')
os.environ.update(PYTHONUTF8='1',PYTHONDONTWRITEBYTECODE='1',PYTHONPATH=str(ROOT)+os.pathsep+os.environ.get('PYTHONPATH',''))
W=ROOT/'project';sys.path.insert(0,str(W/'tools'))
if args.mode in ('fixed','live'):
 # Read this boot's restore identity before taking either compute-board lease.
 runpy.run_path(str(W/'tools/read_pynq_current_restore.py'),run_name='__main__')
 sys.argv=[str(W/'tools/run_three_board_perception.py'),'--with-tcn','--compact-nav','--reuse-roi','--nav-body-native','--late-display','--fast-render','--neon-swap','--native-hand-crop','--q-parallel']
 if args.mode=='fixed':sys.argv+=['--offline-roi']
 if args.mode=='live':sys.argv+=['--minute']
elif args.mode=='tcn':sys.argv=[str(W/'tools/run_tcn_frontend_replay.py')]
elif args.mode=='hand':
 runpy.run_path(str(W/'tools/read_pynq_current_restore.py'),run_name='__main__')
 sys.argv=[str(W/'tools/run_p_fixture.py'),'3']
else:sys.argv=[str(W/'tools/read_pynq_current_restore.py')]
runpy.run_path(sys.argv[0],run_name='__main__')
