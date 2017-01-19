#!/usr/bin/env python
# ~*~ coding: utf-8 ~*~
#

import sys
import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
PROJECT_DIR = os.path.dirname(BASE_DIR)
__version__ = '0.4.0'

from .utils import wrap_with_line_feed as wr, \
    wrap_with_info as info, wrap_with_warning as warning, \
    wrap_with_primary as primary, wrap_with_title as title, \
    compute_max_length as cml
from .exceptions import SSHError
from .proxy import ProxyServer
from .interactive import InteractiveServer
from .app import Coco
