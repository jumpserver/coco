#!/usr/bin/env python
# -*- coding: utf-8 -*-
#

import os
from logging.config import dictConfig


LOGGING = {
        'version': 1,
        'disable_existing_loggers': False,
        'formatters': {
            'verbose': {
                'format': '%(levelname)s %(asctime)s %(module)s %(process)d %(thread)d %(message)s'
            },
            'main': {
                'datefmt': '%Y-%m-%d %H:%M:%S',
                'format': '%(asctime)s [%(module)s %(levelname)s] %(message)s',
            },
            'simple': {
                'format': '%(levelname)s %(message)s'
            },
        },
        'handlers': {
            'null': {
                'level': 'DEBUG',
                'class': 'logging.NullHandler',
            },
            'console': {
                'level': 'DEBUG',
                'class': 'logging.StreamHandler',
                'formatter': 'main',
                'stream': 'ext://sys.stdout',
            },
            'file': {
                'level': 'DEBUG',
                'class': 'logging.handlers.TimedRotatingFileHandler',
                'formatter': 'main',
                'filename': '%s',
                'when': 'D',
                'backupCount': 10,
            },
        },
        'loggers': {
            'coco': {
                'handlers': ['console', 'file'],
                'level': 'debug',
                'propagate': True,
            },
        }
    }


def create_logger(app):
    level = app.config.get('LOG_LEVEL', 'warning')
    log_path = app.config.get('LOG_PATH', os.path.join(app.root_path, 'logs', 'coco.log'))
    LOGGING['file']['filename'] = log_path
    LOGGING['loggers']['level'] = level
    dictConfig(LOGGING)
