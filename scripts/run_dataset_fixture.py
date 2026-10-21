"""Temporary synthetic browser-test dataset, never uses user videos or labels."""
from pathlib import Path
from tempfile import TemporaryDirectory


def main():
    import argparse
    import cv2
    import numpy as np
    from cctv_tracker.dataset import digest,manifest_hash,write_json
    from cctv_tracker.dataset_server import serve_dataset
    parser=argparse.ArgumentParser()
    parser.add_argument('--mode',choices=['annotate','report'],default='annotate')
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]/'runtime'
    root.mkdir(exist_ok=True)
    with TemporaryDirectory(prefix='dataset-browser-',dir=root) as temporary:
        dataset=Path(temporary);directory=dataset/'frames'/'synthetic';directory.mkdir(parents=True)
        frames=[]
        for i in (1,2):
            image=np.zeros((480,640,3),np.uint8)
            cv2.putText(image,'SYNTHETIC ANNOTATION TEST',(30,40),cv2.FONT_HERSHEY_SIMPLEX,.7,(200,200,200),1)
            cv2.rectangle(image,(180,100),(350,420),(75,120,110),-1)
            path=directory/f'{i}.jpg';cv2.imwrite(str(path),image)
            frames.append({'key':f'synthetic:{i}','number':i,'seconds':i/2,'width':640,'height':480,
                           'image':f'frames/synthetic/{i}.jpg','sha256':digest(path)})
        manifest={'version':1,'sequences':[{'id':'synthetic','source_name':'SYNTHETIC fixture',
                   'group':'synthetic','split':'pilot','sha256':'f'*64,'frames':frames}]}
        labels={'version':1,'revision':0,'manifest_sha256':manifest_hash(manifest),
                'frames':{f['key']:{'reviewed':False,'reviewer':'','label_source':'human',
                         'scenarios':[],'persons':[],'comment':''} for f in frames}}
        write_json(dataset/'manifest.json',manifest);write_json(dataset/'labels.json',labels)
        if args.mode=='annotate':
            serve_dataset(dataset,8782)
        else:
            from cctv_tracker.detector_evaluation import write_report
            from cctv_tracker.detector_report_server import serve_report
            for row in labels['frames'].values():
                row.update(reviewed=True,reviewer='SYNTHETIC TEST',scenarios=['normal'],label_source='assistant',
                           persons=[{'person_id':'p1','box':[.28,.2,.55,.88]}])
            predictions={'state':'COMPLETED','manifest_sha256':manifest_hash(manifest),'frames':{}}
            alternative={'state':'COMPLETED','manifest_sha256':manifest_hash(manifest),'frames':{}}
            for i,frame in enumerate(frames):
                predictions['frames'][frame['key']]={'detections':[] if i else [{'box':[.28,.2,.55,.88],'confidence':.9}],'inference_ms':20}
                alternative['frames'][frame['key']]={'detections':[{'box':[.7,.1,.95,.8],'confidence':.8}],'inference_ms':10}
            write_report(dataset,labels,{'Reference fixture':predictions,'Fast fixture':alternative},dataset/'report',thresholds=[.25,.45])
            serve_report(dataset/'report',8783)


if __name__=='__main__':
    main()
