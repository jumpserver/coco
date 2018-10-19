# -*- coding: utf-8 -*-
#

import os
import uuid
from flask_socketio import SocketIO, Namespace, join_room
from flask import Flask, request

from ..models import Connection, WSProxy
from ..proxy import ProxyServer
from ..utils import get_logger
from ..service import app_service
from ..config import config

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
logger = get_logger(__file__)


class BaseNamespace(Namespace):
    current_user = None

    def on_connect(self):
        self.current_user = self.get_current_user()
        logger.debug("{} connect websocket".format(self.current_user))

    def get_current_user(self):
        session_id = request.cookies.get('sessionid', '')
        csrf_token = request.cookies.get('csrftoken', '')
        user = None
        if session_id and csrf_token:
            user = app_service.check_user_cookie(session_id, csrf_token)
        msg = "Get current user: session_id<{}> => {}".format(
            session_id, user
        )
        logger.debug(msg)
        request.current_user = user
        return user
