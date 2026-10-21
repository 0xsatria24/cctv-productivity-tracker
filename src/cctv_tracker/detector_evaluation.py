"""Paired detector comparison and diagnostic review, without live policy changes."""
import argparse
import base64
import csv
import io
from importlib.resources import files
import json
import math
from pathlib import Path

from .dataset import (digest,evaluate_boxes,frame_index,iou,manifest_hash,match_boxes,
                      prediction_rows,read_json,validate_labels,write_json)
from .secure_store import atomic_write


def errors_for_frames(manifest,labels,predictions,confidence,iou_threshold,split):
    rows=[]
    for key,(sequence,frame) in frame_index(manifest).items():
        truth=labels['frames'][key]
        if sequence['split'] != split or not truth['reviewed']:
            continue
        expected=truth['persons']
        observed=prediction_rows(predictions,key,confidence)
        pairs=match_boxes(expected,observed,iou_threshold)
        matched_gt={a for a,b in pairs};matched_pred={b for a,b in pairs}
        rows.append({'key':key,'tp':len(pairs),'fn':len(expected)-len(pairs),'fp':len(observed)-len(pairs),
                     'missed_gt':[i for i in range(len(expected)) if i not in matched_gt],
                     'false_positive_predictions':[i for i in range(len(observed)) if i not in matched_pred],
                     'detections':observed,'matched_ious':[iou(expected[a]['box'],observed[b]['box']) for a,b in pairs],
                     'person_sizes':[{'bin':'under_one_third_frame_height' if p['box'][3]-p['box'][1]<1/3 else 'at_least_one_third_frame_height',
                                      'detected':i in matched_gt} for i,p in enumerate(expected)]})
    return rows


def threshold_proposal(manifest,labels,variants,split):
    """A proposal needs complete human validation data and a separate test group.

    Even an eligible proposal is never applied to the application automatically.
    Numeric sample minima are operational guards, not statistical certification.
    """
    reasons=[]
    rows=[labels['frames'][f['key']] for s in manifest['sequences'] if s['split']==split for f in s['frames']]
    if split != 'validation':
        reasons.append('THRESHOLD_SELECTION_REQUIRES_VALIDATION_SPLIT')
    if not rows or any(not r['reviewed'] or r['label_source']!='human' for r in rows):
        reasons.append('COMPLETE_HUMAN_REVIEW_REQUIRED')
    if len(rows)<20 or sum(len(r['persons']) for r in rows)<50 or not any(r['reviewed'] and not r['persons'] for r in rows):
        reasons.append('MORE_PERSON_AND_EMPTY_FRAME_SUPPORT_REQUIRED')
    groups={s['group'] for s in manifest['sequences'] if s['split']==split}
    test_groups={s['group'] for s in manifest['sequences'] if s['split']=='test' and s['frames']}
    if not test_groups or groups & test_groups:
        reasons.append('DISTINCT_HELD_OUT_TEST_GROUP_REQUIRED')
    if reasons:
        return {'state':'NOT_ELIGIBLE','reasons':reasons,'configuration':None,'applied':False}
    candidates=[]
    for model in variants:
        for variant in model['variants']:
            metric=variant.get('evaluation',{}).get('metrics',{}).get('overall',{})
            if (metric.get('precision') or 0)>=.9 and (metric.get('recall') or 0)>=.9:
                candidates.append((metric['f1'],variant['confidence'],model['name']))
    if not candidates:
        return {'state':'NO_THRESHOLD_MEETS_TARGET','reasons':['PRECISION_AND_RECALL_TARGET_0.9'],
                'configuration':None,'applied':False}
    f1,confidence,model=max(candidates)
    return {'state':'PROPOSAL_REQUIRES_HELD_OUT_ACCEPTANCE','configuration':{'model_name':model,'confidence':confidence},
            'validation_f1':f1,'applied':False,'production_qualified':False}


def compare(manifest,labels,caches,*,thresholds=(.25,.35,.45,.55,.65),iou_threshold=.5,split='pilot'):
    validate_labels(manifest,labels)
    if split not in {'pilot','validation','test'} or type(iou_threshold) not in (int,float) or not math.isfinite(iou_threshold) or not 0<iou_threshold<=1:
        raise ValueError('Invalid evaluation split or IoU threshold')
    thresholds=sorted(set(thresholds))
    if not thresholds or any(type(v) not in (int,float) or not math.isfinite(v) or not 0<v<=1 for v in thresholds):
        raise ValueError('Thresholds must be finite within (0,1]')
    if split=='test' and len(thresholds)!=1:
        raise ValueError('Held-out test requires one frozen threshold; tune only on validation')
    reviewed={k for k,(s,f) in frame_index(manifest).items() if s['split']==split and labels['frames'][k]['reviewed']}
    if not caches:
        raise ValueError('Supply at least one measured detector cache')
    models=[]
    for name,predictions in caches.items():
        if not name.strip() or len(name)>120:
            raise ValueError('Invalid model comparison name')
        if predictions.get('state')!='COMPLETED' or predictions.get('manifest_sha256')!=manifest_hash(manifest):
            raise ValueError('Use completed caches from the same immutable dataset')
        if reviewed-set(predictions.get('frames',{})):
            raise ValueError('Paired comparison requires predictions for every reviewed frame')
        floors=[predictions['frames'][k].get('candidate_floor',predictions.get('model',{}).get('threshold',.45)) for k in reviewed]
        if any(type(floor) not in (int,float) or not math.isfinite(floor) or not 0<floor<=1 for floor in floors):
            raise ValueError('Invalid stored candidate floor')
        floor=max(floors,default=.45)
        variants=[]
        for confidence in thresholds:
            variant={'confidence':confidence}
            if confidence<floor:
                variant.update(state='UNAVAILABLE_BELOW_CACHE_FLOOR',candidate_floor=floor)
            else:
                result=evaluate_boxes(manifest,labels,predictions,confidence=confidence,iou_threshold=iou_threshold,split=split)
                error_rows=errors_for_frames(manifest,labels,predictions,confidence,iou_threshold,split)
                overlaps=[v for r in error_rows for v in r['matched_ious']]
                size_recall={}
                for row in error_rows:
                    for person in row['person_sizes']:
                        size=size_recall.setdefault(person['bin'],{'persons':0,'detected':0})
                        size['persons']+=1;size['detected']+=person['detected']
                for size in size_recall.values():
                    size['recall']=size['detected']/size['persons']
                variant.update(state=result['state'],evaluation=result,errors=error_rows,
                               matched_mean_iou=sum(overlaps)/len(overlaps) if overlaps else None,
                               object_height_recall=size_recall)
            variants.append(variant)
        # Paired image-call timings exclude the stored warmup calls. No camera
        # FPS, model-quality difference or load-isolation claim follows from this.
        timings=sorted(predictions['frames'][k]['inference_ms'] for k in reviewed if predictions['frames'][k].get('inference_ms') is not None)
        if any(type(t) not in (int,float) or not math.isfinite(t) or t<0 for t in timings):
            raise ValueError('Invalid measured latency')
        latency={'samples':len(timings),'p50':(timings[(len(timings)-1)//2]+timings[len(timings)//2])/2 if timings else None,
                 'p95':timings[math.ceil(.95*len(timings))-1] if timings else None}
        models.append({'name':name,'model':predictions.get('model',{}),'model_sha256':predictions.get('model_sha256'),
                       'candidate_floor':floor,'warmup_frames':predictions.get('warmup_frames',0),
                       'image_call_ms':latency,'variants':variants})
    sources={}
    for key in reviewed:
        source=labels['frames'][key]['label_source'];sources[source]=sources.get(source,0)+1
    return {'version':1,'state':'PILOT_DIAGNOSTIC' if reviewed else 'AWAITING_LABELS',
            'manifest_sha256':manifest_hash(manifest),'label_snapshot_sha256':manifest_hash(labels),
            'split':split,'iou':iou_threshold,'reviewed_frames':len(reviewed),'label_sources':sources,
            'models':models,'threshold_proposal':threshold_proposal(manifest,labels,models,split),
            'production_qualified':False,'live_configuration_changed':False,
            'limitations':['Assistant/pseudo labels are diagnostic references, not independent human ground truth.',
               'All models use the same reviewed images. Sparse selected frames do not validate tracking.',
               'Precision/recall/F1 at one IoU is not AP, HOTA, IDF1 or commercial accuracy.',
               'Image-call timings are offline measurements; hardware load and different runtimes confound speed comparisons.',
               'A same-weight runtime comparison is not a comparison between different model architectures.',
               'Confidence sweeps below a stored candidate floor are unavailable, not zero recall.']}


def write_report(dataset,labels,caches,output,*,thresholds=(.25,.35,.45,.55,.65),iou_threshold=.5,split='pilot'):
    dataset,output=Path(dataset),Path(output)
    manifest=read_json(dataset/'manifest.json')
    report=compare(manifest,labels,caches,thresholds=thresholds,iou_threshold=iou_threshold,split=split)
    reviewed={k for k,r in labels['frames'].items() if r['reviewed']}
    frames=[]
    for key,(sequence,frame) in frame_index(manifest).items():
        if key not in reviewed or sequence['split']!=split:
            continue
        image=dataset/frame['image']
        if digest(image)!=frame['sha256']:
            raise ValueError('Review frame checksum mismatch')
        frames.append({**frame,'source_name':sequence['source_name'],'truth':labels['frames'][key],
                       'image_data':'data:image/jpeg;base64,'+base64.b64encode(image.read_bytes()).decode()})
    # Output is private and self-contained. It does not expose a source path or
    # publish frames. Never replace a previous comparison or the user's labels.
    output.mkdir(parents=True,exist_ok=False)
    write_json(output/'comparison.json',report)
    write_json(output/'labels-snapshot.json',labels)
    csv_file=io.StringIO(newline='');writer=csv.writer(csv_file)
    writer.writerow(['model','confidence','state','frames','tp','fp','fn','precision','recall','f1','matched_mean_iou','paired_call_p50_ms','paired_call_p95_ms'])
    for model in report['models']:
        for variant in model['variants']:
            metric=variant.get('evaluation',{}).get('metrics',{}).get('overall',{})
            writer.writerow([model['name'],variant['confidence'],variant['state'],report['reviewed_frames'],
                             *[metric.get(k) for k in ('tp','fp','fn','precision','recall','f1')],
                             variant.get('matched_mean_iou'),model['image_call_ms']['p50'],model['image_call_ms']['p95']])
    atomic_write(output/'summary.csv',csv_file.getvalue().encode('utf-8-sig'))
    template=files('cctv_tracker').joinpath('resources/detector-report.html').read_text(encoding='utf-8')
    payload=json.dumps({'report':report,'frames':frames},ensure_ascii=True,allow_nan=False).replace('<','\\u003c')
    atomic_write(output/'review.html',template.replace('__REPORT_JSON__',payload).encode('utf-8'))
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset',required=True,type=Path)
    parser.add_argument('--labels',type=Path)
    parser.add_argument('--prediction',required=True,action='append',metavar='NAME=PATH')
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--threshold',type=float,action='append')
    parser.add_argument('--iou',type=float,default=.5)
    parser.add_argument('--split',choices=['pilot','validation','test'],default='pilot')
    args=parser.parse_args()
    caches={}
    for specification in args.prediction:
        name,separator,path=specification.partition('=')
        if not separator or name in caches:
            parser.error('Use unique NAME=PATH prediction arguments')
        caches[name]=read_json(path)
    result=write_report(args.dataset,read_json(args.labels or args.dataset/'labels.json'),caches,args.output,
                        thresholds=args.threshold or (.25,.35,.45,.55,.65),iou_threshold=args.iou,split=args.split)
    print(json.dumps({k:v for k,v in result.items() if k!='models'}))


if __name__=='__main__':
    main()
