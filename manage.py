#!/usr/bin/python
#

import os
import sys

from coco import Coco

try:
    import conf
except ImportError:
    print("Please prepare config file `cp conf_example.py conf.py`")
    sys.exit(1)

try:
    os.mkdir("logs")
    os.mkdir("keys")
except:
    pass


coco = Coco()
coco.config.from_object(conf)

# Todo:
# 0. argparser
# 1. register application user
# 2. backup record file
# 3. xxx

if __name__ == '__main__':
    coco.run_forever()
