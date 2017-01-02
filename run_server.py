#!/usr/bin/env python
# -*- coding: utf-8 -*-
#

from coco import Coco

from config import Config

app = Coco()
app.config.from_object(Config)

if __name__ == '__main__':
    app.run_forever()
