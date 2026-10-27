"""Private, reproducible person-box evaluation data. No training or camera access."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import statistics
import time

from .secure_store import atomic_write

SCENARIOS = ('normal', 'bending', 'occlusion', 'crossing', 'distant', 'low_light', 'empty')
SPLITS = ('pilot', 'train', 'validation', 'test')


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write_json(path, value):
    atomic_write(path, json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False).encode('utf-8'))


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def manifest_hash(manifest):
    return hashlib.sha256(json.dumps(manifest, sort_keys=True, allow_nan=False).encode()).hexdigest()


def validate_splits(sequences):
    """All recordings of the same site/day stay together, including reused files."""
    groups, hashes, ids = {}, {}, set()
    for sequence in sequences:
        if sequence['id'] in ids or sequence['split'] not in SPLITS or not sequence['group'].strip():
            raise ValueError('Invalid sequence ID, split or recording group')
        ids.add(sequence['id'])
        for mapping, key in ((groups, sequence['group']), (hashes, sequence['sha256'])):
            if key in mapping and mapping[key] != sequence['split']:
                raise ValueError('Dataset leakage: a recording group or source file spans splits')
            mapping[key] = sequence['split']


def prepare(videos, output, *, group, split='pilot', sample_fps=2, seconds=None):
    """Export PTS-indexed, corruption-filtered JPEGs with the live capture sizing."""
    import av
    from .frame_image import encode_frame
    if not group.strip() or split not in SPLITS or not math.isfinite(sample_fps) or not 0 < sample_fps <= 15:
        raise ValueError('Specify a recording group, split and sample FPS in (0,15]')
    if seconds is not None and (not math.isfinite(seconds) or seconds <= 0):
        raise ValueError('Seconds must be positive and finite')
    videos = [Path(p).resolve(strict=True) for p in videos]
    hashes = [digest(p) for p in videos]
    if len(hashes) != len(set(hashes)) or not videos:
        raise ValueError('Supply distinct video files')
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    manifest = {'version': 1, 'purpose': 'PILOT_EVALUATION', 'grouping_policy': 'site and recording day',
                'reuse_rights': 'REVIEW_REQUIRED', 'sample_fps': sample_fps, 'sequences': [],
                'image_pipeline': 'noncorrupt PyAV frame, preserve aspect, long side <=640, JPEG quality 75'}
    labels = {}
    try:
        av.logging.set_level(av.logging.PANIC)
        for path, sha in zip(videos, hashes):
            seq = {'id': 'clip-' + sha[:16], 'source_name': path.name, 'sha256': sha,
                   'group': group, 'split': split, 'source_bytes': path.stat().st_size,
                   'decoded': 0, 'corrupt_dropped': 0, 'duplicate_pts_dropped': 0, 'frames': []}
            directory = output / 'frames' / seq['id']
            directory.mkdir(parents=True)
            first, previous, sampled = None, None, -math.inf
            with av.open(str(path)) as source:
                stream = source.streams.video[0]
                seq['native_fps'] = float(stream.average_rate) if stream.average_rate else None
                for frame in source.decode(video=0):
                    if frame.time is None:
                        raise ValueError('Video requires reliable presentation timestamps')
                    pts = float(frame.time)
                    if previous is not None and pts < previous:
                        raise ValueError('Nonmonotonic video PTS; split the recording first')
                    first = pts if first is None else first
                    elapsed = pts - first
                    if seconds is not None and elapsed > seconds:
                        break
                    seq['decoded'] += 1
                    duplicate = pts == previous
                    previous = pts
                    seq['decoded_until_seconds'] = elapsed
                    if frame.is_corrupt:
                        seq['corrupt_dropped'] += 1
                        continue
                    if duplicate:
                        seq['duplicate_pts_dropped'] += 1
                        continue
                    if elapsed - sampled + 1e-9 < 1 / sample_fps:
                        continue
                    sampled = elapsed
                    jpeg, width, height = encode_frame(frame)
                    number = len(seq['frames']) + 1
                    relative = f'frames/{seq["id"]}/{number:06}.jpg'
                    atomic_write(output / relative, jpeg)
                    key = f'{seq["id"]}:{number}'
                    seq['frames'].append({'key': key, 'number': number, 'seconds': elapsed,
                                          'image': relative, 'sha256': digest(output / relative),
                                          'width': width, 'height': height})
                    labels[key] = {'reviewed': False, 'reviewer': '', 'label_source': 'human',
                                   'scenarios': [], 'persons': [], 'comment': ''}
            if not seq['frames']:
                raise ValueError('Video has no usable sampled frames')
            manifest['sequences'].append(seq)
        validate_splits(manifest['sequences'])
        write_json(output / 'manifest.json', manifest)
        write_json(output / 'labels.json', {'version': 1, 'manifest_sha256': manifest_hash(manifest),
                                          'revision': 0, 'frames': labels})
        write_json(output / 'preparation.json', {'state': 'COMPLETED', 'frames': len(labels),
                   'reviewed_frames': 0, 'accuracy_evaluated': False})
    except BaseException as error:
        write_json(output / 'preparation.json', {'state': 'FAILED', 'error_type': type(error).__name__})
        raise
    return manifest


def frame_index(manifest):
    return {f['key']: (sequence, f) for sequence in manifest['sequences'] for f in sequence['frames']}


def validate_labels(manifest, labels):
    from .vision import Detection
    validate_splits(manifest['sequences'])
    if not isinstance(labels,dict) or labels.get('version') != 1 or labels.get('manifest_sha256') != manifest_hash(manifest):
        raise ValueError('Labels belong to a different manifest')
    if type(labels.get('revision')) is not int or labels['revision'] < 0:
        raise ValueError('Invalid label revision')
    expected = frame_index(manifest)
    if not isinstance(labels.get('frames'),dict) or set(labels['frames']) != set(expected):
        raise ValueError('Labels must include every exported frame exactly once')
    for key, row in labels['frames'].items():
        if not isinstance(row,dict):
            raise ValueError('Frame labels must be objects')
        if type(row.get('reviewed')) is not bool or row.get('label_source') not in {'human', 'assistant', 'pseudo'}:
            raise ValueError('Invalid review state or label provenance')
        if not isinstance(row.get('reviewer'), str) or len(row['reviewer']) > 120:
            raise ValueError('Invalid reviewer')
        if not isinstance(row.get('comment'), str) or len(row['comment']) > 2000:
            raise ValueError('Comment must be text of at most 2000 characters')
        if not isinstance(row.get('scenarios'), list) or set(row['scenarios']) - set(SCENARIOS):
            raise ValueError('Unsupported scenario')
        if row['reviewed'] and (not row['reviewer'].strip() or not row['scenarios']):
            raise ValueError('Reviewed frames require a reviewer and scenario')
        people = row.get('persons')
        if not isinstance(people, list) or len(people) > 128:
            raise ValueError('At most 128 person boxes per frame')
        ids = set()
        for person in people:
            if not isinstance(person,dict):
                raise ValueError('Person labels must be objects')
            identifier = person.get('person_id')
            if not isinstance(identifier, str) or not identifier.strip() or len(identifier) > 80 or identifier in ids:
                raise ValueError('Person IDs must be nonempty and unique within each frame')
            ids.add(identifier)
            Detection(tuple(person['box']), 1)
        if 'empty' in row['scenarios'] and people:
            raise ValueError('An empty frame cannot contain person boxes')
    return labels


def baseline(dataset, output, *, detector_kind='yolox-openvino', device='GPU', detector=None,
             labels=None, reviewed_only=False, warmup=0,zoom_regions=()):
    """Unlabelled model outputs are proposals/evidence, never ground truth."""
    from .engine import create_detector
    dataset, output = Path(dataset), Path(output)
    manifest = read_json(dataset / 'manifest.json')
    validate_splits(manifest['sequences'])
    if detector_kind in {'yolox','nanodet'} and device!='CPU':
        raise ValueError('The ONNX Runtime YOLOX/NanoDet adapter supports CPU only')
    if type(warmup) is not int or not 0 <= warmup <= 10:
        raise ValueError('Warmup must be 0..10 frames')
    selected = frame_index(manifest)
    if reviewed_only:
        labels = validate_labels(manifest,labels if labels is not None else read_json(dataset/'labels.json'))
        selected = {k:v for k,v in selected.items() if labels['frames'][k]['reviewed']}
    if not selected:
        raise ValueError('No frames selected for inference')
    if output.exists():
        raise FileExistsError('Never overwrite an existing baseline')
    detector = detector or create_detector(detector_kind, device)
    if zoom_regions:
        from .detector_zoom import ZoomExperiment
        detector=ZoomExperiment(detector,zoom_regions)
    result = {'version': 1, 'state': 'RUNNING', 'manifest_sha256': manifest_hash(manifest),
              'model': detector.manifest, 'model_sha256': detector.sha,
              'detector': detector_kind, 'device': device, 'frames': {}, 'accuracy_evaluated': False,
              'prediction_format_version':2,'selected_frames':list(selected),'warmup_frames':warmup,
              'selection':'reviewed_only' if reviewed_only else 'all_exported_frames',
              'label_snapshot_sha256':manifest_hash(labels) if labels is not None else None}
    write_json(output, result)
    timings = []
    try:
        first = next(iter(selected.values()))[1]
        first_image = dataset/first['image']
        if digest(first_image) != first['sha256']:
            raise ValueError('Evaluation frame checksum mismatch')
        started = time.perf_counter()
        for _ in range(warmup):
            detector.detect(first_image.read_bytes())
        result['warmup_total_ms'] = (time.perf_counter()-started)*1000
        for key, (_, frame) in selected.items():
            image = dataset / frame['image']
            if digest(image) != frame['sha256']:
                raise ValueError('Evaluation frame checksum mismatch')
            started = time.perf_counter()
            prediction = detector.detect(image.read_bytes())
            timings.append((time.perf_counter() - started) * 1000)
            if (prediction['width'], prediction['height']) != (frame['width'], frame['height']):
                raise ValueError('Detector and exported image dimensions differ')
            # Retain weak measured candidates for offline threshold sweeps. They
            # remain proposals and never change the live display/accounting policy.
            from .person_detection import detection_proposals
            candidates = detection_proposals(prediction)
            floor = detector.manifest.get('tracking_candidate_threshold',.45) if 'tracking_candidates' in prediction else detector.manifest.get('threshold',.45)
            result['frames'][key] = {'detections': prediction['detections'],'candidates':candidates,
                                     'candidate_floor':floor,'inference_ms': timings[-1]}
            if len(timings) % 25 == 0:
                write_json(output, result)
        result.update(state='COMPLETED', frames_processed=len(timings),
                      inference_ms_p50=statistics.median(timings),
                      inference_ms_p95=sorted(timings)[math.ceil(.95*len(timings))-1])
    except BaseException as error:
        result.update(state='FAILED', error_type=type(error).__name__)
        raise
    finally:
        write_json(output, result)
    return result


def prediction_rows(predictions, key, confidence):
    entry = predictions['frames'].get(key)
    if entry is None:
        return []
    floor = entry.get('candidate_floor',predictions.get('model',{}).get('threshold',.45))
    if confidence < floor:
        raise ValueError(f'Confidence {confidence} is below stored candidate floor {floor}')
    from .vision import Detection
    observed=[]
    for row in entry.get('candidates',entry.get('detections',[])):
        Detection(tuple(row['box']),row['confidence'])
        if row['confidence'] >= confidence:
            observed.append(row)
    return observed


def iou(a, b):
    intersection = max(0, min(a[2],b[2])-max(a[0],b[0])) * max(0, min(a[3],b[3])-max(a[1],b[1]))
    union = (a[2]-a[0])*(a[3]-a[1]) + (b[2]-b[0])*(b[3]-b[1]) - intersection
    return intersection / union if union else 0


def match_boxes(expected, observed, threshold):
    """Maximum cardinality, then maximum IoU. Avoid greedy matching false misses."""
    if not expected or not observed:
        return []
    import numpy as np
    from scipy.optimize import linear_sum_assignment
    overlaps = np.array([[iou(a['box'], b['box']) for b in observed] for a in expected])
    scores = np.where(overlaps >= threshold, min(len(expected),len(observed))+1+overlaps, 0)
    rows, cols = linear_sum_assignment(scores, maximize=True)
    return [(int(a),int(b)) for a,b in zip(rows,cols) if overlaps[a,b] >= threshold]


def evaluate_boxes(manifest, labels, predictions, *, confidence=.45, iou_threshold=.5, split='pilot'):
    validate_labels(manifest, labels)
    if split not in SPLITS or not all(type(v) in (float,int) and math.isfinite(v) and 0 < v <= 1 for v in (confidence,iou_threshold)):
        raise ValueError('Invalid split or thresholds')
    if predictions.get('manifest_sha256') != manifest_hash(manifest) or predictions.get('state') != 'COMPLETED':
        raise ValueError('A completed baseline for the same manifest is required')
    if set(predictions.get('frames', {})) - set(frame_index(manifest)):
        raise ValueError('Baseline includes unexpected frames')
    counts, per_frame = {}, []
    reviewed, eligible, sources, missing = 0, 0, {}, 0
    for key, (sequence, frame) in frame_index(manifest).items():
        if sequence['split'] != split:
            continue
        eligible += 1
        truth = labels['frames'][key]
        if not truth['reviewed']:
            continue  # An unreviewed [] is not an empty scene.
        reviewed += 1
        sources[truth['label_source']] = sources.get(truth['label_source'],0)+1
        entry = predictions['frames'].get(key)
        missing += entry is None
        observed = prediction_rows(predictions,key,confidence)
        matched = match_boxes(truth['persons'], observed, iou_threshold)
        row = {'key': key, 'tp': len(matched), 'fp': len(observed)-len(matched),
               'fn': len(truth['persons'])-len(matched)}
        per_frame.append(row)
        for group in ('overall', 'sequence:'+sequence['id'], *('scenario:'+s for s in truth['scenarios'])):
            counter = counts.setdefault(group, {'tp':0,'fp':0,'fn':0,'frames':0})
            for field in ('tp','fp','fn'):
                counter[field] += row[field]
            counter['frames'] += 1
    for row in counts.values():
        tp, fp, fn = row['tp'],row['fp'],row['fn']
        row.update(precision=tp/(tp+fp) if tp+fp else None, recall=tp/(tp+fn) if tp+fn else None,
                   f1=2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else None)
    return {'version':1,'state':'EVALUATED' if reviewed else 'AWAITING_LABELS',
            'basis':'person boxes on reviewed sampled frames; not AP, HOTA or IDF1',
            'split':split,'iou':iou_threshold,'confidence':confidence,'eligible_frames':eligible,
            'reviewed_frames':reviewed,'review_coverage':reviewed/eligible if eligible else None,
            'label_sources':sources,'missing_prediction_frames':missing,'metrics':counts,'per_frame':per_frame,
            'production_qualified':False,
            'limitations':['Sampled images do not validate continuous tracking, timing, or real RTSP.',
                'Independent complete annotations and held-out site/day recordings require review.',
                'Assistant and pseudo labels are never independent ground truth.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    export = sub.add_parser('prepare')
    export.add_argument('--video', action='append', required=True, type=Path)
    export.add_argument('--output', required=True, type=Path)
    export.add_argument('--group', required=True)
    export.add_argument('--split', choices=SPLITS, default='pilot')
    export.add_argument('--sample-fps', type=float, default=2)
    export.add_argument('--seconds', type=float)
    serve = sub.add_parser('annotate')
    serve.add_argument('--dataset', required=True, type=Path)
    serve.add_argument('--port', type=int, default=8773)
    infer = sub.add_parser('baseline')
    infer.add_argument('--dataset', required=True, type=Path)
    infer.add_argument('--output', required=True, type=Path)
    infer.add_argument('--detector', choices=['yolox','yolox-openvino','nanodet'], default='yolox-openvino')
    infer.add_argument('--device', choices=['CPU','GPU'], default='GPU')
    infer.add_argument('--labels',type=Path,help='Separate reviewed label snapshot')
    infer.add_argument('--reviewed-only',action='store_true')
    infer.add_argument('--warmup',type=int,default=0)
    infer.add_argument('--zoom-region',action='append',type=lambda value:tuple(map(float,value.split(','))),
                       help='Offline experiment only: normalized x0,y0,x1,y1; at most four regions')
    score = sub.add_parser('evaluate')
    score.add_argument('--dataset', required=True, type=Path)
    score.add_argument('--predictions', required=True, type=Path)
    score.add_argument('--labels',type=Path,help='Separate reviewed label snapshot')
    score.add_argument('--output', required=True, type=Path)
    score.add_argument('--split', choices=SPLITS, default='pilot')
    score.add_argument('--confidence', type=float, default=.45)
    score.add_argument('--iou', type=float, default=.5)
    args = parser.parse_args()
    if args.command == 'prepare':
        result = prepare(args.video,args.output,group=args.group,split=args.split,sample_fps=args.sample_fps,seconds=args.seconds)
        print(json.dumps({'sequences':len(result['sequences']),'frames':len(frame_index(result)),'output':str(args.output)}))
    elif args.command == 'annotate':
        from .dataset_server import serve_dataset
        serve_dataset(args.dataset,args.port)
    elif args.command == 'baseline':
        result = baseline(args.dataset,args.output,detector_kind=args.detector,device=args.device,
                          labels=read_json(args.labels) if args.labels else None,
                          reviewed_only=args.reviewed_only,warmup=args.warmup,zoom_regions=args.zoom_region or ())
        print(json.dumps({k:v for k,v in result.items() if k != 'frames'}))
    else:
        if args.output.exists():
            raise FileExistsError('Never overwrite an evaluation')
        result = evaluate_boxes(read_json(args.dataset/'manifest.json'),read_json(args.labels or args.dataset/'labels.json'),
                                read_json(args.predictions),split=args.split,confidence=args.confidence,iou_threshold=args.iou)
        write_json(args.output,result)
        print(json.dumps({k:v for k,v in result.items() if k != 'per_frame'}))


if __name__ == '__main__':
    main()
