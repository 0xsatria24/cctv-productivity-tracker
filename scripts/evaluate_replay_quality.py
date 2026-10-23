"""Score replay results against independently reviewed workstation/person labels."""
import argparse
import json
from pathlib import Path

from cctv_tracker.evaluation import evaluate_replay


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--labels',type=Path,required=True)
    parser.add_argument('--results',type=Path,required=True)
    parser.add_argument('--profile',default='balanced')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    labels=json.loads(args.labels.read_text(encoding='utf-8'))
    result=json.loads(args.results.read_text(encoding='utf-8'))[args.profile]
    report=evaluate_replay(labels,result['rows'])
    report['candidate']={k:v for k,v in result.items() if k!='rows'}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in ('candidate','workstations')},indent=2))
    return 0 if report['labeled_clip_passed'] else 1


if __name__=='__main__':
    raise SystemExit(main())
