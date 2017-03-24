#!/usr/bin/env python
# -*- coding: utf-8 -*-
#

from __future__ import unicode_literals
from six import string_types
import os
import logging
import re
import sys
import uuid
import json
import base64
import datetime
import copy
from logging.config import dictConfig
try:
    import cStringIO as StringIO
except ImportError:
    import StringIO

try:
    from collections import OrderedDict
except ImportError:
    OrderedDict = dict

from itsdangerous import TimedJSONWebSignatureSerializer, SignatureExpired, \
    BadSignature, JSONWebSignatureSerializer
import paramiko
from paramiko.rsakey import RSAKey
import pyte


class Signer(object):
    def __init__(self, secret_key=None):
        self.secret_key = secret_key

    def sign(self, value):
        s = JSONWebSignatureSerializer(self.secret_key)
        return s.dumps(value)

    def unsign(self, value):
        s = JSONWebSignatureSerializer(self.secret_key)
        return s.loads(value)

    def sign_t(self, value, expires_in=3600):
        s = TimedJSONWebSignatureSerializer(self.secret_key, expires_in=expires_in)
        return s.dumps(value)

    def unsign_t(self, value):
        s = TimedJSONWebSignatureSerializer(self.secret_key)
        return s.loads(value)


def ssh_key_string_to_obj(text):
    key_f = StringIO.StringIO(text)
    key = None
    try:
        key = paramiko.RSAKey.from_private_key(key_f)
    except paramiko.SSHException:
        pass

    try:
        key = paramiko.DSSKey.from_private_key(key_f)
    except paramiko.SSHException:
        pass
    return key


def ssh_pubkey_gen(private_key=None, username='jumpserver', hostname='localhost'):
    if isinstance(private_key, string_types):
        private_key = ssh_key_string_to_obj(private_key)

    if not isinstance(private_key, (paramiko.RSAKey, paramiko.DSSKey)):
        raise IOError('Invalid private key')

    public_key = "%(key_type)s %(key_content)s %(username)s@%(hostname)s" % {
        'key_type': private_key.get_name(),
        'key_content': private_key.get_base64(),
        'username': username,
        'hostname': hostname,
    }
    return public_key


def ssh_key_gen(length=2048, type='rsa', password=None, username='jumpserver', hostname=None):
    """Generate user ssh private and public key

    Use paramiko RSAKey generate it.
    :return private key str and public key str
    """

    if hostname is None:
        hostname = os.uname()[1]

    f = StringIO.StringIO()

    try:
        if type == 'rsa':
            private_key_obj = paramiko.RSAKey.generate(length)
        elif type == 'dsa':
            private_key_obj = paramiko.DSSKey.generate(length)
        else:
            raise IOError('SSH private key must be `rsa` or `dsa`')
        private_key_obj.write_private_key(f, password=password)
        private_key = f.getvalue()
        public_key = ssh_pubkey_gen(private_key_obj, username=username, hostname=hostname)
        return private_key, public_key
    except IOError:
        raise IOError('These is error when generate ssh key.')



def gen_uuid():
    return uuid.uuid4().get_hex()


def max_length(object_list, max_=30, min_=8):
    try:
        length = max([len(obj.encode('utf-8')) for obj in object_list])
    except ValueError:
        length = max_

    if length > max_:
        return max_

    if length < min_:
        return min_
    return length


def system_user_max_length(asset_list, max_=30):
    system_users_username = []
    for asset in asset_list:
        asset_system_user = []
        for system_user in asset.system_users_granted:
            asset_system_user.append(system_user.username)
        system_users_username.append(', '.join(asset_system_user))

    try:
        length = max(len(s) for s in system_users_username)
    except ValueError:
        length = max_

    if length > max_:
        return max_
    else:
        return length

signer = Signer()
