#! coding: utf-8


class SSHServer:

    def __init__(self, app=None):
        self.app = app

    @classmethod
    def run(cls, app):
        self = cls(app)

    def shutdown(self):
        pass
