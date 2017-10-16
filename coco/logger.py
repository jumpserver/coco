#!/usr/bin/env python
# -*- coding: utf-8 -*-
#

import os
import logging
from logging import StreamHandler
from logging.handlers import TimedRotatingFileHandler


LOG_LEVELS = {
    'DEBUG': logging.DEBUG,
    'INFO': logging.INFO,
    'WARN': logging.WARNING,
    'WARNING': logging.WARNING,
    'ERROR': logging.ERROR,
    'FATAL': logging.FATAL,
    'CRITICAL': logging.CRITICAL,
}


def create_logger(app):
    level = app.config['LOG_LEVEL']
    level = LOG_LEVELS.get(level, logging.INFO)
    log_dir = app.config.get('LOG_DIR')
    log_path = os.path.join(log_dir, 'coco.log')
    logger = logging.getLogger()

    main_formatter = logging.Formatter(
        fmt='%(asctime)s [%(module)s %(levelname)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S')
    console_handler = StreamHandler()
    file_handler = TimedRotatingFileHandler(
        filename=log_path, when='D', backupCount=10)

    for handler in [console_handler, file_handler]:
        handler.setFormatter(main_formatter)
        logger.addHandler(handler)
    logger.setLevel(level)
