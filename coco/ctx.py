# -*- coding: utf-8 -*-
#

from werkzeug.local import LocalProxy
from functools import partial

from .config import config
from jms.service import AppService

stack = {}
__db_sessions = []


def _find(name):
    if stack.get(name):
        return stack[name]
    else:
        raise ValueError("Not found in stack: {}".format(name))


app_service = AppService(config)
app_service.initial()
current_app = LocalProxy(partial(_find, 'current_app'))
# app_service = LocalProxy(partial(_find, 'app_service'))
