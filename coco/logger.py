#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#

import os
import socket
import logging
from logging.config import dictConfig
from .conf import config as app_config


def get_logger_config():
    level = app_config['LOG_LEVEL']
    log_dir = app_config['LOG_DIR']
    filename = 'coco-{}.log'.format(socket.gethostname())
    if not os.path.isdir(log_dir):
        os.makedirs(log_dir)
    log_path = os.path.join(log_dir, filename)
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
                'class': 'logging.handlers.RotatingFileHandler',
                'formatter': 'main',
                'filename': log_path,
                'maxBytes': 1024 * 1024 * 100,
                'backupCount': 7,
            },
        },
        loggers={
            'coco': main_setting,
            'jms': main_setting,
            # 'socket.io': main_setting,
            # 'engineio': main_setting,
        }
    )
    if level.lower() == 'debug':
        config['loggers']['paramiko'] = main_setting
        # config['loggers']['socket.io'] = main_setting
        # config['loggers']['engineio'] = main_setting
    return config


def create_logger():
    config = get_logger_config()
    dictConfig(config)
    logger = logging.getLogger()
    return logger


def append_engineio_logger():
    main_setting = {
        'handlers': ['console', 'file'],
        'level': 'DEBUG',
        'propagate': False,
    }
    config = get_logger_config()
    config['loggers']['engineio'] = main_setting
    dictConfig(config)
    logger = logging.getLogger()
    return logger


create_logger()
