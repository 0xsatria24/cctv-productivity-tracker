import pytest

from cctv_tracker.evaluation import evaluate_replay, match_boxes


def examples():
    labels={'schema_version':1,'reviewer':'synthetic metric test','frames':[
        {'time':t,'people':[{'box':[.1,.1,.3,.8],'person_id':'a'}],'zones':{'desk':'OCCUPIED'}} for t in (0,.2,.4)]}
    rows=[{'time':t,'detections':[{'box':[.1,.1,.3,.8],'session_id':'one'}],
           'workstations':[{'zone_id':'desk','occupied_us':round(t*1e6),'empty_us':0,'unknown_us':0}]} for t in (0,.2,.4)]
    return labels,rows


def test_quality_metrics_use_independent_boxes_ids_and_workstation_time():
    labels,rows=examples()
    report=evaluate_replay(labels,rows,minimum_seconds=.4)
    assert report['precision']==report['recall']==1
    assert report['labeled_clip_passed'] and not report['production_ready']
    assert report['workstations']['desk']['duration_error_ratio']==0
    assert not evaluate_replay(labels,rows)['labeled_clip_passed']


def test_false_merge_and_switch_and_missed_person_cannot_pass():
    labels,rows=examples()
    labels['frames'][1]['people'][0]['person_id']='b'
    labels['frames'][2]['people'][0]['person_id']='b'
    rows[2]['detections'][0]['session_id']='two'
    report=evaluate_replay(labels,rows,minimum_seconds=.4)
    assert report['sessions_with_multiple_labeled_people']==1
    assert report['session_id_switches']==1 and not report['labeled_clip_passed']
    rows[2]['detections']=[]
    assert evaluate_replay(labels,rows)['recall']==pytest.approx(2/3)


def test_unknown_time_reduces_coverage_and_is_not_treated_as_accurate_occupancy():
    labels,rows=examples()
    for row in rows:
        row['workstations'][0]['unknown_us']=row['workstations'][0]['occupied_us']
        row['workstations'][0]['occupied_us']=0
    report=evaluate_replay(labels,rows,minimum_seconds=.4)
    assert report['workstations']['desk']['coverage']==0
    assert report['workstations']['desk']['duration_error_ratio']==1
    assert not report['labeled_clip_passed']


def test_matching_is_one_to_one_and_uses_maximum_cardinality():
    a={'box':[0,0,.6,1]};b={'box':[.4,0,1,1]}
    assert len(match_boxes([a,b],[{'box':[.2,0,.8,1]},a],.4))==2
    assert len(match_boxes([a,a],[a]))==1


@pytest.mark.parametrize('kind',['missing','reset','time','unreviewed','box','zone'])
def test_invalid_evaluation_fails_closed(kind):
    labels,rows=examples()
    if kind=='missing':labels['frames'].pop()
    if kind=='reset':rows[2]['workstations'][0]['occupied_us']=0
    if kind=='time':rows[1]['time']=9
    if kind=='unreviewed':labels['reviewer']=''
    if kind=='box':labels['frames'][0]['people'][0]['box']=[0,0,2,2]
    if kind=='zone':labels['frames'][0]['zones']={}
    with pytest.raises(ValueError):evaluate_replay(labels,rows)
