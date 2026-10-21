"""Manually launched 24/72-hour read-only observer of an already running dashboard.

Does not start cameras, change recording policy, inject faults, or stop the app.
Use --dry-run to inspect configuration without starting the observation period.
"""
import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import shutil
import signal
from threading import Event
import time
from urllib.parse import urlsplit

from cctv_tracker.dataset import write_json


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def validate_options(args):
    parsed = urlsplit(args.url)
    if parsed.scheme != 'http' or parsed.hostname not in {'127.0.0.1','localhost'} or parsed.username or parsed.password or parsed.path not in {'','/'} or parsed.query or parsed.fragment:
        raise ValueError('Use the loopback dashboard URL without credentials, path or query')
    if parsed.port is not None and not 1 <= parsed.port <= 65535:
        raise ValueError('Invalid dashboard port')
    args.url = args.url.rstrip('/')
    for key, low, high in (('hours',1/60,72),('interval',1,60),('timeout',.1,30),
                          ('grace',0,600),('no_progress',5,600),('max_rss_mb',64,131072),
                          ('max_growth_mb',1,131072),('min_free_mb',1,1048576),
                          ('max_log_mb',1,4096),('min_fps',.01,30),('max_age_ms',100,60000)):
        value = getattr(args,key)
        if not math.isfinite(value) or not low <= value <= high:
            raise ValueError(f'{key} must be finite within [{low}, {high}]')
    if args.no_progress < args.interval:
        raise ValueError('No-progress limit must be at least the sampling interval')
    if args.pid is not None and args.pid <= 0:
        raise ValueError('PID must be positive')
    return args


class Monitor:
    """Bounded state: no frame history, no native errors or camera URLs retained."""
    def __init__(self, ids, *, grace, no_progress, min_fps, max_age_ms):
        self.ids, self.grace, self.no_progress = set(ids),grace,no_progress
        self.min_fps, self.max_age_ms = min_fps,max_age_ms
        self.previous, self.last_progress, self.conditions, self.findings = {},{}, {},{}

    def condition(self, key, bad, elapsed, camera=None, persistence=None):
        identity = (key,camera)
        if bad:
            self.conditions.setdefault(identity,elapsed)
            limit=self.no_progress if persistence is None else persistence
            if elapsed >= self.grace and elapsed-self.conditions[identity] >= limit:
                value = self.findings.setdefault(identity,{'code':key,'camera_id':camera,'first_seconds':elapsed,'last_seconds':elapsed,'samples':0})
                value.update(last_seconds=elapsed,samples=value['samples']+1)
        else:
            self.conditions.pop(identity,None)

    def sample(self, wall, elapsed):
        rows = {c['id']:c for c in wall['cameras']}
        summary=[]
        for cid in sorted(self.ids):
            camera = rows.get(cid)
            self.condition('CAMERA_REMOVED',camera is None,elapsed,cid)
            if camera is None:
                continue
            engine=camera.get('engine') or {}
            processed=engine.get('processed',0)
            prev=self.previous.get(cid)
            fps=None
            restarted=False
            if prev:
                restarted=processed < prev[1] or engine.get('session_id') != prev[2]
                if not restarted:
                    fps=max(0,processed-prev[1])/max(.001,elapsed-prev[0])
            if not prev or processed > prev[1] or restarted:
                self.last_progress[cid]=elapsed
            self.previous[cid]=(elapsed,processed,engine.get('session_id'))
            age=None
            latest=engine.get('latest') or {}
            if latest.get('processed_monotonic_ns'):
                age=max(0,(time.perf_counter_ns()-latest['processed_monotonic_ns'])/1e6)
            performance=engine.get('performance') or {}
            stages=performance.get('stages') or {}
            latency=stages.get('capture_to_result_ms',{})
            self.condition('ANALYSIS_STOPPED',not camera.get('analysis'),elapsed,cid)
            self.condition('ENGINE_UNHEALTHY',engine.get('status')=='FAILED' or engine.get('camera_health')!='ONLINE',elapsed,cid)
            self.condition('NO_COMMITTED_PROGRESS',elapsed-self.last_progress[cid]>=self.no_progress,elapsed,cid,persistence=0)
            self.condition('LOW_FPS',fps is not None and fps<self.min_fps,elapsed,cid)
            self.condition('STALE_RESULT',age is None or age>self.max_age_ms,elapsed,cid)
            if restarted:
                key=('SESSION_RESTART',cid)
                value=self.findings.setdefault(key,{'code':'SESSION_RESTART','camera_id':cid,'first_seconds':elapsed,'last_seconds':elapsed,'samples':0})
                value.update(last_seconds=elapsed,samples=value['samples']+1)
            summary.append({'id':cid,'status':engine.get('status'),'health':engine.get('camera_health'),
                            'processed':processed,'effective_fps':fps,'result_age_ms':age,
                            'local_latency_window_ms':latency,'stale_dropped':performance.get('stale_dropped'),
                            'capture':performance.get('capture'),'scheduler':performance.get('scheduler'),
                            'zone_states':[{'id':z['id'],'state':z['state'],'reason':z.get('reason')} for z in latest.get('zones',[])]})
        return summary


def resource_sample(root, previous, elapsed_delta):
    import psutil
    if not root.is_running() or root.status()==psutil.STATUS_ZOMBIE:
        raise RuntimeError('MONITORED_PROCESS_EXITED')
    rss,total,values=0,0,{}
    for process in [root,*root.children(recursive=True)]:
        try:
            times=process.cpu_times();current=times.user+times.system
            key=(process.pid,process.create_time())
            if key in previous:
                total+=max(0,current-previous[key])
            values[key]=current
            rss+=process.memory_info().rss
        except psutil.Error:
            continue
    previous.clear();previous.update(values)
    return {'rss_tree_mb':rss/2**20,'processes':len(values),
            'cpu_percent_one_core_100':total/max(.001,elapsed_delta)*100}


def fetch_wall(session,url,timeout):
    response=session.get(url+'/pilot/v1/camera-wall',timeout=timeout)
    if response.status_code in {401,403}:
        # A restarted app issues a new local session token.
        session.get(url+'/',timeout=timeout).raise_for_status()
        response=session.get(url+'/pilot/v1/camera-wall',timeout=timeout)
    response.raise_for_status()
    return response.json()


def run(args):
    import requests
    import psutil
    args.output.mkdir(parents=True,exist_ok=False)
    stop=Event()
    for name in ('SIGINT','SIGTERM','SIGBREAK'):
        if hasattr(signal,name):
            signal.signal(getattr(signal,name),lambda *_:stop.set())
    result={'version':1,'state':'RUNNING','started_utc':utc_now(),'requested_hours':args.hours,
            'input':'EXISTING_DASHBOARD_API','production_qualified':False,'acceptance_passed':False,
            'configuration':{k:v for k,v in vars(args).items() if k not in {'output','dry_run'}},
            'samples':0,'findings':[],'external_events_file':'manual-events.jsonl',
            'limitations':['API observer does not prove model accuracy, video integrity, restore safety or GUI rendering.',
              'The selected PID process tree excludes the browser and external video publishers.',
              'RSS sums processes and may count shared pages more than once.',
              'Result age is local post-decode age, not camera exposure latency.',
              'P95/P99 values are engine rolling windows, not full-test quantiles.',
              'Manual disconnect, reboot, disk and upload scenarios require separate evidence.']}
    write_json(args.output/'result.json',result)
    write_json(args.output/'manual-events.example.json',{'utc':'2026-10-22T00:00:00+00:00','event':'DISCONNECT_TEST_CAMERA','camera_id':'...','notes':'Record start, recovery and evidence paths in manual-events.jsonl'})
    started=previous_at=time.perf_counter()
    previous_cpu={};peak_rss=0;baseline_rss=None
    root=None
    monitor=None
    session=requests.Session()
    session.trust_env=False  # Never send private loopback requests through an environment proxy.
    try:
        root=psutil.Process(args.pid) if args.pid else None
        session.get(args.url+'/',timeout=args.timeout).raise_for_status()
        wall=fetch_wall(session,args.url,args.timeout)
        ids=args.camera or [c['id'] for c in wall['cameras'] if c.get('analysis')]
        if not ids or set(ids)-{c['id'] for c in wall['cameras'] if c.get('analysis')}:
            raise ValueError('Select existing cameras with analysis running before starting the test')
        monitor=Monitor(ids,grace=args.grace,no_progress=args.no_progress,min_fps=args.min_fps,max_age_ms=args.max_age_ms)
        result['camera_ids']=sorted(monitor.ids)
        result['checks_skipped']=['Ground-truth accuracy','Recording playback and restore','Manual fault injection']
        if root is None:
            result['checks_skipped'].append('Process-tree CPU and RSS: no --pid supplied')
        with (args.output/'samples.jsonl').open('w',encoding='utf-8') as log:
            while not stop.is_set():
                if (args.output/'STOP').exists():
                    stop.set();break
                now=time.perf_counter();elapsed=now-started
                resources=resource_sample(root,previous_cpu,now-previous_at) if root else {}
                previous_at=now
                sample={'utc':utc_now(),'elapsed_seconds':elapsed,'resources':resources,'cameras':[]}
                try:
                    sample['cameras']=monitor.sample(fetch_wall(session,args.url,args.timeout),elapsed)
                    monitor.condition('API_UNAVAILABLE',False,elapsed)
                except (requests.RequestException,ValueError,KeyError,TypeError):
                    sample['api_error']='API_UNAVAILABLE'
                    monitor.condition('API_UNAVAILABLE',True,elapsed)
                free=shutil.disk_usage(args.output).free/2**20
                if root:
                    memory=resources['rss_tree_mb'];peak_rss=max(peak_rss,memory)
                    if elapsed>=args.grace and baseline_rss is None:
                        baseline_rss=memory
                    monitor.condition('RSS_LIMIT',memory>args.max_rss_mb,elapsed)
                    monitor.condition('RSS_GROWTH',baseline_rss is not None and memory-baseline_rss>args.max_growth_mb,elapsed)
                sample['free_disk_mb']=free
                log.write(json.dumps(sample,allow_nan=False)+'\n');log.flush()
                result.update(samples=result['samples']+1,elapsed_seconds=elapsed,rss_peak_mb=peak_rss if root else None,
                              rss_after_warmup_mb=baseline_rss,findings=list(monitor.findings.values()))
                write_json(args.output/'result.json',result)
                if free<args.min_free_mb or log.tell()>args.max_log_mb*2**20:
                    raise RuntimeError('DISK_OR_LOG_LIMIT')
                if elapsed>=args.hours*3600:
                    result['state']='COMPLETED'
                    break
                stop.wait(min(args.interval,max(0,args.hours*3600-(time.perf_counter()-started))))
        if stop.is_set():
            result['state']='CANCELLED'
        result['acceptance_passed']=result['state']=='COMPLETED' and not result['findings'] and result['samples']>=2
    except Exception as error:
        result.update(state='FAILED',error_type=type(error).__name__)
        # Do not log native errors, credentials, request URLs or exception text.
    finally:
        session.close()
        result.update(ended_utc=utc_now(),elapsed_seconds=time.perf_counter()-started)
        write_json(args.output/'result.json',result)
        print(json.dumps({k:result[k] for k in ('state','elapsed_seconds','samples','acceptance_passed')}),flush=True)
    return 0 if result['acceptance_passed'] else 1


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url',default='http://127.0.0.1:8767')
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--hours',type=float,default=24)
    parser.add_argument('--interval',type=float,default=5)
    parser.add_argument('--timeout',type=float,default=5)
    parser.add_argument('--grace',type=float,default=60)
    parser.add_argument('--no-progress',type=float,default=30)
    parser.add_argument('--camera',action='append',help='Camera ID, repeatable. Default: currently analysing cameras.')
    parser.add_argument('--pid',type=int,help='Optional dashboard or supervisor PID for process-tree RSS/CPU measurements')
    parser.add_argument('--max-rss-mb',type=float,default=4096)
    parser.add_argument('--max-growth-mb',type=float,default=512)
    parser.add_argument('--min-free-mb',type=float,default=1024)
    parser.add_argument('--max-log-mb',type=float,default=256)
    parser.add_argument('--min-fps',type=float,default=.5)
    parser.add_argument('--max-age-ms',type=float,default=5000)
    parser.add_argument('--dry-run',action='store_true')
    args=parser.parse_args()
    try:
        validate_options(args)
    except ValueError as error:
        parser.error(str(error))
    if args.dry_run:
        print(json.dumps({'state':'NOT_STARTED','duration_seconds':args.hours*3600,
              'configuration':{k:str(v) if isinstance(v,Path) else v for k,v in vars(args).items()}}))
        return
    raise SystemExit(run(args))


if __name__=='__main__':
    main()
