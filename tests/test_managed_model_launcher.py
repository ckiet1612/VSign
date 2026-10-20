import os
import subprocess
from pathlib import Path


def test_managed_launcher_pins_worker_and_never_targets_experimental_runtime(tmp_path):
    project=tmp_path/'project with spaces'
    scripts=project/'scripts'
    scripts.mkdir(parents=True)
    (scripts/'run_managed_coreml_local.sh').write_text(Path('scripts/run_managed_coreml_local.sh').read_text())
    (scripts/'run_coreml_local.sh').write_text('#!/bin/sh\nprintf "%s|%s|%s|%s|%s" "$MODEL_DEPLOYMENT_WORKER" "$INFERENCE_PORT" "$MODEL_DEPLOYMENT_TARGET" "$DATABASE_URL" "$MODEL_DEPLOYMENT_RUNTIME_URL"\n')
    env={**os.environ,'MODEL_DEPLOYMENT_WORKER':'false'}
    for key in ('INFERENCE_PORT','MODEL_DEPLOYMENT_TARGET','DATABASE_URL','MODEL_DEPLOYMENT_RUNTIME_URL'):
        env.pop(key,None)
    result=subprocess.run(['bash',str(scripts/'run_managed_coreml_local.sh')],env=env,capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    assert result.stdout==f'true|8002|production-local|sqlite:///{project}/data/vsign-platform.db|http://127.0.0.1:8002'
    result=subprocess.run(['bash',str(scripts/'run_managed_coreml_local.sh')],env={**env,'INFERENCE_PORT':'8003'},capture_output=True,text=True)
    assert result.returncode!=0
    assert not result.stdout
