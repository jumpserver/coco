# ~*~ coding: utf-8 ~*~
from __future__ import absolute_import
import time

from celery import Celery

from .conf import config
from .logger import get_logger
from .service import service

logger = get_logger(__file__)
app = Celery(config.get('NAME'))
app.conf.update(config)

while True:
    if service.is_authenticated():
        logger.info('App auth passed')
        break
    else:
        logger.warn('App auth failed, Access key error '
                    'or need admin active it')
        time.sleep(5)


@app.task
def send_command_log(data):
    service.send_command_log(data)
