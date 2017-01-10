# -*- coding: utf-8 -*-
#
import sys
import threading
from flask.ctx import RequestContext as RequestContextBase, AppContext as AppContextBase
from .globals import _app_ctx_stack, _request_ctx_stack


_sentinel = object()


class Request(object):
    method = 'shell'
    assets = []
    win_width = 80
    win_height = 24
    change_win_size_event = None
    shell_event = None
    command_event = None

    def __init__(self, environ):
        self.environ = environ
        self.user = None


class _AppCtxGlobals(object):
    """A plain object."""

    def get(self, name, default=None):
        return self.__dict__.get(name, default)

    def pop(self, name, default=_sentinel):
        if default is _sentinel:
            return self.__dict__.pop(name)
        else:
            return self.__dict__.pop(name, default)

    def setdefault(self, name, default=None):
        return self.__dict__.setdefault(name, default)

    def __contains__(self, item):
        return item in self.__dict__

    def __iter__(self):
        return iter(self.__dict__)

    # def __repr__(self):
    #     top = _app_ctx_stack.top
    #     if top is not None:
    #         return '<coco.g of %r>' % top.app.name
    #     return object.__repr__(self)


class RequestContext(RequestContextBase):
    def __init__(self, app, environ, request=None):
        self.app = app
        if request is None:
            request = Request(environ)
        self.request = request
        self._implicit_app_ctx_stack = []

    def match_request(self):
        return None

    def push(self):
        # Before we push the request context we have to ensure that there
        # is an application context.
        app_ctx = _app_ctx_stack.top
        if app_ctx is None and len(self._implicit_app_ctx_stack) > 0:
            app_ctx = self._implicit_app_ctx_stack[-1]

        if app_ctx is None:  # or app_ctx.app != self.app:
            app_ctx = self.app.app_context()
            self._implicit_app_ctx_stack.append(app_ctx)
        app_ctx.push()
        _request_ctx_stack.push(self)

    def pop(self, exc=_sentinel):
        app_ctx = self._implicit_app_ctx_stack.pop()
        _request_ctx_stack.pop()

        if app_ctx is not None:
            app_ctx.pop()

    def __repr__(self):
        return '<%s request of %s>' % (
            self.__class__.__name__,
            self.app.name,
        )

    def __enter__(self):
        self.push()
        return self

    __str__ = __repr__


class AppContext(object):
    def __init__(self, app):
        self.app = app
        self.g = _AppCtxGlobals()

    def push(self):
        _app_ctx_stack.push(self)

    def pop(self):
        _app_ctx_stack.pop()

    def copy(self):
        return self.__class__(self, self.app)
