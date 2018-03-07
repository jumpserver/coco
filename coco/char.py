#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#

BACKSPACE_CHAR = {b'\x08': b'\x08\x1b[K', b'\x7f': b'\x08\x1b[K'}
ENTER_CHAR = [b'\r', b'\n', b'\r\n']
ENTER_CHAR_ORDER = [ord(b'\r'), ord(b'\n')]
UNSUPPORTED_CHAR = {b'\x15': 'Ctrl-U', b'\x0c': 'Ctrl-L', b'\x05': 'Ctrl-E'}
CLEAR_CHAR = b'\x1b[H\x1b[2J'
BELL_CHAR = b'\x07'
NEW_LINE = b'\r\n'
RZ_PROTOCOL_CHAR = b'**\x18B0900000000a87c\r\x8a\x11'
