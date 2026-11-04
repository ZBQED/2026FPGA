"""Cross-compile supplied userspace sources against the retained ARM runtime ABI."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('mode', choices=['native','qt','camera','tcn','display'])
parser.add_argument('--compiler-dir', type=Path, required=True)
parser.add_argument('--sysroot', type=Path, required=True)
parser.add_argument('--runtime-libs', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--library')
parser.add_argument('--tf-source', type=Path)
parser.add_argument('--tf-dependencies', type=Path)
parser.add_argument('--backend-library', type=Path)
parser.add_argument('--drm-sdk', type=Path)
parser.add_argument('--link-only', action='store_true')
args = parser.parse_args()
SDK = args.sysroot.resolve()
TOOLS = args.compiler_dir.resolve()
LIB = args.runtime_libs.resolve()
OUT = args.output.resolve()
if OUT.is_relative_to(ROOT):
    parser.error('Build output must be outside the source package')
OUT.mkdir(parents=True,exist_ok=True)
(OUT/'tmp').mkdir(exist_ok=True)
suffix = '.exe' if os.name=='nt' else ''
CC = TOOLS/('arm-linux-gnueabihf-gcc'+suffix)
CXX = TOOLS/('arm-linux-gnueabihf-g++'+suffix)
READELF = TOOLS/('arm-linux-gnueabihf-readelf'+suffix)
env = dict(os.environ,TEMP=str(OUT/'tmp'),TMP=str(OUT/'tmp'),PYTHONDONTWRITEBYTECODE='1')
include = subprocess.check_output([str(CC),'-print-file-name=include'],text=True).strip()
vendor = Path(subprocess.check_output([str(CC),'-print-sysroot'],text=True).strip())/'usr/include'
flags = ['-O2','-fPIC','-mcpu=cortex-a9','-mfpu=neon','-mfloat-abi=hard','-marm',
         '-ffp-contract=off','-fno-fast-math','-nostdinc',
         '-isystem',include,'-isystem',str(SDK/'usr/include'),
         '-isystem',str(SDK/'usr/include/arm-linux-gnueabihf'),'-isystem',str(vendor)]
cpp = SDK/'usr/arm-linux-gnueabihf/include/c++/9'
cxxflags = ['-std=c++17','-nostdinc++','-isystem',str(cpp),
            '-isystem',str(cpp/'arm-linux-gnueabihf'),'-isystem',str(cpp/'backward'),
            '-include','limits']
libraries = [str(LIB/name) for name in ['libm-2.30.so','libpthread-2.30.so',
             'libdl-2.30.so','libc-2.30.so','libgcc_s.so.1','ld-2.30.so']]
rows = []

def build(name, command, inputs):
    log = OUT/(name+'.log')
    with log.open('w',encoding='utf-8') as f:
        f.write(json.dumps(command,ensure_ascii=False)+'\n'); f.flush()
        result = subprocess.run(command,stdout=f,stderr=subprocess.STDOUT,env=env)
    row = dict(name=name,returncode=result.returncode,
               source_sha256={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs},
               status='COMPILE_FAILED')
    if not result.returncode:
        binary = OUT/name
        data = binary.read_bytes()
        assert data[:4]==b'\x7fELF' and data[4]==1 and int.from_bytes(data[18:20],'little')==40
        elf = subprocess.run([str(READELF),'-h','-A','-d','-V',str(binary)],capture_output=True,text=True,errors='replace')
        (OUT/(name+'.elf.txt')).write_text(elf.stdout+elf.stderr,'utf-8')
        row.update(status='ARM_ELF_BUILT',sha256=hashlib.sha256(data).hexdigest(),bytes=len(data))
    rows.append(row)
    (OUT/(mode+'_result.json')).write_text(json.dumps(dict(results=rows,hardware_accessed=False),indent=2)+'\n','utf-8')
    print(json.dumps(row),flush=True)

native = ROOT/'src/native'
tasks = [
    ('libhand_q.so',[native/'hand_q/workspace_source.c'],[]),
    ('libhand_p.so',[native/'hand_p/full_hand.c'],[]),
    ('libhand_crop.so',[native/'nav/hand_crop.c'],[]),
    ('libgaussian3.so',[native/'nav/gaussian3.c'],[]),
    ('libtcn_resample.so',[native/'tcn_frontend/resample_i64.c'],[]),
    ('libcamera_timed_arm.so',[native/'capture/camera_seqlock.c',native/'capture/capture_timestamp.c'],[]),
    ('libyf2_raw_pl.so',[native/'person'/n for n in ['delivery_yolo_pc.c','yf2_core.c','yf2_decode.c','yf2_preproc.c']],
     ['-D_POSIX_C_SOURCE=200809L','-DYF2_PREPROC_IN_W=192','-DYF2_PREPROC_IN_H=192','-I',str(native/'person')]),
]
mode = args.mode
if mode=='native':
    selected = args.library
    if selected and selected not in [row[0] for row in tasks]:
        parser.error('Unknown native library')
    if selected and (OUT/'native_result.json').exists():
        rows.extend(r for r in json.loads((OUT/'native_result.json').read_text('utf-8'))['results'] if r['name']!=selected)
    for name, sources, options in tasks:
        if selected and name!=selected:
            continue
        command = [str(CC),'-std=c11']+flags+options+['-shared','-nostdlib']+list(map(str,sources))+libraries+[
            '-lgcc','-Wl,-z,defs','-Wl,-rpath-link,'+str(LIB),'-o',str(OUT/name)]
        build(name,command,sources)
elif mode=='display':
    if not args.drm_sdk:parser.error('display requires --drm-sdk with target libdrm headers and libdrm.so.2.4.0')
    folder=ROOT/'src/native/display';sources=[folder/'live_integer_frame.c']
    for name in ['liblive_integer_frame.so','libreport_integer_image.so']:
        command=[str(CC),'-std=c11']+flags+['-I'+str(folder),'-I'+str(args.drm_sdk),'-shared','-nostdlib']+list(map(str,sources))+[str(args.drm_sdk/'libdrm.so.2.4.0')]+libraries+['-lgcc','-Wl,-z,defs','-Wl,-soname,'+name,'-Wl,-rpath-link,'+str(LIB),'-o',str(OUT/name)]
        build(name,command,sources)
elif mode in ('qt','camera'):
    bindings = json.loads((ROOT/'build/qt_generated/bindings.json').read_text('utf-8'))
    for relative, digest in bindings['source_files_sha256'].items():
        if hashlib.sha256((ROOT/relative).read_bytes()).hexdigest()!=digest:
            raise RuntimeError('Regenerate Qt moc/rcc after changing '+relative)
    qt = SDK/'usr/include/arm-linux-gnueabihf/qt5'
    sources = [ROOT/'src/ui/src'/n for n in ['main.cpp','backend.cpp','camerapreview.cpp']]
    sources += [ROOT/'build/qt_generated'/n for n in ['moc_backend.cpp','moc_camerapreview.cpp','qrc_qml.cpp']]
    if mode=='camera': sources=[ROOT/'src/ui/camera_bridge.cpp']
    options = ['-DQT_NO_OPENGL','-include',str(ROOT/'build/qt_generated/deployment_config.h'),'-I'+str(ROOT/'src/ui/src'),'-I'+str(qt)]
    options += ['-I'+str(qt/n) for n in ['QtCore','QtGui','QtNetwork','QtQml','QtQuick']]
    crt = SDK/'usr/lib/arm-linux-gnueabihf'
    def gccfile(name):
        return subprocess.check_output([str(CC),'-print-file-name='+name],text=True).strip()
    command = [str(CXX)]+cxxflags+flags+options+['-nostartfiles','-nodefaultlibs',str(crt/'Scrt1.o'),str(crt/'crti.o'),gccfile('crtbeginS.o')]
    command += list(map(str,sources)) + ['-Wl,--allow-shlib-undefined','-Wl,-rpath,$ORIGIN']
    command += [str(LIB/('libQt5'+n+'.so.5.13.2')) for n in (['Gui','Core']if mode=='camera'else['Quick','Qml','Gui','Network','Core'])]
    if mode=='qt': command += [str(ROOT/'board/runtime/nav/liblive_integer_frame.so')]
    command += [str(LIB/'libstdc++.so.6.0.27')]+libraries
    name='medcomm_camera'if mode=='camera'else'medcomm_touch_ui'
    command += [str(crt/'libc_nonshared.a'),gccfile('crtendS.o'),str(crt/'crtn.o'),'-o',str(OUT/name)]
    build(name,command,sources)
elif mode=='tcn':
    if args.tf_source is None or args.tf_dependencies is None:
        parser.error('tcn requires --tf-source and --tf-dependencies')
    folder = native/'tcn'
    objects = OUT/'tcn_objects'
    objects.mkdir(exist_ok=True)
    includes = [args.tf_source,
                args.tf_dependencies/'flatbuffers/include',
                args.tf_dependencies/'gemmlowp',
                args.tf_dependencies/'abseil-cpp', folder]
    names = ['i8_math.cc','i8_client.cc','sha256.cc','i8_delegate.cc','i8_bridge.cc',
             'shared_owner.cc','raw_delegate.cc','prelu_device.cc','prelu_delegate.cc',
             'direct_device.cc','host_unused_person_stub.cc','tcn_bridge.cc','boundary_integer.c']
    sources = [folder/name for name in names]
    link_only = args.link_only
    with (OUT/'tcn_compile.log').open('a' if link_only else 'w',encoding='utf-8') as log:
        for source in sources:
            if link_only:
                break
            is_c = source.suffix=='.c'
            command = [str(CC if is_c else CXX)]+(['-std=c11'] if is_c else cxxflags)+flags
            command += ['-I'+str(p) for p in includes]+['-c',str(source),'-o',str(objects/(source.stem+'.o'))]
            log.write(json.dumps(command)+'\n');log.flush()
            code = subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,env=env).returncode
            if code:
                (OUT/'tcn_result.json').write_text(json.dumps(dict(status='OBJECT_COMPILE_FAILED',source=source.name,returncode=code)),'utf-8')
                raise SystemExit(code)
    dependency = args.backend_library.resolve() if args.backend_library else ROOT/'build/artifacts/arm/libgesture_tflite_pl.so'
    crt = SDK/'usr/lib/arm-linux-gnueabihf'
    def gccfile(name):
        return subprocess.check_output([str(CC),'-print-file-name='+name],text=True).strip()
    command = [str(CXX),'-shared','-nostdlib']+flags+[str(crt/'crti.o'),gccfile('crtbeginS.o')]+list(map(str,sorted(objects.glob('*.o'))))
    command += [str(dependency),str(LIB/'libstdc++.so.6.0.27')]+libraries
    command += ['-lgcc','-Wl,-rpath,$ORIGIN','-Wl,-z,defs','-Wl,--version-script,'+str(folder/'exports.map'),
                '-Wl,-rpath-link,'+str(LIB),gccfile('crtendS.o'),str(crt/'crtn.o'),'-o',str(OUT/'libgesture_lite_i8_v12.so')]
    build('libgesture_lite_i8_v12.so',command,sources)
else:
    raise SystemExit('Use native, qt or tcn')

if any(r.get("status")=="COMPILE_FAILED" for r in rows):
    raise SystemExit(1)
