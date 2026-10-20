"""Disposable native ONNX/video fixture. Never reads or mutates production artifacts."""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import onnx
from onnx import TensorProto as T, helper as h
from PIL import Image
from argon2 import PasswordHasher
from fastapi.testclient import TestClient

from app.config import Settings
from app.model_manifest import labels_digest
from app.model_registry_db import RegisteredModel, DeploymentTarget
from app.platform_auth import bootstrap_platform, local_admin_id
from app.platform_db import create_database
from app.workspace_data import canonical


def prepare(root, origin, port):
    root.mkdir(exist_ok=True)
    registry, evidence = root/'registry',root/'evidence'
    registry.mkdir()
    evidence.mkdir()
    labels = ['Hello','Không ký hiệu']
    labels_file = registry/'labels.json'
    labels_file.write_bytes(canonical(labels))
    identities, manifests = {},{}
    for name in ('baseline','candidate'):
        nodes, input_name = [],'clip'
        if name == 'baseline':
            # Extra real tensor work makes this deliberately simple baseline slower.
            for index in range(4):
                output = f'sin{index}'
                nodes.append(h.make_node('Sin',[input_name],[output]))
                input_name = output
        nodes.extend([h.make_node('ReduceMean',[input_name],['mean'],axes=[1,2,3,4],keepdims=0),
            h.make_node('Unsqueeze',['mean'],['column'],axes=[1]),
            h.make_node('Constant',[],['scale'],value=h.make_tensor('scale',T.FLOAT,[1],[20.])),
            h.make_node('Mul',['column','scale'],['positive']),h.make_node('Neg',['positive'],['negative']),
            h.make_node('Concat',['positive','negative'],['logits'],axis=1)])
        graph = h.make_graph(nodes,name,[h.make_tensor_value_info('clip',T.FLOAT,[1,3,16,224,224])],
            [h.make_tensor_value_info('logits',T.FLOAT,[1,2])])
        model = h.make_model(graph,opset_imports=[h.make_opsetid('',11)],producer_name='isolated-evaluations')
        model.ir_version=8
        onnx.checker.check_model(model)
        artifact = registry/f'{name}.onnx'
        onnx.save(model,artifact)
        manifest = dict(model_version=f'evaluation-{name}',artifact_sha256=hashlib.sha256(artifact.read_bytes()).hexdigest(),
            labels_sha256=labels_digest(labels),backend='onnx',protocol_version='1.0',frame_count=16,frame_size=224,
            preprocessing_version='rgb16-224-imagenet-v1',confidence_threshold=.7,margin_threshold=.15,
            source_run_id=f'fixture-{name}',status='production' if name == 'baseline' else 'candidate')
        identities[name],manifests[name]=str(uuid4()),manifest
    settings=Settings.from_env()
    settings=replace(settings,inference_backend='onnx',model_version='evaluation-baseline',model_manifest_path=None,
        onnx_model_path=registry/'baseline.onnx',label_map_path=labels_file,labels_verified=True,
        model_registry_roots=(registry,),model_evaluation_roots=(evidence,),collection_dir=root/'media',
        collection_enabled=True,collection_labels=tuple(labels),model_deployment_worker=True,
        model_deployment_runtime_url=f'http://127.0.0.1:{port}',allowed_origins=(origin,))
    db=create_database(settings.database_url)
    db.create_schema()
    bootstrap_platform(db,settings,PasswordHasher())
    with db.session() as session:
        for name in identities:
            session.add(RegisteredModel(id=identities[name],workspace_id=settings.workspace_id,
                model_version=manifests[name]['model_version'],artifact_path=str(registry/f'{name}.onnx'),labels_path=str(labels_file),
                labels_count=2,manifest_json=manifests[name],origin=name if name == 'baseline' else 'candidate'))
        session.flush()
        session.add(DeploymentTarget(workspace_id=settings.workspace_id,target_id=settings.model_deployment_target,
            runtime_url=settings.model_deployment_runtime_url,backend='onnx',active_model_id=identities['baseline'],revision=0))
        session.commit()
    from app.main import create_app
    with TestClient(create_app(replace(settings,inference_backend='mock',model_deployment_worker=False))) as client:
        data='/api/v1/workspace/data'
        lv,dataset,collection,snapshot=[str(uuid4()) for _ in range(4)]
        def post(path,body):
            response=client.post(data+path,json=body)
            assert response.status_code in (200,201),response.text
            return response.json()
        post('/labels',dict(request_id=lv,name='Kiểm thử tích hợp',entries=[dict(id=str(uuid4()),name=name,
            kind='sign' if name == 'Hello' else 'negative') for name in labels]))
        post('/datasets',dict(request_id=dataset,name='Video trắng và đen',label_version_id=lv))
        post('/sessions',dict(request_id=collection,dataset_version_id=dataset))
        for name,color in zip(labels,('white','black')):
            with Image.new('RGB',(224,224),color) as image:
                stream=io.BytesIO()
                image.save(stream,format='JPEG')
                url='data:image/jpeg;base64,'+base64.b64encode(stream.getvalue()).decode()
            post(f'/sessions/{collection}/samples',dict(session_id=str(uuid4()),sample_key=str(uuid4()),batch='personal-100',
                captured_at=1788980000000,duration_ms=2100,expected_label=name,hand='right',frames=[url]*28))
        post(f'/sessions/{collection}/state',dict(state='stopped'))
        overview=post(f'/datasets/{dataset}/snapshot',dict(request_id=snapshot))
        manifest=client.get(data+f'/snapshots/{snapshot}/manifest').json()
    config=dict(candidate_id=identities['candidate'],baseline_id=identities['baseline'],snapshot_id=snapshot,
        workspace_id=settings.workspace_id,sha256=overview['snapshots'][0]['sha256'],manifests=manifests,
        video_hashes=[sample['video_sha256'] for sample in manifest['samples']],limits='Synthetic classifier and generated MP4s, not real sign quality.')
    (root/'fixture.json').write_bytes(canonical(config))
    db.dispose()
    return settings


def proof(root):
    config=json.loads((root/'fixture.json').read_bytes())
    document=dict(schema_version='1',workspace_id=config['workspace_id'],snapshot_sha256=config['sha256'],
        complete_training_lineage=True,evaluation_groups={digest:'unseen-fixture-session' for digest in config['video_hashes']},
        models={m['artifact_sha256']:dict(source_run_id=m['source_run_id'],training_video_sha256=['f'*64],
            training_group_ids=['training-fixture-session']) for m in config['manifests'].values()})
    (root/'evidence'/f'provenance-{config["sha256"]}.json').write_bytes(canonical(document))


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--port',type=int,default=0)
    parser.add_argument('--origin',default='')
    parser.add_argument('--proof',action='store_true')
    args=parser.parse_args()
    root=args.output.resolve()
    if root.is_relative_to(Path(__file__).resolve().parents[2]):
        parser.error('Output must be outside the repository')
    if args.proof:
        proof(root)
        return
    if args.port in (0,8000,8002,8003,5174): parser.error('Use a disposable port')
    settings=prepare(root,args.origin,args.port)
    from app.main import create_app
    import uvicorn
    uvicorn.run(create_app(settings),host='127.0.0.1',port=args.port)


if __name__ == '__main__': main()
