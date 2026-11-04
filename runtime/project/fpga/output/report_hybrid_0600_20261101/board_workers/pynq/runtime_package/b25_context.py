"""Fresh, source-locked B25+original10ms-tap admission. Import performs no I/O."""
from pathlib import Path
import hashlib,json,os,re,subprocess,time,math
RUNTIME=Path('/home/xilinx/jupyter_notebooks/2026FPGA_project/03_b_smoke_test')
TAPROOT=Path('/home/xilinx/b_audio_envelope_r2')
UNIT='b-speech-standby.service'
PYTHON='/usr/local/share/pynq-venv/bin/python3'
PINS={
 'board_standby_linein_model.py':'c419a81b4fb97dec35fa165fb39c93141dea250839fa31f8da37b8b1795d5f90',
 'staff_classifier_active_speech_float32_pc_mic_selected.npz':'c98bd72ad0661e839cf0bdf6767a5ae8f932ac15ed3c59f6f401912165490692',
 'reliable_sender.py':'6acd7e63b9b574c8fea5bd46534571461f4ef59fbd6be9fd5c3d8b7fdbe78b15',
 'staff_speech_intents_v1.json':'21633ad377bf3454e3834ef289c9d2daaaf613fec582c64c11b42fb2e25d2ffa',
 'tap/run_audio_envelope.py':'896b6701acd1658eb3668f8c403a8bfc169bf7bf800073396c97c1cc3b6b1fb4',
 'tap/envelope_tap.py':'fe1faa1b46832ad46ac5047b29f00eb127c412475b1630c78528a06463f5bd2c'}
CONFIG=RUNTIME/'b_standby_config.json'
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def pin_paths():return {str(TAPROOT/n[4:]if n.startswith('tap/')else RUNTIME/n):v for n,v in PINS.items()}
def command(*args):return subprocess.check_output(list(args),stderr=subprocess.STDOUT,universal_newlines=True,timeout=5).strip()
def argv_expected():return [PYTHON,'-B',str(TAPROOT/'run_audio_envelope.py'),'--config',str(CONFIG)]
def read_process_environment(pid):
 raw=Path('/proc',str(pid),'environ').read_bytes();result={}
 for field in raw.split(bytes([0])):
  if not field:continue
  name,value=field.split(b'=',1);result[os.fsdecode(name)]=os.fsdecode(value)
 return result

def validate_evidence(e,now_ns):
 if e.get('service_active')!='active'or e.get('service_substate')!='running':raise ValueError('Current B25 service is not active/running')
 identity=e.get('service_process',{})
 if type(identity.get('pid'))is not int or identity['pid']<2 or type(identity.get('start_ticks'))is not int or identity['start_ticks']<1:raise ValueError('Fresh B25 PID/start identity required')
 if e.get('speech_argv')!=argv_expected():raise ValueError('Current B service is not the exact original10ms wrapper+config argv')
 for key in ['cmd_sha256']:
  if not isinstance(identity.get(key),str)or not re.fullmatch('[0-9a-f]{64}',identity[key]):raise ValueError('Nonempty command identity required')
 for key in ['environment_sha256','unit_config_sha256','config_sha256']:
  if not isinstance(e.get(key),str)or not re.fullmatch('[0-9a-f]{64}',e[key]):raise ValueError('Fresh environment/unit/config hashes required')
 if e.get('pinned_files')!=pin_paths():raise ValueError('B25 source/model/sender/catalog/10ms wrapper bytes differ')
 if e.get('catalog_classes')!=list(range(25)):raise ValueError('Current B25 catalog does not contain exact classes0..24')
 if e.get('source_sample_rate_hz')!=48000 or e.get('bin_ms')!=10 or e.get('tap_running')is not True:raise ValueError('Current original48k/10ms tap not active')
 age=now_ns-e.get('tap_source_end_ns',-1)
 if not 0<=age<=2000000000:raise ValueError('Current real audio tap source is stale or future')
 if e.get('tap_extra_record_calls')!=0:raise ValueError('Original tap no-extra-record contract differs')
 validate_voice_fields(e,now_ns)
 return e

def collect_snapshot(process):
 pid=int(command('systemctl','show',UNIT,'-p','MainPID','--value'))
 if pid<2:raise RuntimeError('B25 MainPID absent')
 raw=Path('/proc',str(pid),'cmdline').read_bytes();identity=process(pid)
 paths=pin_paths();actual={k:sha(k)for k in paths}
 catalog=json.loads((RUNTIME/'staff_speech_intents_v1.json').read_text());rows=catalog['intents']+catalog['rejection_classes']
 tap=json.loads(Path('/run/b-audio-envelope/state.json').read_text());observer=json.loads(Path('/run/b-speech-ui/state.json').read_text());now=time.monotonic_ns()
 source_stamp=observer.get('updated_monotonic');voice_stamp=round(source_stamp*1000000000)if type(source_stamp)in(int,float)and math.isfinite(source_stamp)else None
 voice_stats=observer.get('communication_stats');voice_stats=voice_stats if isinstance(voice_stats,dict)else {}
 e=dict(service_active=command('systemctl','is-active',UNIT),service_substate=command('systemctl','show',UNIT,'-p','SubState','--value'),service_process=identity,speech_argv=[os.fsdecode(x)for x in raw.split(bytes([0]))if x],environment_sha256=sha(Path('/proc',str(pid),'environ')),unit_config_sha256=hashlib.sha256(command('systemctl','cat',UNIT).encode()).hexdigest(),config_sha256=sha(CONFIG),pinned_files=actual,catalog_classes=sorted(x['model_class']for x in rows),source_sample_rate_hz=tap.get('sample_rate_hz'),bin_ms=tap.get('bin_ms'),tap_running=tap.get('running'),tap_source_end_ns=tap.get('source_end_ns'),tap_extra_record_calls=tap.get('extra_record_calls'),tap_session_id=tap.get('session_id'),voice_phase=observer.get('phase'),voice_remote_context_available=observer.get('remote_context_available'),voice_sender_queue_depth=voice_stats.get('queue_depth'),voice_observer_updated_ns=voice_stamp,captured_monotonic_ns=now)
 validate_evidence(e,now)
 if process(pid)!=identity or hashlib.sha256(raw).hexdigest()!=identity['cmd_sha256']:raise RuntimeError('B25 service changed during fresh snapshot')
 e.update(speech_source=str(RUNTIME/'board_standby_linein_model.py'),speech_source_sha256=PINS['board_standby_linein_model.py'],speech_entry=str(TAPROOT/'run_audio_envelope.py'),entry_argv=e['speech_argv'][2:],boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip(),file_hashes=dict(actual,**{str(CONFIG):e['config_sha256']}),model_classes=25,raw_PCM_saved=False,extra_record_calls=0)
 # Include all imported B modules as immutable within this activation/restore window.
 for name in ('board_observer.py','board_wav_to_logmel.py','board_model_smoke.py','model_runtime.py'):
  path=RUNTIME/name
  if path.is_file():e['file_hashes'][str(path)]=sha(path)
 return e

def verify_files(c):
 if c.get('pinned_files')!=pin_paths()or c.get('model_classes')!=25:raise RuntimeError('B25 context source locks differ')
 expected=dict(c['file_hashes'])
 if any(expected.get(k)!=v for k,v in pin_paths().items())or expected.get(str(CONFIG))!=c['config_sha256']:raise RuntimeError('B25 context omitted pinned input')
 for path,digest in expected.items():
  if sha(path)!=digest:raise RuntimeError('Original B25/tap/config input changed: '+path)
 if c.get('speech_entry')!=str(TAPROOT/'run_audio_envelope.py')or c.get('entry_argv')!=argv_expected()[2:]:raise RuntimeError('B25 original wrapper entry differs')

def verify_snapshot(c,process):
 if not 0<=time.monotonic_ns()-c['captured_monotonic_ns']<=300000000000:raise RuntimeError('B25 baseline older than300seconds')
 verify_files(c);now=collect_snapshot(process)
 for key in ('service_process','speech_argv','environment_sha256','unit_config_sha256','config_sha256','pinned_files','file_hashes','tap_session_id','boot_id'):
  if now[key]!=c[key]:raise RuntimeError('Current B25 source/service/environment changed: '+key)
 return now

def validate_voice_fields(e,now_ns,not_before_ns=None):
 if type(e.get('voice_sender_queue_depth'))is not int or e['voice_sender_queue_depth']!=0:raise ValueError('Current B25 ReliableSender queue must be explicitly0')
 if e.get('voice_phase')!='waiting'or e.get('voice_remote_context_available')is not False:raise ValueError('Current B25 must be waiting without remote capture context')
 stamp=e.get('voice_observer_updated_ns')
 if type(stamp)is not int or not 0<=now_ns-stamp<=10000000000:raise ValueError('Current B25 observer missing/stale/future (>10seconds)')
 if not_before_ns is not None and(type(not_before_ns)is not int or stamp<not_before_ns):raise ValueError('Observer predates the owned private speech process')
 return e

def read_voice_quiet(not_before_ns=None):
 observer=json.loads(Path('/run/b-speech-ui/state.json').read_text());now=time.monotonic_ns();value=observer.get('updated_monotonic');stamp=round(value*1000000000)if type(value)in(int,float)and math.isfinite(value)else None
 stats=observer.get('communication_stats');stats=stats if isinstance(stats,dict)else {}
 row=dict(voice_phase=observer.get('phase'),voice_remote_context_available=observer.get('remote_context_available'),voice_sender_queue_depth=stats.get('queue_depth'),voice_observer_updated_ns=stamp,observed_monotonic_ns=now,source='/run/b-speech-ui/state.json')
 validate_voice_fields(row,now,not_before_ns);row['idle']=True;return row
