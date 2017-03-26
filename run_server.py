#!/usr/bin/env python
# -*- coding: utf-8 -*-
#

from __future__ import absolute_import
import os

try:
    os.mkdir('logs')
    os.mkdir('keys')
except:
    pass

from coco.app import Coco
from coco.tasks import command_task, record_task


coco = Coco()

if __name__ == '__main__':
    command_task.run()
    record_task.run()
    coco.run_forever()
