# -*- coding: utf-8 -*-
#

from jms.service import AppService
from .conf import config


inited = False
app_service = AppService(config)

if not inited:
    app_service.initial()
    inited = True
