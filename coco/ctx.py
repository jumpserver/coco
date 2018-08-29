# -*- coding: utf-8 -*-
#

from werkzeug.local import LocalProxy
from functools import partial

from sqlalchemy.orm import sessionmaker, scoped_session

stack = {}
__db_sessions = []


def _find(name):
    if stack.get(name):
        return stack[name]
    else:
        raise ValueError("Not found in stack: {}".format(name))


def new_db_session():
    if __db_sessions:
        return __db_sessions[0]
    session = scoped_session(sessionmaker(autocommit=True, bind=db_engine))
    __db_sessions.append(session)
    return session


current_app = LocalProxy(partial(_find, 'current_app'))
app_service = LocalProxy(partial(_find, 'app_service'))
db_engine = LocalProxy(partial(_find, 'db_engine'))
db_session = LocalProxy(new_db_session)
