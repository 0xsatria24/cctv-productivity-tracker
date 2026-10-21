"""Profile a running local dashboard without changing its monitoring policy."""
import argparse
import json
from pathlib import Path
import statistics
import time
from uuid import uuid4

import psutil
import requests


def distribution(values):
    if not values:
        return None
    ordered = sorted(values)
    return {'mean': round(statistics.mean(values), 2),
            'p95': round(ordered[min(len(ordered)-1, int(len(ordered)*.95))], 2),
            'p99': round(ordered[min(len(ordered)-1, int(len(ordered)*.99))], 2)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:8767')
    parser.add_argument('--launch', type=Path, default=Path('runtime/recording-feature-preview/launch.json'))
    parser.add_argument('--seconds', type=int, default=30)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    session = requests.Session()
    session.get(args.url+'/', timeout=3).raise_for_status()
    launcher = psutil.Process(json.loads(args.launch.read_text())['launcher_pid'])
    servers = [p for p in launcher.children(recursive=True) if '-m cctv_tracker' in ' '.join(p.cmdline())]
    if not servers:
        raise RuntimeError('Owned dashboard server not found')
    server = servers[0]
    viewer = 'profile-' + uuid4().hex
    def lease():
        wall = session.get(args.url+'/pilot/v1/camera-wall', timeout=4).json()
        ids = [c['id'] for c in wall['cameras'] if c.get('analysis')]
        session.post(args.url+'/pilot/v1/camera-wall/view', headers={'Origin':args.url},
                     json={'viewer_id':viewer,'camera_ids':ids}, timeout=4).raise_for_status()
    lease()
    time.sleep(5)  # Include visible previews and allow their capture processes to start.
    samples, timings, inference, source_age, cpu, rss, processes = [], {}, {}, {}, [], [], []
    previous_cpu = {}
    started = previous_at = time.perf_counter()
    while time.perf_counter()-started < args.seconds:
        tick = time.perf_counter()
        lease()
        procs = [server, *server.children(recursive=True)]
        delta, memory = 0, 0
        for process in procs:
            try:
                times = process.cpu_times(); current = times.user+times.system
                if process.pid in previous_cpu:
                    delta += max(0, current-previous_cpu[process.pid])
                previous_cpu[process.pid] = current
                memory += process.memory_info().rss
            except psutil.Error:
                pass
        if samples:
            cpu.append(delta/max(.001,tick-previous_at)*100)
        previous_at = tick
        rss.append(memory/2**20); processes.append(len(procs))
        wall = session.get(args.url+'/pilot/v1/camera-wall', timeout=4)
        wall.raise_for_status()
        cameras = []
        for camera in wall.json()['cameras']:
            if not camera.get('analysis'):
                continue
            cid, state = camera['id'], camera['engine']
            packet = session.get(args.url+f'/pilot/v1/camera-wall/cameras/{cid}/observation?metadata_only=true', timeout=3).json()
            image = session.get(args.url+f'/pilot/v1/camera-wall/cameras/{cid}/frame.jpg?smooth=true', timeout=3)
            measured = packet.get('observation')
            row = {'id':cid,'name':camera['name'],'processed':state['processed'],
                   'preview_sequence':int(image.headers.get('X-Frame-Sequence',0)),
                   'sequence':packet.get('sequence'), 'performance':state.get('performance'),
                   'activity':[{'id':d.get('track_id'),**d.get('activity',{})} for d in (measured or {}).get('detections',[])],
                   'measured_boxes':len((measured or {}).get('detections',[])),
                   'predicted_tracks':[d['track_id'] for d in (measured or {}).get('display_predictions',[])],
                   'tracks':[d['track_id'] for d in (measured or {}).get('detections',[]) if d.get('track_id')]}
            if measured and packet.get('sequence') != timings.get(cid,{}).get('last_sequence'):
                timing = timings.setdefault(cid, {'last_sequence':None,'latency_ms':[]})
                timing['last_sequence'] = packet['sequence']
                timing['latency_ms'].append(max(0,packet['source_age_ms']-packet['result_age_ms']))
                inference.setdefault(cid,[]).append(measured['inference_ms'])
                source_age.setdefault(cid,[]).append(packet['source_age_ms'])
            cameras.append(row)
        samples.append({'seconds':time.perf_counter()-started,'cameras':cameras,'rss_mb':rss[-1]})
        time.sleep(max(0,.5-(time.perf_counter()-tick)))
    elapsed = samples[-1]['seconds']-samples[0]['seconds']
    cameras = []
    for last in samples[-1]['cameras']:
        first = next((c for c in samples[0]['cameras'] if c['id']==last['id']),None)
        if first:
            cid = last['id']
            cameras.append({'id':cid,'name':last['name'],'processed_fps':round((last['processed']-first['processed'])/elapsed,2),
                'preview_capture_fps':round((last['preview_sequence']-first['preview_sequence'])/elapsed,2),
                'local_capture_to_result_ms':distribution(timings.get(cid,{}).get('latency_ms',[])),
                'detector_total_ms':distribution(inference.get(cid,[])), 'polled_result_source_age_ms':distribution(source_age.get(cid,[])),
                'performance':last['performance']})
    result = {'duration_seconds':round(elapsed,2),'cameras':cameras,'server_process_count':distribution(processes),
              'cpu_percent_one_core_100':distribution(cpu),'rss_tree_mb':distribution(rss),'rss_tree_peak_mb':round(max(rss),2),
              'rss_last_minus_first_mb':round(rss[-1]-rss[0],2),
              'limitations':['Local capture timestamps start after decoding, not at camera exposure.',
                'RSS sums processes and can count shared pages more than once. Replay publishers and browser are excluded.',
                'No annotated identity ground truth: no IDF1, HOTA or true ID-switch claim.',
                'Preview and inference sample the stream at different rates; their FPS difference is not a transport-drop count.']}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps({'summary':result,'samples':samples},indent=2))
    session.post(args.url+'/pilot/v1/camera-wall/view', headers={'Origin':args.url},
                 json={'viewer_id':viewer,'camera_ids':[]}, timeout=4)
    print(json.dumps(result),flush=True)


if __name__=='__main__':
    main()
