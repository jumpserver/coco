#!/usr/bin/env python
# -*- coding: utf-8 -*-
#

import os
import logging
import time

from . import utils
from .exception import LoadAccessKeyError


class AccessKeyAuth(object):
    def __init__(self, access_key):
        self.id = access_key.id
        self.secret = access_key.secret

    def sign_request(self, req):
        req.headers['Date'] = utils.http_date()
        signature = utils.make_signature(self.secret)
        req.headers['Authorization'] = "Sign {0}:{1}".format(self.id, signature)
        return req


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
        return cls(id=id, secret=secret)

    @classmethod
    def load_from_env(cls, env, **kwargs):
        value = os.environ.get(env)
        id, secret = cls.clean(value, **kwargs)
        return cls(id=id, secret=secret)

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
        return cls(id=id, secret=secret)

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

    def __bool__(self):
        return bool(self.id and self.secret)

    def __str__(self):
        return '{0}:{1}'.format(self.id, self.secret)

    def __repr__(self):
        return '{0}:{1}'.format(self.id, self.secret)


class AppAccessKey(AccessKey):
    """使用Access key来认证"""

    def __init__(self, id=None, secret=None):
        super().__init__(id=id, secret=secret)
        self.app = None

    def set_app(self, app):
        self.app = app

    @property
    def _key_env(self):
        return self.app.config['ACCESS_KEY_ENV']

    @property
    def _key_val(self):
        return self.app.config['ACCESS_KEY']

    @property
    def _key_file(self):
        return self.app.config['ACCESS_KEY_FILE']

    def load_from_conf_env(self, sep=':', silent=False):
        return super().load_from_env(self._key_env, sep=sep, silent=silent)

    def load_from_conf_val(self, sep=':', silent=False):
        return super().load_from_val(self._key_val, sep=sep, silent=silent)

    def load_from_conf_file(self, sep=':', silent=False):
        return super().load_from_f(self._key_file, sep=sep, silent=silent)

    def load(self, **kwargs):
        """Should return access_key_id, access_key_secret"""
        for method in [self.load_from_conf_env,
                       self.load_from_conf_val,
                       self.load_from_conf_file]:
            try:
                return method(**kwargs)
            except LoadAccessKeyError:
                continue
        return None

    def save_to_file(self):
        return super().save_to_f(self._key_file)