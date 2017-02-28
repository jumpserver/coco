#!/usr/bin/env python
# ~*~ coding: utf-8 ~*~
#

import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
PROJECT_DIR = os.path.dirname(BASE_DIR)
__version__ = '0.4.0'


from .exceptions import SSHError
from .proxy import ProxyServer
from .interactive import InteractiveServer
from .app import Coco
