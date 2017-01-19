# ~*~ coding: utf-8 ~*~
from __future__ import absolute_import

from celery import Celery

from core.conf import config
from jms import AppService


app_name = config.get('NAME')
endpoint = config.get('JUMPSERVER_ENDPOINT')
app = Celery(app_name)
app.conf.update(config)


app_service = AppService(app_name, endpoint)
