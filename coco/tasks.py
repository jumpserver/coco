#!/usr/bin/env python
# ~*~ coding: utf-8 -*-
#
from __future__ import unicode_literals

import os
import sys

from celery import Celery

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
PROJECT_DIR = os.path.dirname(BASE_DIR)
sys.path.append(BASE_DIR)
sys.path.append(PROJECT_DIR)

from sdk import AppService, UserSerivce
from config import Config


CONFIG = Config
app = Celery('terminal', broker=CONFIG.BROKER_URL)


class Task(object):
    def __init__(self, name):
        self.name = name

    @app.task
    def create_command_log(self, command_no, command, output, log_id, datetime):
        api = AppRequest(self.name)
        api.create_command_log(command_no, command, output, log_id, datetime)
