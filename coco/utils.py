#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#

from __future__ import unicode_literals

import hashlib
import logging
import re
import os
import threading
import base64
import calendar
import time
import datetime
import gettext
from io import StringIO
from binascii import hexlify

import paramiko
import pyte
import pytz
from email.utils import formatdate
from queue import Queue, Empty

from .exception import NoAppException

BASE_DIR = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))


def ssh_key_string_to_obj(text, password=None):
    key = None
    try:
        key = paramiko.RSAKey.from_private_key(StringIO(text), password=password)
    except paramiko.SSHException:
        pass

    try:
        key = paramiko.DSSKey.from_private_key(StringIO(text), password=password)
    except paramiko.SSHException:
        pass
    return key


def ssh_pubkey_gen(private_key=None, username='jumpserver', hostname='localhost'):
    if isinstance(private_key, str):
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


def ssh_key_gen(length=2048, type='rsa', password=None,
                username='jumpserver', hostname=None):
    """Generate user ssh private and public key

    Use paramiko RSAKey generate it.
    :return private key str and public key str
    """

    if hostname is None:
        hostname = os.uname()[1]

    f = StringIO()

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


class TtyIOParser(object):
    def __init__(self, width=80, height=24):
        self.screen = pyte.Screen(width, height)
        self.stream = pyte.ByteStream()
        self.stream.attach(self.screen)
        self.ps1_pattern = re.compile(r'^\[?.*@.*\]?[\$#]\s|mysql>\s')

    def clean_ps1_etc(self, command):
        return self.ps1_pattern.sub('', command)

    def parse_output(self, data, sep='\n'):
        """
        Parse user command output

        :param data: output data list like, [b'data', b'data']
        :param sep:  line separator
        :return: output unicode data
        """
        output = []

        for d in data:
            self.stream.feed(d)
        try:
            for line in self.screen.display:
                if line.strip():
                    output.append(line)
        except IndexError:
            pass
        self.screen.reset()
        return sep.join(output[0:-1]).strip()

    def parse_input(self, data):
        """
        Parse user input command

        :param data: input data list, like [b'data', b'data']
        :return: command unicode
        """
        command = []
        for d in data:
            self.stream.feed(d)
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
        return command.strip()


def is_obj_attr_has(obj, val, attrs=("hostname", "ip", "comment")):
    if not attrs:
        vals = [val for val in obj.__dict__.values() if isinstance(val, (str, int))]
    else:
        vals = [getattr(obj, attr) for attr in attrs if
                hasattr(obj, attr) and isinstance(hasattr(obj, attr), (str, int))]

    for v in vals:
        if str(v).find(val) != -1:
            return True
    return False


def is_obj_attr_eq(obj, val, attrs=("id", "hostname", "ip")):
    if not attrs:
        vals = [val for val in obj.__dict__.values() if isinstance(val, (str, int))]
    else:
        vals = [getattr(obj, attr) for attr in attrs if hasattr(obj, attr)]

    for v in vals:
        if str(v) == str(val):
            return True
    return False


def wrap_with_line_feed(s, before=0, after=1):
    if isinstance(s, bytes):
        return b'\r\n' * before + s + b'\r\n' * after
    return '\r\n' * before + s + '\r\n' * after


def wrap_with_color(text, color='white', background=None,
                    bolder=False, underline=False):
    bolder_ = '1'
    _underline = '4'
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
        wrap_with.append(_underline)
    if background:
        wrap_with.append(background_map.get(background, ''))
    wrap_with.append(color_map.get(color, ''))

    is_bytes = True if isinstance(text, bytes) else False

    if is_bytes:
        text = text.decode("utf-8")
    data = '\033[' + ';'.join(wrap_with) + 'm' + text + '\033[0m'
    if is_bytes:
        return data.encode('utf-8')
    else:
        return data


def wrap_with_warning(text, bolder=False):
    return wrap_with_color(text, color='red', bolder=bolder)


def wrap_with_info(text, bolder=False):
    return wrap_with_color(text, color='brown', bolder=bolder)


def wrap_with_primary(text, bolder=False):
    return wrap_with_color(text, color='green', bolder=bolder)


def wrap_with_title(text):
    return wrap_with_color(text, color='black', background='green')


def split_string_int(s):
    """Split string or int

    example: test-01-02-db => ['test-', '01', '-', '02', 'db']
    """
    string_list = []
    index = 0
    pre_type = None
    word = ''
    for i in s:
        if index == 0:
            pre_type = int if i.isdigit() else str
            word = i
        else:
            if pre_type is int and i.isdigit() or pre_type is str and not i.isdigit():
                word += i
            else:
                string_list.append(word.lower() if not word.isdigit() else int(word))
                word = i
                pre_type = int if i.isdigit() else str
        index += 1
    string_list.append(word.lower() if not word.isdigit() else int(word))
    return string_list


def sort_assets(assets, order_by='hostname'):
    if order_by == 'ip':
        assets = sorted(assets, key=lambda asset: [int(d) for d in asset.ip.split('.') if d.isdigit()])
    else:
        assets = sorted(assets, key=lambda asset: getattr(asset, order_by))
    return assets


def _gettext():
    gettext.bindtextdomain("coco", os.path.join(BASE_DIR, "locale"))
    gettext.textdomain("coco")
    return gettext.gettext


def get_private_key_fingerprint(key):
    line = hexlify(key.get_fingerprint())
    return b':'.join([line[i:i+2] for i in range(0, len(line), 2)])


def make_message():
    os.makedirs(os.path.join(BASE_DIR, "locale", "zh_CN"))
    pass


def compile_message():
    pass


def get_logger(file_name):
    return logging.getLogger('coco.'+file_name)


zh_pattern = re.compile(u'[\u4e00-\u9fa5]+')


def len_display(s):
    length = 0
    for i in s:
        if zh_pattern.match(i):
            length += 2
        else:
            length += 1
    return length


ugettext = _gettext()
