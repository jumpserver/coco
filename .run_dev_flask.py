#!/usr/bin/python
#
from coco.httpd import app, socket_io
from coco.logger import create_logger

create_logger()

if __name__ == '__main__':
    socket_io.run(app, debug=False)
