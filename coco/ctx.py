#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
from werkzeug.local import Local


class Request(object):
    def __init__(self):
        self.remote_addr = None
        self.port = None
        self.user = None
        self.client = None
        self.channel_height = None
        self.channel_width = None


def get_req_ctx_obj(name, default=None):
    if default is None:
        default = {}
    if not hasattr(ctx, name):
        setattr(ctx, name, default)
    return getattr(ctx, name)


ctx = Local()
request = get_req_ctx_obj('request', default=Request())