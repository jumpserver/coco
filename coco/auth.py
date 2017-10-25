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
    def __init__(self, access_key_id, access_key_secret):
        self.id = access_key_id
        self.secret = access_key_secret

    def sign_request(self, req):
        req.headers['Date'] = utils.http_date()
        signature = utils.make_signature(self.secret)
        req.headers['Authorization'] = "Sign {0}:{1}".format(self.id, signature)
        return req


class AccessTokenAuth(object):
    def __init__(self, token):
        self.token = token

    def sign_request(self, req):
        req.headers['Authorization'] = 'Bearer {0}'.format(self.token)
        return req


class SessionAuth(object):
    def __init__(self, session_id, csrf_token):
        self.session_id = session_id
        self.csrf_token = csrf_token

    def sign_request(self, req):
        cookie = [v for v in req.headers.get('Cookie', '').split(';')
                  if v.strip()]
        cookie.extend(['sessionid='+self.session_id,
                       'csrftoken='+self.csrf_token])
        req.headers['Cookie'] = ';'.join(cookie)
        req.headers['X-CSRFTOKEN'] = self.csrf_token
        return req


class Auth(object):
    def __init__(self, token=None, access_key_id=None,
                 access_key_secret=None,
                 session_id=None, csrf_token=None):

        if token is not None:
            self.instance = AccessTokenAuth(token)
        elif access_key_id and access_key_secret:
            self.instance = AccessKeyAuth(access_key_id, access_key_secret)
        elif session_id and csrf_token:
            self.instance = SessionAuth(session_id, csrf_token)
        else:
            raise SyntaxError('Need token or access_key_id, access_key_secret '
                              'or session_id, csrf_token')

    def sign_request(self, req):
        return self.instance.sign_request(req)


class AccessKey(object):
    def __init__(self, id=None, secret=None):
        self.id = id
        self.secret = secret

    @staticmethod
    def clean(value, delimiter=':', silent=False):
        try:
            id, secret = value.split(delimiter)
        except (AttributeError, ValueError) as e:
            if not silent:
                raise LoadAccessKeyError(e)
            return '', ''
        else:
            return id, secret

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


class ServiceAccessKey(AccessKey):
    """使用Access key来认证"""

    # 默认从配置文件中读取的设置
    # 配置文件中ACCESS_KEY值的名称
    conf_attr_var = 'ACCESS_KEY'
    # 配置文件中配置环境变量的名称
    conf_env_var = 'ACCESS_KEY_ENV'
    # 配置文件中定义Access key store的位置
    conf_store_var = 'ACCESS_KEY_STORE'

    # 如果用户配置中没有设置, 方法中也没填入, 使用下面默认
    default_key_env = 'ACCESS_KEY_ENV'
    default_key_store = os.path.join(os.environ.get('HOME', ''), '.access_key')

    def __init__(self, id=None, secret=None, config=None):
        super().__init__(id=id, secret=secret)
        self.config = config or {}
        self._key_store = None
        self._key_env = None

    # 获取key store位置
    @property
    def key_store(self):
        if self._key_store:
            return self._key_store
        elif self.conf_store_var in self.config:
            return self.config[self.conf_store_var]
        else:
            return self.default_key_store

    @key_store.setter
    def key_store(self, value):
        self._key_store = value

    # 获取access key的环境变量名
    @property
    def key_env(self):
        if self._key_env:
            return self._key_env
        elif self.conf_env_var in self.config:
            return self.config[self.conf_env_var]
        else:
            return self.default_key_env

    @key_env.setter
    def key_env(self, value):
        self._key_env = value

    def load_from_conf_env(self, env=None, delimiter=':'):
        if env is None:
            env = self.key_env
        return super(ServiceAccessKey, self).\
            load_from_env(env, delimiter=delimiter)

    def load_from_conf_setting(self, attr=None, delimiter=':', silent=False):
        value = ''
        if attr is None:
            attr = self.conf_attr_var
        if attr in self.config:
            value = self.config.get(attr)
        return self.clean(value, delimiter, silent)

    def load_from_key_store(self, f=None, delimiter=':', silent=False):
        if f is None:
            f = self.key_store
        return super(ServiceAccessKey, self).load_from_f(f, delimiter, silent)

    def load_from_conf_all(self, **kwargs):
        """Should return access_key_id, access_key_secret"""
        for method in [self.load_from_conf_setting,
                       self.load_from_key_store,
                       self.load_from_conf_env]:
            try:
                return method(**kwargs)
            except LoadAccessKeyError:
                continue

        if not (bool(self.id) and bool(self.secret)):
            logging.error('Load access key failed')

    def save_to_key_store(self, key_store=None, silent=True):
        if key_store is None:
            key_store = self.key_store
        return super(ServiceAccessKey, self).save_to_f(key_store, silent)