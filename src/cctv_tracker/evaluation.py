"""Duration-weighted occupancy evaluation against human annotations."""
import argparse
from contextlib import closing
import json
import math
from pathlib import Path
import time

from .secure_store import atomic_write


def validate_annotations(value):
    if value.get('version') != 1 or not value.get('zones'):
        raise ValueError('Annotations require version 1 and at least one zone')
    from .config import Zone
    ids = set()
    for zone in value['zones']:
        Zone(zone['id'], zone['name'], tuple(tuple(p) for p in zone['polygon']))
        if zone['id'] in ids:
            raise ValueError('Duplicate annotated zone')
        ids.add(zone['id'])
        previous = 0
        if not zone.get('intervals'):
            raise ValueError('Each zone needs human-labeled intervals')
        for row in zone['intervals']:
            start, end = row['start_seconds'], row['end_seconds']
            if not all(type(v) in (int, float) and math.isfinite(v) for v in (start, end)) or start < previous or end <= start or row['state'] not in {'OCCUPIED', 'EMPTY', 'UNKNOWN'}:
                raise ValueError('Annotation intervals must be ordered, nonoverlapping and positive')
            previous = end
    return value


def evaluate(truth, predictions, minimum_coverage):
    validate_annotations(truth)
    if not math.isfinite(minimum_coverage) or not 0 < minimum_coverage <= 1:
        raise ValueError('Set the pilot minimum coverage explicitly (0, 1]')
    matrix = {a: {b: 0.0 for b in ('OCCUPIED', 'EMPTY', 'UNKNOWN')} for a in ('OCCUPIED', 'EMPTY')}
    per_zone = []
    for zone in truth['zones']:
        predicted = sorted(predictions.get(zone['id'], []), key=lambda p: p['start_seconds'])
        previous = 0
        for row in predicted:
            if any(type(row[k]) not in (int,float) or not math.isfinite(row[k]) for k in ('start_seconds','end_seconds')) or row['start_seconds'] < previous or row['end_seconds'] <= row['start_seconds'] or row['state'] not in {'OCCUPIED', 'EMPTY', 'UNKNOWN'}:
                raise ValueError('Predicted intervals overlap or are invalid')
            previous = row['end_seconds']
        valid, total = 0.0, 0.0
        for expected in zone['intervals']:
            if expected['state'] == 'UNKNOWN':
                continue
            left, end = expected['start_seconds'], expected['end_seconds']
            total += end - left
            for observed in predicted:
                a, b = max(left, observed['start_seconds']), min(end, observed['end_seconds'])
                if b <= a:
                    continue
                if a > left:
                    matrix[expected['state']]['UNKNOWN'] += a - left
                matrix[expected['state']][observed['state']] += b - a
                if observed['state'] != 'UNKNOWN':
                    valid += b - a
                left = b
            if left < end:
                matrix[expected['state']]['UNKNOWN'] += end - left
        per_zone.append({'zone_id': zone['id'], 'eligible_seconds': total, 'observed_seconds': valid, 'coverage': valid / total if total else None})
    total = sum(sum(row.values()) for row in matrix.values())
    unknown = sum(row['UNKNOWN'] for row in matrix.values())
    coverage = (total - unknown) / total if total else None
    metrics = {}
    for state in matrix:
        other = 'EMPTY' if state == 'OCCUPIED' else 'OCCUPIED'
        tp, fp, fn = matrix[state][state], matrix[other][state], matrix[state][other]
        metrics[state] = {'precision_valid': tp / (tp + fp) if tp + fp else None,
                          'recall_valid': tp / (tp + fn) if tp + fn else None,
                          'recall_including_unknown': tp / sum(matrix[state].values()) if sum(matrix[state].values()) else None}
    passed = coverage is not None and coverage >= minimum_coverage and all(m[k] is not None and m[k] >= .9 for m in metrics.values() for k in ('precision_valid', 'recall_valid'))
    return {'basis': 'annotated workstation-seconds', 'confusion_seconds': matrix, 'coverage': coverage,
            'unknown_seconds': unknown, 'per_zone': per_zone, 'classes': metrics,
            'gate': {'precision_recall_minimum': .9, 'coverage_minimum': minimum_coverage, 'passed': passed}}


def replay_video(video, annotations, output, *, detector_kind='yolox-openvino', device='GPU', minimum_coverage):
    import av
    from .frame_image import encode_frame
    from .config import Settings, Zone, Rules
    from .engine import create_detector
    from .persistence import Database
    from .pipeline import Pipeline
    from .vision import Detection
    truth = validate_annotations(json.loads(Path(annotations).read_text(encoding='utf-8')))
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)  # Never overwrite a previous evaluation.
    zones = tuple(Zone(z['id'], z['name'], tuple(tuple(p) for p in z['polygon'])) for z in truth['zones'])
    rules = Rules(**truth.get('rules', {'max_evidence_gap_seconds': 1}))
    settings = Settings(database=output / 'evaluation.sqlite3', zones=zones, rules=rules)
    detector = create_detector(detector_kind, device)
    anchor, pipeline, frames, times = 1_800_000_000_000_000, None, 0, []
    first_time, last_time, sampled = None, None, -math.inf
    corrupt_dropped, duplicates_dropped, sequence = 0, 0, 0
    last_evidence = None
    try:
        with closing(Database(settings.database)) as db, av.open(str(video)) as source:
            for frame in source.decode(video=0):
                if frame.time is None:
                    raise ValueError('Video needs reliable presentation timestamps')
                first_time = frame.time if first_time is None else first_time
                elapsed = frame.time - first_time
                if last_time is not None and elapsed < last_time:
                    raise ValueError('Video timestamps are not monotonic')
                duplicate = last_time == elapsed
                last_time = elapsed
                if frame.is_corrupt:
                    corrupt_dropped += 1
                    continue
                if duplicate:
                    duplicates_dropped += 1
                    continue
                if elapsed - sampled + 1e-9 < 1 / settings.inference_fps:
                    continue
                sampled = elapsed
                jpeg, _, _ = encode_frame(frame)
                before = time.perf_counter()
                result = detector.detect(jpeg)
                times.append((time.perf_counter() - before) * 1000)
                if pipeline is None:
                    pipeline = Pipeline(settings, db, anchor, 'ANNOTATED_VIDEO_REPLAY', detector.sha, detector.manifest)
                frames += 1
                sequence += 1
                candidates = result.get('tracking_candidates',result['detections'])
                pipeline.feed([Detection(tuple(d['box']), d['confidence']) for d in candidates], anchor + round(elapsed * 1e6), round(elapsed * 1e9), sequence, 'video-1')
                last_evidence = elapsed
            if not frames:
                raise ValueError('Video contains no evaluable frames')
            if max(r['end_seconds'] for z in truth['zones'] for r in z['intervals']) > last_time:
                raise ValueError('Annotations extend beyond the last video timestamp')
            if last_time > last_evidence:
                # The unmeasured tail remains UNKNOWN, never backfilled with presence.
                pipeline.feed([],anchor+round(last_time*1e6),round(last_time*1e9),sequence+1,'video-1','EVALUATION_END_GAP')
            pipeline.finish('COMPLETED'); pipeline = None
            predictions = {}
            for zone in zones:
                # Resolve through the stored name/config rather than assuming ID construction.
                found = db.conn.execute('SELECT id FROM workspaces WHERE name=?', (zone.name,)).fetchall()
                if len(found) != 1:
                    raise ValueError('Zone names must be unique for evaluation')
                workspace = found[0][0]
                predictions[zone.id] = [{'start_seconds': (r['start_utc_us'] - anchor) / 1e6,
                                        'end_seconds': (r['evidence_until_utc_us'] - anchor) / 1e6, 'state': r['state']}
                                       for r in db.conn.execute('SELECT * FROM zone_intervals WHERE workspace_id=? AND evidence_until_utc_us>start_utc_us ORDER BY start_utc_us', (workspace,))]
            result = evaluate(truth, predictions, minimum_coverage)
        import statistics
        result.update(source='USER_VIDEO_REPLAY', annotation_source=truth.get('annotation_source', 'user-provided, review required'), frames=frames, video_seconds=last_time,
                      inference_ms_p50=statistics.median(times), inference_ms_p95=sorted(times)[math.ceil(len(times)*.95)-1], model=dict(detector.manifest),
                      corrupt_frames_dropped=corrupt_dropped,duplicate_pts_dropped=duplicates_dropped,
                      image_pipeline='shared live capture JPEG transform', wall_clock_capacity_validated=False)
        atomic_write(output / 'predictions.json', json.dumps(predictions, indent=2).encode())
        atomic_write(output / 'result.json', json.dumps(result, indent=2).encode())
        return result
    finally:
        if pipeline:
            pipeline.lease.close()


def main():
    parser = argparse.ArgumentParser(description='Evaluate a local CCTV recording against human zone/state annotations')
    parser.add_argument('--video', required=True, type=Path)
    parser.add_argument('--annotations', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--min-coverage', required=True, type=float)
    parser.add_argument('--detector', choices=['yolox', 'yolox-openvino'], default='yolox-openvino')
    parser.add_argument('--device', choices=['CPU', 'GPU'], default='GPU')
    args = parser.parse_args()
    result = replay_video(args.video, args.annotations, args.output, detector_kind=args.detector, device=args.device, minimum_coverage=args.min_coverage)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
