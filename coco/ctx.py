#!/usr/bin/env python
# -*- coding: utf-8 -*-
#

from functools import partial

from dotmap import DotMap
from werkzeug.local import LocalStack, LocalProxy
from flask.globals import request, g, _app_ctx_stack as _g_ctx_stack, \
    _request_ctx_stack, _lookup_req_object


class RawMixin(object):
    @property
    def raw(self):
        return self


class Request(DotMap, RawMixin):
    remote_addr = ''
    client = None
    user = DotMap()
    win_width = 80
    win_height = 24


class G(DotMap, RawMixin):
    user_service = None


_client_channel_ctx_stack = LocalStack()
client_channel = LocalProxy(partial(_lookup_req_object, 'client_channel'))

