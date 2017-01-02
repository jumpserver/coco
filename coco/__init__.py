#!/usr/bin/env python
# ~*~ coding: utf-8 ~*~
#

import os

from jms import UserService, AppService

from .config import Config

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
from .app import Coco
