#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
from flask.ctx import RequestContext as RequestContextBase
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


class RequestContext(RequestContextBase):
    def __init__(self, app, environ, request=None):
        self.app = app
        if request is None:
            request = app.request_class(environ)
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
        elif app_ctx is None:
            app_ctx = self.app.app_context()
            self._implicit_app_ctx_stack.append(app_ctx)
        elif len(self._implicit_app_ctx_stack) > 0:
            app_ctx = self._implicit_app_ctx_stack[-1]
        else:
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


class AppContext(object):
    def __init__(self, app):
        self.app = app
        self.g = app.app_ctx_globals_class()

    def push(self):
        _app_ctx_stack.push(self)

    def pop(self):
        _app_ctx_stack.pop()

    def __enter__(self):
        self.push()
        return self

    def __exit__(self, exc_type, exc_value, tb):
        self.pop()
