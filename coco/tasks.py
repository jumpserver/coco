#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#

from .ctx import app_service
from .utils import get_logger
from .session import Session

logger = get_logger(__file__)


class TaskHandler:
    def __init__(self):
        self.routes = {
            'kill_session': self.handle_kill_session
        }

    @staticmethod
    def handle_kill_session(task):
        logger.info("Handle kill session task: {}".format(task.args))
        session_id = task.args
        session = Session.sessions.get(session_id)
        if session:
            session.terminate()
        app_service.finish_task(task.id)

    def handle(self, task):
        func = self.routes.get(task.name)
        return func(task)
