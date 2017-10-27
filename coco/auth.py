#!/usr/bin/env python
# -*- coding: utf-8 -*-
#

import os
import logging
import time

from . import utils
from .exception import LoadAccessKeyError


def make_signature(access_key_secret, date=None):
    if isinstance(date, bytes):
        date = date.decode("utf-8")
    if isinstance(date, int):
        date_gmt = utils.http_date(date)
    elif date is None:
        date_gmt = utils.http_date(int(time.time()))
    else:
        date_gmt = date
    data = str(access_key_secret) + "\n" + date_gmt
    return utils.content_md5(data)


class AccessKeyAuth(object):
    def __init__(self, access_key):
        self.id = access_key.id
        self.secret = access_key.secret

    def sign_request(self, req):
        req.headers['Date'] = utils.http_date()
        signature = utils.make_signature(self.secret)
        req.headers['Authorization'] = "Sign {0}:{1}".format(self.id, signature)
        return req

#
# class AccessTokenAuth(object):
#     def __init__(self, token):
#         self.token = token
#
#     def sign_request(self, req):
#         req.headers['Authorization'] = 'Bearer {0}'.format(self.token)
#         return req
#
#
# class SessionAuth(object):
#     def __init__(self, session_id, csrf_token):
#         self.session_id = session_id
#         self.csrf_token = csrf_token
#
#     def sign_request(self, req):
#         cookie = [v for v in req.headers.get('Cookie', '').split(';')
#                   if v.strip()]
#         cookie.extend(['sessionid='+self.session_id,
#                        'csrftoken='+self.csrf_token])
#         req.headers['Cookie'] = ';'.join(cookie)
#         req.headers['X-CSRFTOKEN'] = self.csrf_token
#         return req


# class Auth(object):
#     def __init__(self, token=None, access_key_id=None,
#                  access_key_secret=None,
#                  session_id=None, csrf_token=None):
#
#         if token is not None:
#             self.instance = AccessTokenAuth(token)
#         elif access_key_id and access_key_secret:
#             self.instance = AccessKeyAuth(access_key_id, access_key_secret)
#         elif session_id and csrf_token:
#             self.instance = SessionAuth(session_id, csrf_token)
#         else:
#             raise SyntaxError('Need token or access_key_id, access_key_secret '
#                               'or session_id, csrf_token')
#
#     def sign_request(self, req):
#         return self.instance.sign_request(req)


class AccessKey(object):
    def __init__(self, id=None, secret=None):
        self.id = id
        self.secret = secret

    @staticmethod
    def clean(value, sep=':', silent=False):
        try:
            id, secret = value.split(sep)
        except (AttributeError, ValueError) as e:
            if not silent:
                raise LoadAccessKeyError(e)
            return '', ''
        else:
            return id, secret

    @classmethod
    def load_from_val(cls, val, **kwargs):
        id, secret = cls.clean(val, **kwargs)
        return cls(id, secret)

    @classmethod
    def load_from_env(cls, env, **kwargs):
        value = os.environ.get(env)
        id, secret = cls.clean(value, **kwargs)
        return cls(id, secret)

    @classmethod
    def load_from_f(cls, f, **kwargs):
        value = ''
        if isinstance(f, str) and os.path.isfile(f):
            f = open(f)
        if hasattr(f, 'read'):
            for line in f:
                if line and not line.strip().startswith('#'):
                    value = line.strip()
                    break
            f.close()
        id, secret = cls.clean(value, **kwargs)
        return cls(id, secret)

    def save_to_f(self, f, silent=False):
        if isinstance(f, str):
            f = open(f, 'w')
        try:
            f.write(str('{0}:{1}'.format(self.id, self.secret)))
        except IOError as e:
            logging.error('Save access key error: {}'.format(e))
            if not silent:
                raise
        finally:
            f.close()

    def __nonzero__(self):
        return bool(self.id and self.secret)
    __bool__ = __nonzero__

    def __str__(self):
        return '{0}:{1}'.format(self.id, self.secret)
    __repr__ = __str__


class AppAccessKey(AccessKey):
    """使用Access key来认证"""

    def __init__(self, app, id=None, secret=None):
        super().__init__(id=id, secret=secret)
        self.app = app
        self._key_store = app.config['ACCESS_KEY_STORE']
        self._key_env = app.config['ACCESS_KEY_ENV']
        self._key_val = app.config['ACCESS_KEY']

    def load_from_conf_env(self, sep=':', silent=False):
        return super().load_from_env(self._key_env, sep=sep, silent=silent)

    def load_from_conf(self, sep=':', silent=False):
        return super().load_from_val(self._key_val, sep=sep, silent=silent)

    def load_from_key_store(self, sep=':', silent=False):
        return super().load_from_f(self._key_store, sep=sep, silent=silent)

    def load(self, **kwargs):
        """Should return access_key_id, access_key_secret"""
        for method in [self.load_from_env,
                       self.load_from_conf,
                       self.load_from_key_store]:
            try:
                return method(**kwargs)
            except LoadAccessKeyError:
                continue
        return None

    def save_to_key_store(self):
        return super().save_to_f(self._key_store)