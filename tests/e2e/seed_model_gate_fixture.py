"""Explicit synthetic evidence for the older deployment-mechanics browser test."""
import argparse
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace

from sqlalchemy import select

from app.config import Settings
from app.model_registry_db import RegisteredModel
from app.platform_db import Membership, create_database
from tests.evaluation_fixtures import seed_computed_validation


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('config',type=Path)
    args=parser.parse_args()
    config_path=args.config.resolve()
    if not config_path.is_relative_to(Path(tempfile.gettempdir()).resolve()):
        parser.error('Only temporary browser fixtures are allowed')
    config=json.loads(config_path.read_bytes())
    if any(not Path(config[key]).resolve().is_relative_to(config_path.parent)
           for key in ('database_path','registry_root','evaluation_root')):
        parser.error('All fixture storage must stay under the temporary output directory')
    settings=Settings(database_url='sqlite:///'+config['database_path'],workspace_id=config['workspace_id'],
        model_registry_roots=(Path(config['registry_root']),),model_evaluation_roots=(Path(config['evaluation_root']),),
        collection_dir=config_path.parent/'unused-collection',model_deployment_target=config['target_id'])
    db=create_database(settings.database_url)
    try:
        with db.session() as session:
            membership=session.scalar(select(Membership).where(Membership.workspace_id==settings.workspace_id))
            candidate=session.scalar(select(RegisteredModel).where(RegisteredModel.workspace_id==settings.workspace_id,
                RegisteredModel.model_version==config['candidate']['version']))
            actor_id,candidate_id=membership.user_id,candidate.id
        client=SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(settings=settings,platform_database=db)),
            get=lambda _path: SimpleNamespace(json=lambda: {'user':{'id':actor_id}}))
        seed_computed_validation(client,candidate_id,json.loads(Path(config['reports']['passing']).read_bytes()))
    finally:
        db.dispose()


if __name__ == '__main__': main()
