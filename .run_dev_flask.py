#!/usr/bin/python
#
from coco.httpd import app
from coco.logger import create_logger

create_logger()

if __name__ == '__main__':
    app.run()
