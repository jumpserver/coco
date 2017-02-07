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


class TtyIOParser(object):
    def __init__(self, width=80, height=24):
        self.screen = pyte.Screen(width, height)
        self.stream = pyte.ByteStream()
        self.stream.attach(self.screen)
        self.ps1_pattern = re.compile(r'^\[?.*@.*\]?[\$#]\s|mysql>\s')

    def clean_ps1_etc(self, command):
        return self.ps1_pattern.sub('', command)

    def parse_output(self, data, sep='\n'):
        output = []
        if not isinstance(data, bytes):
            data = data.encode('utf-8', 'ignore')

        self.stream.feed(data)
        for line in self.screen.display:
            if line.strip():
                output.append(line)
        self.screen.reset()
        return sep.join(output[0:-1])

    def parse_input(self, data):
        command = []
        if not isinstance(data, bytes):
            data = data.encode('utf-8', 'ignore')

        self.stream.feed(data)
        for line in self.screen.display:
            line = line.strip()
            if line:
                command.append(line)
        if command:
            command = command[-1]
        else:
            command = ''
        self.screen.reset()
        command = self.clean_ps1_etc(command)
        return command


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


def wrap_with_line_feed(s, before=0, after=1):
    return '\r\n' * before + s + '\r\n' * after


def wrap_with_color(text, color='white', background=None, bolder=False, underline=False):
    bolder_ = '1'
    underline_ = '4'
    color_map = {
        'black': '30',
        'red': '31',
        'green': '32',
        'brown': '33',
        'blue': '34',
        'purple': '35',
        'cyan': '36',
        'white': '37',
    }
    background_map = {
        'black': '40',
        'red': '41',
        'green': '42',
        'brown': '43',
        'blue': '44',
        'purple': '45',
        'cyan': '46',
        'white': '47',
    }

    wrap_with = []
    if bolder:
        wrap_with.append(bolder_)
    if underline:
        wrap_with.append(underline_)
    if background:
        wrap_with.append(background_map.get(background, ''))
    wrap_with.append(color_map.get(color, ''))
    return '\033[' + ';'.join(wrap_with) + 'm' + text + '\033[0m'


def wrap_with_warning(text, bolder=False):
    return wrap_with_color(text, color='red', bolder=bolder)


def wrap_with_info(text, bolder=False):
    return wrap_with_color(text, color='brown', bolder=bolder)


def wrap_with_primary(text, bolder=False):
    return wrap_with_color(text, color='green', bolder=bolder)


def wrap_with_title(text):
    return wrap_with_color(text, color='black', background='green')


def gen_uuid():
    return uuid.uuid4().get_hex()


def max_length(object_list, max_=30):
    try:
        length = max([len(obj.encode('utf-8')) for obj in object_list])
    except ValueError:
        length = max_

    if length > max_:
        return max_
    else:
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
