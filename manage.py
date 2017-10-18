#!/usr/bin/python
#

import os

from coco import Coco
import conf

try:
    os.mkdir("logs")
    os.mkdir("keys")
except:
    pass


coco = Coco()
coco.config.from_object(conf)

print(coco.root_path)

if __name__ == '__main__':
    coco.run_forever()
