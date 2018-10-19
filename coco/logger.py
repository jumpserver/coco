#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#

import os
import logging
from logging.config import dictConfig
from .config import config as app_config


def create_logger():
    level = app_config['LOG_LEVEL']
    log_dir = app_config.get('LOG_DIR')
    log_path = os.path.join(log_dir, 'coco.log')
    main_setting = {
        'handlers': ['console', 'file'],
        'level': level,
        'propagate': False,
    }
    config = dict(
        version=1,
        formatters={
            "main": {
                'format': '%(asctime)s [%(module)s %(levelname)s] %(message)s',
                'datefmt': '%Y-%m-%d %H:%M:%S',
            },
            'simple': {
                'format': '%(asctime)s [%(levelname)-8s] %(message)s',
                'datefmt': '%Y-%m-%d %H:%M:%S',
            }
        },
        handlers={
            'null': {
                'level': 'DEBUG',
                'class': 'logging.NullHandler',
            },
            'console': {
                'level': 'DEBUG',
                'class': 'logging.StreamHandler',
                'formatter': 'main'
            },
            'file': {
                'level': 'DEBUG',
                'class': 'logging.handlers.TimedRotatingFileHandler',
                'formatter': 'main',
                'filename': log_path,
                'when': "D",
                'interval': 1,
                "backupCount": 7
            },
        },
        loggers={
            'coco': main_setting,
            'paramiko': main_setting,
            'jms': main_setting,
            # 'socket.io': main_setting,
            # 'engineio': main_setting,
        }
    )
    dictConfig(config)
    logger = logging.getLogger()
    return logger


create_logger()
