"""Read-only low-latency stream of the existing B RAM audio meter.
No audio device is opened, no samples/model/config are changed on the board.
"""
from collections import deque
from pathlib import Path
import copy,json,math,shlex,threading,time,uuid

REMOTE_STREAM = "\nfrom pathlib import Path\nimport json,sys,time\nlegacy=Path('/run/b-speech-ui/state.json');dense=Path('/run/b-audio-envelope/state.json')\nboot=Path('/proc/sys/kernel/random/boot_id').read_text().strip()\nprint(json.dumps(dict(type='ready',boot_id=boot,monotonic_ns=time.monotonic_ns())),flush=True)\nhello=json.loads(sys.stdin.readline());print(json.dumps(dict(type='anchor',boot_id=boot,remote_monotonic_ns=time.monotonic_ns(),echo=hello.get('nonce'))),flush=True)\nlast=None;beat=0\nwhile True:\n try:\n  d=None\n  if dense.exists():\n   raw=dense.read_bytes()\n   if len(raw)>1048576:raise ValueError('envelope state too large')\n   v=json.loads(raw)\n   if v.get('running')and 0<=time.monotonic_ns()-v.get('source_end_ns',0)<=1500000000:d=v\n  if d is not None:\n   identity=('dense',d.get('session_id'),d.get('sequence'))\n   if identity!=last:\n    d.update(type='envelope',boot_id=boot,collected_monotonic_ns=time.monotonic_ns());print(json.dumps(d,allow_nan=False,separators=(',',':')),flush=True);last=identity\n  else:\n   raw=legacy.read_bytes()\n   if len(raw)>1048576:raise ValueError('meter state too large')\n   v=json.loads(raw);identity=('legacy',v.get('session_id'),v.get('updated_monotonic'))\n   if identity!=last:\n    row=dict(type='meter',boot_id=boot,session_id=v.get('session_id'),updated_monotonic=v.get('updated_monotonic'),collected_monotonic_ns=time.monotonic_ns(),level_dbfs=v.get('level_dbfs'),peak=v.get('peak'),chunk_seconds=v.get('chunk_seconds'),phase=v.get('phase'))\n    print(json.dumps(row,allow_nan=False,separators=(',',':')),flush=True);last=identity\n  if time.monotonic()-beat>=.5:print(json.dumps(dict(type='heartbeat',remote_monotonic_ns=time.monotonic_ns()),separators=(',',':')),flush=True);beat=time.monotonic()\n except(OSError,ValueError)as exc:print(json.dumps(dict(type='source_error',error=type(exc).__name__)),flush=True)\n time.sleep(.025)\n"


def finite(value):
    return type(value) in (int,float) and math.isfinite(value)


class AudioStream:
    def __init__(self, connect, stop_event, receipt_path=None):
        self.connect=connect; self.stop=stop_event; self.receipt_path=Path(receipt_path) if receipt_path else None
        self.lock=threading.RLock(); self.thread=None; self.client=None
        self.samples=deque(maxlen=2048); self.intervals=deque(maxlen=20);self.batch_intervals=deque(maxlen=20);self.highres=False;self.last_block_end=None;self.source_sample_rate=None;self.tap_dropped=0;self.tap_compute_ms=None
        self.session=None; self.last_source=None; self.last_value=None
        self.anchor=None; self.connected=False; self.error='等待B板电平流'
        self.received=0; self.reconnects=0; self.duplicate_snapshots=0
        self.last_source_mono=None; self.last_poll_mono=None; self.last_level=None; self.last_peak=None
        self._last_receipt=0.

    def start(self):
        self.thread=threading.Thread(target=self._run,name='B-meter-stream',daemon=True);self.thread.start()

    def close(self):
        if self.client:
            try:self.client.close()
            except Exception:pass
        if self.thread and self.thread is not threading.current_thread():self.thread.join(timeout=2.)

    def _invalidate(self,error):
        with self.lock:self.connected=False;self.error=error

    def _set_anchor(self, remote_ns, sent_ns, received_ns, wall_ms):
        if type(remote_ns)is not int or received_ns<sent_ns or received_ns-sent_ns>1000000000:
            raise ValueError('invalid or slow meter clock anchor')
        with self.lock:
            self.anchor=dict(offset_ns=(sent_ns+received_ns)//2-remote_ns,
                             host_mono_ns=received_ns,host_wall_ms=wall_ms,
                             uncertainty_ms=(received_ns-sent_ns)/2000000.)

    def ingest(self,row, now_mono_ns=None):
        if not isinstance(row,dict)or row.get('type')!='meter':return False
        now=time.monotonic_ns()if now_mono_ns is None else now_mono_ns
        session=row.get('session_id');boot=row.get('boot_id');source=row.get('updated_monotonic')
        db=row.get('level_dbfs');peak=row.get('peak')
        if (not isinstance(session,str)or not session or not isinstance(boot,str)or not boot
                or not finite(source)or source<0 or not finite(db)or not -240<=db<=0
                or not finite(peak)or not 0<=peak<=1):
            return False
        with self.lock:
            if self.anchor is None:return False
            mapped=int(source*1000000000)+self.anchor['offset_ns'];age=(now-mapped)/1000000.
            if age < -self.anchor['uncertainty_ms']-10 or age>2000:return False
            key=boot+':'+session
            if key!=self.session:
                self.samples.clear();self.intervals.clear();self.last_source=None;self.last_value=None;self.session=key;self.highres=False;self.last_block_end=None;self.batch_intervals.clear()
            self.connected=True;self.error='';self.last_poll_mono=now
            if self.last_source is not None and source<=self.last_source:return False
            if self.last_source is not None:self.intervals.append((source-self.last_source)*1000.)
            self.last_source=source
            # Observer phase-only writes can repeat the last audio values.
            # Do not manufacture a second audio observation from that rewrite.
            value=(db,peak)
            if value==self.last_value:
                self.duplicate_snapshots+=1;return False
            self.last_value=value;self.last_source_mono=mapped;self.last_level=db;self.last_peak=peak
            t_ms=self.anchor['host_wall_ms']+(mapped-self.anchor['host_mono_ns'])/1000000.
            duration=row.get('chunk_seconds');duration_ms=duration*1000 if finite(duration)and 0<duration<=1 else 250.
            self.samples.append(dict(id=key+':'+str(source),t_ms=t_ms,rms=10**(db/20.),peak=peak,duration_ms=duration_ms))
            self.received+=1
            return True

    def ingest_dense(self,row,now_mono_ns=None):
        now=time.monotonic_ns()if now_mono_ns is None else now_mono_ns
        if not isinstance(row,dict)or row.get('type')!='envelope'or row.get('schema_version')!='b_audio_envelope_v2'or row.get('running')is not True:return False
        session=row.get('session_id');boot=row.get('boot_id');seq=row.get('sequence');end=row.get('source_end_ns');bins=row.get('bins');fs=row.get('sample_rate_hz')
        if not isinstance(session,str)or not session or not isinstance(boot,str)or not boot or type(seq)is not int or seq<1 or type(end)is not int or type(fs)is not int or fs!=48000 or not isinstance(bins,list)or not 1<=len(bins)<=100:return False
        previous=None
        for v in bins:
            if not isinstance(v,dict)or type(v.get('end_ns'))is not int:return False
            if previous is not None and v['end_ns']<=previous:return False
            previous=v['end_ns']
            if any(not finite(v.get(k))for k in ('min','max','rms','peak','duration_ms')):return False
            if not(-1<=v['min']<=v['max']<=1 and 0<=v['rms']<=v['peak']+1e-7 and 0<=v['peak']<=1 and 0<v['duration_ms']<=10.0001):return False
            if abs(v['peak']-max(abs(v['min']),abs(v['max'])))>1e-7:return False
        if bins[-1]['end_ns']!=end:return False
        with self.lock:
            if self.anchor is None:return False
            mapped=end+self.anchor['offset_ns'];age=(now-mapped)/1e6
            if age < -self.anchor['uncertainty_ms']-10 or age>2000:return False
            key=boot+':'+session
            if key!=self.session or not self.highres:
                self.samples.clear();self.intervals.clear();self.batch_intervals.clear();self.last_block_end=None;self.session=key
            if self.last_block_end is not None and end<=self.last_block_end:return False
            if self.last_block_end is not None:self.batch_intervals.append((end-self.last_block_end)/1e6)
            self.last_block_end=end;self.highres=True;self.connected=True;self.error='';self.source_sample_rate=fs
            self.last_source_mono=mapped;self.last_poll_mono=now;self.last_level=20*math.log10(max(bins[-1]['rms'],1e-12));self.last_peak=bins[-1]['peak']
            self.tap_dropped=row.get('dropped_blocks',0);self.tap_compute_ms=row.get('summary_compute_ns',0)/1e6
            for i,v in enumerate(bins):
                t_ms=self.anchor['host_wall_ms']+(v['end_ns']+self.anchor['offset_ns']-self.anchor['host_mono_ns'])/1e6
                self.samples.append(dict(id=key+':'+str(seq)+':'+str(i),t_ms=t_ms,min=v['min'],max=v['max'],rms=v['rms'],peak=v['peak'],duration_ms=v['duration_ms']))
            self.received+=len(bins)
            return True

    def snapshot(self):
        now=time.monotonic_ns()
        with self.lock:
            age=(now-self.last_source_mono)/1000000. if self.last_source_mono is not None else None
            available=bool(self.connected and age is not None and 0<=age<=2000)
            anchor=self.anchor or{};intervals=[x for x in self.intervals if 50<=x<=2000]
            interval=10. if self.highres else(sorted(intervals)[len(intervals)//2]if intervals else None)
            batch=sorted(self.batch_intervals)[len(self.batch_intervals)//2]if self.batch_intervals else None
            items=[copy.deepcopy(x)for x in self.samples if anchor and anchor['host_mono_ns']+(x['t_ms']-anchor['host_wall_ms'])*1000000>=now-9000000000]if available else[]
            observed=int(time.time()*1000)-max(0,age)if age is not None else None
            return dict(available=available,kind='rms_envelope',source='PYNQ HP+MIC · 10ms真实包络'if self.highres else'PYNQ HP+MIC · 原电平低密度回退',
                session_id=self.session,observed_at_ms=observed,stale_after_ms=2000,
                rms_dbfs=self.last_level if available else None,
                peak_dbfs=20*math.log10(max(self.last_peak,1e-12))if available else None,
                sample_rate_hz=None,meter_rate_hz=1000./interval if interval else None,
                source_interval_ms=interval,batch_interval_ms=batch,source_sample_rate_hz=self.source_sample_rate if self.highres else None,density_mode='true_10ms_minmax'if self.highres else'legacy_meter',tap_compute_ms=self.tap_compute_ms,dropped_source_blocks=self.tap_dropped,samples=items,waveform=[x['rms']for x in items],
                window_ms=8000,status_text=('10ms真实幅值包络 · 48kHz原采音'if self.highres else'旧电平低密度回退')if available else'电平流未连接或已过期',
                stream_connected=self.connected,source_age_ms=age,clock_uncertainty_ms=anchor.get('uncertainty_ms'),
                unique_samples_received=self.received,duplicate_state_values_skipped=self.duplicate_snapshots,
                reconnect_count=self.reconnects,error=self.error if not available else'')

    def _write_receipt(self):
        if not self.receipt_path or time.monotonic()-self._last_receipt<2:return
        self._last_receipt=time.monotonic()
        try:
            s=self.snapshot();s.update(read_only=True,audio_device_opened=False,collector_restarts_B_service=False,
                                      waveform_is_PCM=False)
            tmp=self.receipt_path.with_suffix('.tmp');tmp.write_text(json.dumps(s,ensure_ascii=False,indent=2),encoding='utf-8');tmp.replace(self.receipt_path)
        except (OSError,ValueError):pass

    def _run(self):
        while not self.stop.is_set():
            client=None
            try:
                client=self.connect('pynq');self.client=client
                i,o,e=client.exec_command('python3 -B -u -c '+shlex.quote(REMOTE_STREAM),timeout=3)
                ready=json.loads(o.readline())
                if ready.get('type')!='ready':raise ValueError('missing meter ready')
                nonce=uuid.uuid4().hex;sent=time.monotonic_ns()
                i.write(json.dumps(dict(nonce=nonce))+'\n');i.flush()
                row=json.loads(o.readline());received=time.monotonic_ns()
                if row.get('echo')!=nonce or row.get('type')!='anchor':raise ValueError('invalid meter anchor')
                self._set_anchor(row['remote_monotonic_ns'],sent,received,int(time.time()*1000))
                with self.lock:self.connected=True;self.error='';self.reconnects+=1
                while not self.stop.is_set():
                    line=o.readline(8193)
                    if not line:raise ConnectionError('B meter stream closed')
                    if len(line)>8192:raise ValueError('meter line exceeds 8 KiB')
                    row=json.loads(line)
                    if row.get('type')=='source_error':self._invalidate('B电平源暂不可读')
                    elif row.get('type')=='meter':self.ingest(row)
                    elif row.get('type')=='envelope':self.ingest_dense(row)
                    self._write_receipt()
            except Exception as exc:
                self._invalidate(type(exc).__name__+': '+str(exc)[:180])
            finally:
                self.client=None
                if client:
                    try:client.close()
                    except Exception:pass
            self._write_receipt();self.stop.wait(.8)
