# -*- coding: utf-8 -*-
#

from werkzeug.local import LocalProxy
from functools import partial


stack = {}


def _find(name):
    if stack.get(name):
        return stack[name]
    else:
        raise ValueError("Not found in stack: {}".format(name))


current_app = LocalProxy(partial(_find, 'app'))
app_service = LocalProxy(partial(_find, 'service'))

# current_app = []
# current_service = []
