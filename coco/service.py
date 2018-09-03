# -*- coding: utf-8 -*-
#

from .ctx import stack


def init_app(app):
    stack['current_app'] = app

