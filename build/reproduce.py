"""Rebuild ARM components using only bundled project inputs and installed Vitis tools."""
from pathlib import Path
import argparse,json,os,shutil,subprocess,sys
from unpack_dependencies import unpack

ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('component',choices=['native','display','qt','camera','tcn','backend'])
parser.add_argument('--vitis-root',type=Path,required=True)
parser.add_argument('--configure-only',action='store_true')
parser.add_argument('--jobs',type=int,default=2)
args=parser.parse_args()
vitis=args.vitis_root.resolve();compiler=vitis/'gnu/aarch32/nt/gcc-arm-linux-gnueabi/bin'
if not(compiler/'arm-linux-gnueabihf-gcc.exe').is_file():parser.error('Vitis ARM Linux compiler directory differs')
if args.jobs<1:parser.error('jobs must be positive')
selected={'arm_userspace'}
if args.component in{'tcn','backend'}:selected|={'tensorflow','tflite_dependencies'}
paths=unpack(selected);sdk=paths['arm_userspace']/'sysroot';libs=paths['arm_userspace']/'runtime_libraries'
out=ROOT/'build_output'/args.component;out.mkdir(parents=True,exist_ok=True)
temporary=ROOT/'.cache/build_tmp';temporary.mkdir(parents=True,exist_ok=True)
env=dict(os.environ,TEMP=str(temporary),TMP=str(temporary),PYTHONDONTWRITEBYTECODE='1',MGD_VITIS_ROOT=str(vitis),MGD_ARM_SYSROOT=str(sdk))
commands=[]
if args.component=='backend':
    def tool(name,candidates):
        found=next((p for p in candidates if p.is_file()),None)
        if found:return str(found)
        found=shutil.which(name)
        if found:return found
        raise FileNotFoundError('Installed Vitis tool is required: '+name)
    cmake=tool('cmake.exe',[vitis/'tps/win64/cmake-3.24.2/bin/cmake.exe',vitis/'tps/cmake/3.24.2/win64.o/nt/bin/cmake.exe'])
    ninja=tool('ninja.exe',[vitis/'tps/mingw/10.0.0/win64.o/nt/bin/ninja.exe'])
    deps=paths['tflite_dependencies'];tf=paths['tensorflow']/'tensorflow-2.11.0'
    cmake_path=lambda path:Path(path).resolve().as_posix()
    commands.append([cmake,'-G','Ninja','-S',cmake_path(ROOT/'build/nav_fp32'),'-B',cmake_path(out),
      '-DCMAKE_BUILD_TYPE=Release','-DCMAKE_TOOLCHAIN_FILE='+cmake_path(ROOT/'build/arm_toolchain.cmake'),
      '-DCMAKE_MAKE_PROGRAM='+ninja.replace('\\','/'),'-DGESTURE_TENSORFLOW_SOURCE='+cmake_path(tf),
      '-DGESTURE_CPP9_INCLUDE='+cmake_path(sdk/'usr/arm-linux-gnueabihf/include/c++/9'),
      '-DFETCHCONTENT_FULLY_DISCONNECTED=ON','-DFETCHCONTENT_UPDATES_DISCONNECTED=ON',
      '-DCMAKE_EXPORT_NO_PACKAGE_REGISTRY=ON','-DCMAKE_FIND_USE_PACKAGE_REGISTRY=OFF',
      *['-DFETCHCONTENT_SOURCE_DIR_'+name.upper()+'='+cmake_path(deps/name)for name in ['abseil-cpp','cpuinfo','eigen','farmhash','fft2d','flatbuffers','gemmlowp','neon2sse','ruy']]])
    if not args.configure_only:commands.append([cmake,'--build',str(out),'--target','gesture_tflite_pl','--parallel',str(args.jobs)])
else:
    if args.configure_only:parser.error('configure-only applies to backend')
    command=[sys.executable,'-B',str(ROOT/'build/build_arm.py'),args.component,'--compiler-dir',str(compiler),'--sysroot',str(sdk),'--runtime-libs',str(libs),'--output',str(out)]
    if args.component=='display':command+=['--drm-sdk',str(ROOT/'build/sdk/drm')]
    if args.component=='tcn':command+=['--tf-source',str(paths['tensorflow']/'tensorflow-2.11.0'),'--tf-dependencies',str(paths['tflite_dependencies']),'--backend-library',str(ROOT/'board/runtime/q/libgesture_tflite_pl.so')]
    commands.append(command)
receipt=dict(component=args.component,commands=commands,results=[])
for index,command in enumerate(commands):
    log=out/('command_'+str(index)+'.log')
    with log.open('w',encoding='utf-8')as stream:
        stream.write(json.dumps(command)+'\n');stream.flush()
        result=subprocess.run(command,cwd=ROOT,env=env,stdout=stream,stderr=subprocess.STDOUT)
    receipt['results'].append(dict(returncode=result.returncode,log=str(log.relative_to(ROOT))))
    (out/'reproduction.json').write_text(json.dumps(receipt,indent=2)+'\n','utf-8')
    if result.returncode:raise SystemExit('Build stopped; see '+str(log))
print(json.dumps(dict(status='PASS',component=args.component,output=str(out),steps=len(commands))))
