"""Run separately from inference: python -m app.evaluation_worker --backend onnx."""
from __future__ import annotations

import argparse
import importlib.util
import logging
import multiprocessing
import signal
import time
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy import select

from app.config import Settings
from app.evaluation_db import EvaluationRun, EvaluationWorkerState
from app.evaluations import alive, evaluation_audit, recover_expired
from app.platform_db import create_database, utc_now
from app.workspace_data import WorkspaceData

logger = logging.getLogger('vsign.evaluation.worker')


def scope(settings):
    return SimpleNamespace(workspace=SimpleNamespace(id=settings.workspace_id))


def claim_run(database, settings, backend, worker_id):
    with WorkspaceData(database,settings).write(scope(settings)) as session:
        recover_expired(session, settings.workspace_id)
        state = session.get(EvaluationWorkerState,(settings.workspace_id,backend))
        if state and state.worker_id != worker_id and alive(state.heartbeat_at):
            return None
        if state is None:
            state = EvaluationWorkerState(workspace_id=settings.workspace_id,backend=backend,worker_id=worker_id,
                                           heartbeat_at=utc_now())
            session.add(state)
        else:
            state.worker_id, state.heartbeat_at = worker_id,utc_now()
        runs = session.scalars(select(EvaluationRun).where(EvaluationRun.workspace_id == settings.workspace_id,
            EvaluationRun.status.in_(['queued','running'])).order_by(EvaluationRun.created_at,EvaluationRun.id)).all()
        if any(run.status == 'running' for run in runs):
            return None
        run = next((run for run in runs if run.frozen_json['candidate']['backend'] == backend),None)
        if run is None:
            return None
        run.status, run.worker_id, run.heartbeat_at, run.started_at = 'running',worker_id,utc_now(),utc_now()
        evaluation_audit(session,run,'started')
        return run.id


def heartbeat(database, settings, backend, worker_id, run_id):
    with WorkspaceData(database,settings).write(scope(settings)) as session:
        state = session.get(EvaluationWorkerState,(settings.workspace_id,backend))
        if not state or state.worker_id != worker_id:
            return False
        run = session.get(EvaluationRun,run_id)
        if not run or run.workspace_id != settings.workspace_id or run.worker_id != worker_id or run.status != 'running':
            return False
        if not alive(state.heartbeat_at) or not alive(run.heartbeat_at):
            run.status,run.error,run.finished_at='failed','Worker bị gián đoạn; hãy tạo lượt đánh giá mới.',utc_now()
            evaluation_audit(session,run,'failed',outcome='failure')
            return False
        state.heartbeat_at = utc_now()
        run.heartbeat_at = utc_now()
        return True


def finish_failure(database, settings, run_id, worker_id, error):
    with WorkspaceData(database,settings).write(scope(settings)) as session:
        run = session.get(EvaluationRun,run_id)
        if not run or run.workspace_id != settings.workspace_id or run.worker_id != worker_id or run.status != 'running':
            return False
        run.status, run.error, run.finished_at = 'failed',error,utc_now()
        evaluation_audit(session,run,'failed',outcome='failure')
        return True


def child(settings, run_id, worker_id):
    database = create_database(settings.database_url)
    try:
        from app.evaluation_engine import execute_run
        execute_run(database,settings,run_id,worker_id)
    except Exception as exc:
        logger.error('Evaluation failed (%s)',type(exc).__name__)
        finish_failure(database,settings,run_id,worker_id,'Không thể hoàn tất đánh giá; kiểm tra worker và dữ liệu đầu vào.')
    finally:
        database.dispose()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--backend',required=True,choices=['onnx','coreml','pytorch'])
    args = parser.parse_args()
    module = {'onnx':'onnxruntime','coreml':'coremltools','pytorch':'torch'}[args.backend]
    if importlib.util.find_spec(module) is None:
        parser.error(f'Worker interpreter has no {module}')
    settings = Settings.from_env()
    if settings.database_url == 'sqlite:///:memory:':
        parser.error('Worker requires a persistent database')
    database = create_database(settings.database_url)
    database.ensure_schema(False)
    worker_id, stopped = str(uuid4()), False
    def stop(*_args):
        nonlocal stopped
        stopped = True
    signal.signal(signal.SIGTERM,stop)
    signal.signal(signal.SIGINT,stop)
    process, run_id = None,None
    try:
        while not stopped:
            run_id = claim_run(database,settings,args.backend,worker_id)
            if not run_id:
                time.sleep(2)
                continue
            process = multiprocessing.get_context('spawn').Process(target=child,args=(settings,run_id,worker_id))
            process.start()
            deadline = time.monotonic() + 1800
            while process.is_alive() and not stopped:
                process.join(timeout=1)
                if time.monotonic() > deadline:
                    finish_failure(database,settings,run_id,worker_id,'Đánh giá vượt giới hạn 30 phút.')
                    break
                if not heartbeat(database,settings,args.backend,worker_id,run_id):
                    break
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
                if process.is_alive():
                    process.kill()
            process.join()
            finish_failure(database,settings,run_id,worker_id,'Worker kết thúc trước khi có kết quả.')
            process = None
    finally:
        if process and process.is_alive():
            process.terminate()
            process.join(timeout=5)
            if process.is_alive():
                process.kill()
                process.join()
        if run_id:
            finish_failure(database,settings,run_id,worker_id,'Worker đã dừng; hãy tạo lượt đánh giá mới.')
        with WorkspaceData(database,settings).write(scope(settings)) as session:
            state = session.get(EvaluationWorkerState,(settings.workspace_id,args.backend))
            if state and state.worker_id == worker_id:
                session.delete(state)
        database.dispose()


if __name__ == '__main__':
    main()
