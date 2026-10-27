"""Offline metrics against independent, complete labels on the sampled frames."""
import math

from .occupancy_evaluation import evaluate, main, replay_video, validate_annotations


def iou(a, b):
    intersection = max(0, min(a[2],b[2])-max(a[0],b[0])) * max(0, min(a[3],b[3])-max(a[1],b[1]))
    union = (a[2]-a[0])*(a[3]-a[1]) + (b[2]-b[0])*(b[3]-b[1]) - intersection
    return intersection/union if union > 0 else 0


def match_boxes(truth, predicted, threshold=.5):
    candidates = [sorted((j for j,p in enumerate(predicted) if iou(t['box'],p['box'])>=threshold),
                         key=lambda j:iou(t['box'],predicted[j]['box']), reverse=True) for t in truth]
    owners = {}

    def assign(index, visited):
        for j in candidates[index]:
            if j in visited:
                continue
            visited.add(j)
            if j not in owners or assign(owners[j],visited):
                owners[j]=index
                return True
        return False

    for index in range(len(truth)):
        assign(index,set())
    return [(i,j) for j,i in owners.items()]


def _box_valid(box):
    return (isinstance(box,(list,tuple)) and len(box)==4
            and all(type(v) in (int,float) and math.isfinite(v) and 0<=v<=1 for v in box)
            and box[0]<box[2] and box[1]<box[3])


def evaluate_replay(labels, rows, *, minimum_seconds=1800):
    frames=labels.get('frames',[])
    if labels.get('schema_version')!=1 or not isinstance(labels.get('reviewer'),str) or not labels['reviewer'].strip() or not frames:
        raise ValueError('Independent labels require schema_version=1, reviewer, and nonempty frames')
    if len(frames)!=len(rows):
        raise ValueError('Labels must cover every result frame in the evaluation window')
    tp=fp=fn=switches=assigned=0
    owners, last_ids, durations, prior = {}, {}, {}, None
    first_time=None
    for truth,predicted in zip(frames,rows):
        at=truth.get('time')
        if type(at) not in (int,float) or not math.isfinite(at) or at<0 or abs(at-predicted['time'])>1e-6 or (prior and at<=prior[0]):
            raise ValueError('Label/result media times must match and advance')
        if first_time is None:
            first_time=at
        people=truth.get('people')
        measured=predicted.get('detections',[])
        if not isinstance(people,list) or len(people)>100 or len(measured)>100:
            raise ValueError('Every labeled frame requires a bounded, complete people list')
        if any(not _box_valid(p.get('box')) or not isinstance(p.get('person_id'),str) or not p['person_id'] for p in people):
            raise ValueError('Every person label requires a normalized box and independent person_id')
        if len({p['person_id'] for p in people})!=len(people) or any(not _box_valid(p.get('box')) for p in measured):
            raise ValueError('Duplicate identities or invalid predicted boxes')
        matched=match_boxes(people,measured)
        tp+=len(matched);fp+=len(measured)-len(matched);fn+=len(people)-len(matched)
        for i,j in matched:
            identity,sid=people[i]['person_id'],measured[j].get('session_id')
            if not sid:
                continue
            assigned+=1
            owners.setdefault(sid,set()).add(identity)
            if identity in last_ids and last_ids[identity]!=sid:
                switches+=1
            last_ids[identity]=sid
        zones=truth.get('zones',{})
        clocks={z['zone_id']:z for z in predicted.get('workstations',[])}
        if not zones or set(zones)!=set(clocks) or any(s not in ('OCCUPIED','EMPTY','UNKNOWN') for s in zones.values()):
            raise ValueError('Each frame must label every calibrated workstation state')
        if any(type(z.get(name)) is not int or z[name]<0 for z in clocks.values() for name in ('occupied_us','empty_us','unknown_us')):
            raise ValueError('Workstation totals must be nonnegative integer microseconds')
        if prior:
            elapsed=round((at-prior[0])*1e6)
            for zone,state in zones.items():
                metric=durations.setdefault(zone,{'reference_occupied_us':0,'predicted_occupied_us':0,
                                                   'absolute_interval_error_us':0,'known_reference_us':0,'unknown_prediction_us':0})
                if set(zones)!=set(prior[1]) or set(clocks)!=set(prior[2]):
                    raise ValueError('Calibration changed during evaluation')
                for name in ('occupied_us','empty_us','unknown_us'):
                    value=clocks[zone].get(name)
                    if type(value) is not int or value<prior[2][zone][name]:
                        raise ValueError('Workstation totals reset or are invalid during evaluation')
                accounted=sum(clocks[zone][key]-prior[2][zone][key] for key in ('occupied_us','empty_us','unknown_us'))
                if abs(accounted-elapsed)>2:
                    raise ValueError('Workstation totals do not partition elapsed media time')
                if elapsed<=1_000_000 and state==prior[1][zone] and state!='UNKNOWN':
                    reference=elapsed if state=='OCCUPIED' else 0
                    estimate=clocks[zone]['occupied_us']-prior[2][zone]['occupied_us']
                    unknown=clocks[zone]['unknown_us']-prior[2][zone]['unknown_us']
                    metric['reference_occupied_us']+=reference
                    metric['predicted_occupied_us']+=estimate
                    metric['known_reference_us']+=elapsed
                    metric['unknown_prediction_us']+=unknown
                    metric['absolute_interval_error_us']+=abs(estimate-reference)
        prior=(at,zones,clocks)
    precision=tp/(tp+fp) if tp+fp else None
    recall=tp/(tp+fn) if tp+fn else None
    false_merges=sum(len(ids)>1 for ids in owners.values())
    identity_coverage=assigned/tp if tp else None
    for metric in durations.values():
        known=metric['known_reference_us']
        metric['duration_error_ratio']=metric['absolute_interval_error_us']/known if known else None
        metric['coverage']=1-metric['unknown_prediction_us']/known if known else None
    evaluated_seconds=frames[-1]['time']-first_time
    gates={'minimum_labeled_duration':evaluated_seconds>=minimum_seconds,
           'precision_at_least_90_percent':precision is not None and precision>=.9,
           'recall_at_least_90_percent':recall is not None and recall>=.9,
           'no_observed_false_merges':false_merges==0 and bool(owners),
           'identity_assignment_coverage_at_least_95_percent':identity_coverage is not None and identity_coverage>=.95,
           'zone_duration_error_at_most_5_percent':bool(durations) and all(m['duration_error_ratio'] is not None and m['duration_error_ratio']<=.05 for m in durations.values()),
           'zone_coverage_at_least_95_percent':bool(durations) and all(m['coverage'] is not None and m['coverage']>=.95 for m in durations.values())}
    return {'basis':'independent_frame_labels','reviewer':labels['reviewer'], 'frames':len(frames),
            'evaluated_seconds':evaluated_seconds,'iou_threshold':.5,'true_positive':tp,'false_positive':fp,
            'false_negative':fn,'precision':precision,'recall':recall,'session_id_switches':switches,
            'identity_assignment_coverage':identity_coverage,
            'sessions_with_multiple_labeled_people':false_merges,'workstations':durations,
            'proposed_acceptance_gates':gates,'labeled_clip_passed':all(gates.values()),'production_ready':False}


if __name__ == '__main__':
    main()
