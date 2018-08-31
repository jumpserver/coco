# -*- coding: utf-8 -*-
#

from .ctx import stack
from . import models
from sqlalchemy import create_engine

from .config import config

from jms.service import AppService





def init_app(app):
    stack['current_app'] = app

