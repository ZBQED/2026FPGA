"""Reproduce one frozen RTL test in a new output directory (Vivado 2024.2)."""
from pathlib import Path
import argparse, json, os, re, shutil, subprocess

root = Path(__file__).resolve().parents[1]
cases = json.loads((root/'sim/cases.json').read_text('utf-8'))
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('case', choices=cases)
parser.add_argument('--output', required=True, help='New, empty directory outside this repository')
parser.add_argument('--vivado-bin', help='Vivado bin directory; otherwise use PATH')
parser.add_argument('--check-only', action='store_true')
args = parser.parse_args()
source = root/'sim/design'/args.case
out = Path(args.output).resolve()
if out.is_relative_to(root) and not out.is_relative_to(root/'build_output'): parser.error('Use build_output/ or an external output directory')
if out.exists(): parser.error('Output directory already exists; choose a new directory')
references = re.findall(r'"([^"]+)"', (source/'files.prj').read_text('utf-8'))
for name in references:
    if not (source/name).is_file(): raise FileNotFoundError(name)
if args.check_only:
    print(json.dumps(dict(case=args.case, references=len(references), status='SOURCE_CLOSURE_PASS')))
    raise SystemExit(0)

suffix = '.bat' if os.name == 'nt' else ''
def tool(name):
    path = Path(args.vivado_bin)/(name+suffix) if args.vivado_bin else shutil.which(name+suffix)
    if path is None or not Path(path).is_file(): raise FileNotFoundError('Missing tool: '+name)
    return str(path)
xelab, xsim = tool('xelab'), tool('xsim')
shutil.copytree(source, out)
if args.case == 'core':
    for category in ['test_inputs', 'reference']:
        for f in (root/'data'/category/'core').glob('*.hex'): shutil.copy2(f, out/f.name)
env = os.environ.copy()
for key in ['TEMP','TMP','USERPROFILE','HOME','APPDATA','LOCALAPPDATA','XDG_CACHE_HOME']:
    directory = out/'tool_env'/key.lower(); directory.mkdir(parents=True, exist_ok=True)
    env[key] = str(directory)
cmd = [xelab, 'xil_defaultlib.tb']
if args.case == 'ethernet': cmd += ['xil_defaultlib.glbl']
cmd += ['-prj','files.prj','-L','unisims_ver','-L','xpm','-L','secureip',
        '-timescale','1ns/1ps','-mt','2','-debug','typical','-s','submission_'+args.case]
result = dict(case=args.case, status='FAILED', commands=[], hardware_accessed=False)
try:
    for command, log in [(cmd,'compile.log'),
        ([xsim,'submission_'+args.case,'-tclbatch','run.tcl','-wdb',args.case+'.wdb'],'simulate.log')]:
        with (out/log).open('w', encoding='utf-8') as stream:
            completed = subprocess.run(command, cwd=out, env=env, stdout=stream, stderr=subprocess.STDOUT, timeout=300)
        result['commands'].append(dict(argv=command, returncode=completed.returncode))
        if completed.returncode: raise RuntimeError('See '+str(out/log))
    text = (out/'simulate.log').read_text('utf-8',errors='replace')
    if cases[args.case]['pass_marker'] not in text or re.search(r'(^|\n)(Fatal:|ERROR:)',text):
        raise RuntimeError('RTL checks did not pass; see simulate.log')
    result['status'] = 'PASS'
finally:
    (out/'run_result.json').write_text(json.dumps(result,indent=2)+'\n','utf-8')
print(json.dumps(result))
