#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#

import sys
import subprocess
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


if __name__ == '__main__':
    try:
        subprocess.call(['./cocod', 'start'], stdin=sys.stdin,
                        stdout=sys.stdout, stderr=sys.stderr)
    except KeyboardInterrupt:
        subprocess.call(['./cocod', 'stop'], stdin=sys.stdin,
                        stdout=sys.stdout, stderr=sys.stderr)
