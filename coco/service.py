# -*- coding: utf-8 -*-
#

from .ctx import stack, db_session
from . import models
from sqlalchemy import create_engine

from .config import config

from jms.service import AppService


def init_service():
    service = AppService(config)
    stack['app_service'] = service


def init_app(app):
    stack['current_app'] = app


def init_db():
    db_path = config['DB_FILE']
    engine = create_engine('sqlite:///{}'.format(db_path), echo=False)
    models.Base.metadata.create_all(engine)
    stack['db_engine'] = engine

