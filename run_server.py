#!/usr/bin/env python
# -*- coding: utf-8 -*-
#

from __future__ import absolute_import
import os

from coco.app import Coco
from coco.tasks import command_task, record_task


os.environ.setdefault('COCO_CONFIG_MODULE', 'coco.config')
coco = Coco()

if __name__ == '__main__':
    try:
        os.mkdir('logs')
        os.mkdir('keys')
    except:
        pass
    command_task.run()
    record_task.run()
    coco.run_forever()
