#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#

import paramiko
import threading

from .utils import get_logger
from .ctx import current_app, app_service

logger = get_logger(__file__)


class SSHInterface(paramiko.ServerInterface):
    """
    使用paramiko提供的接口实现ssh server.

    More see paramiko ssh server demo
    https://github.com/paramiko/paramiko/blob/master/demos/demo_server.py
    """

    def __init__(self, request):
        self.request = request
        self.event = threading.Event()
        self.auth_valid = False
        self.otp_auth = False
        self.info = None

    def check_auth_interactive(self, username, submethods):
        logger.info("Check auth interactive: %s %s" % (username, submethods))
        instructions = 'Please enter 6 digits.'
        interactive = paramiko.server.InteractiveQuery(instructions=instructions)
        interactive.add_prompt(prompt='[MFA auth]: ')
        return interactive

    def check_auth_interactive_response(self, responses):
        logger.info("Check auth interactive response: %s " % responses)
        # TODO：MFA Auth
        otp_code = responses[0]
        if not otp_code or not len(otp_code) == 6 or not otp_code.isdigit():
            return paramiko.AUTH_FAILED
        return self.check_auth_otp(otp_code)

    def check_auth_otp(self, otp_code):
        seed = self.info.get('seed', '')
        if not seed:
            return paramiko.AUTH_FAILED

        is_valid = app_service.authenticate_otp(seed, otp_code)
        if is_valid:
            return paramiko.AUTH_SUCCESSFUL
        return paramiko.AUTH_FAILED

    def enable_auth_gssapi(self):
        return False

    def get_allowed_auths(self, username):
        supported = []
        if self.otp_auth:
            return 'keyboard-interactive'
        if current_app.config["PASSWORD_AUTH"]:
            supported.append("password")
        if current_app.config["PUBLIC_KEY_AUTH"]:
            supported.append("publickey")
        return ",".join(supported)

    def check_auth_none(self, username):
        return paramiko.AUTH_FAILED

    def check_auth_password(self, username, password):
        user = self.validate_auth(username, password=password)
        if not user:
            logger.warning("Password and public key auth <%s> failed, reject it" % username)
            return paramiko.AUTH_FAILED
        else:
            logger.info("Password auth <%s> success" % username)
            if self.otp_auth:
                return paramiko.AUTH_PARTIALLY_SUCCESSFUL
            return paramiko.AUTH_SUCCESSFUL

    def check_auth_publickey(self, username, key):
        key = key.get_base64()
        user = self.validate_auth(username, public_key=key)
        if not user:
            logger.debug("Public key auth <%s> failed, try to password" % username)
            return paramiko.AUTH_FAILED
        else:
            logger.debug("Public key auth <%s> success" % username)
            if self.otp_auth:
                return paramiko.AUTH_PARTIALLY_SUCCESSFUL
            return paramiko.AUTH_SUCCESSFUL

    def validate_auth(self, username, password="", public_key=""):
        info = app_service.authenticate(
            username, password=password, public_key=public_key,
            remote_addr=self.request.remote_ip
        )
        user = info.get('user', None)
        if user:
            self.request.user = user
            self.info = info

        seed = info.get('seed', None)
        token = info.get('token', None)
        if seed and not token:
            self.otp_auth = True
        return user

    def check_channel_direct_tcpip_request(self, chanid, origin, destination):
        logger.debug("Check channel direct tcpip request: %d %s %s" %
                     (chanid, origin, destination))
        self.request.type.append('direct-tcpip')
        self.request.meta.update({
            'chanid': chanid, 'origin': origin,
            'destination': destination,
        })
        self.event.set()
        return 0

    def check_channel_env_request(self, channel, name, value):
        logger.debug("Check channel env request: %s, %s, %s" %
                     (channel, name, value))
        self.request.type.append('env')
        return False

    def check_channel_exec_request(self, channel, command):
        logger.debug("Check channel exec request:  `%s`" % command)
        self.request.type.append('exec')
        self.request.meta.update({'channel': channel.get_id(), 'command': command})
        self.event.set()
        return False

    def check_channel_forward_agent_request(self, channel):
        logger.debug("Check channel forward agent request: %s" % channel)
        self.request.type.append("forward-agent")
        self.request.meta.update({'channel': channel.get_id()})
        self.event.set()
        return False

    def check_channel_pty_request(
            self, channel, term, width, height,
            pixelwidth, pixelheight, modes):
        logger.info("Check channel pty request: %s %s %s %s %s" %
                     (term, width, height, pixelwidth, pixelheight))
        self.request.type.append('pty')
        self.request.meta.update({
            'channel': channel, 'term': term, 'width': width,
            'height': height, 'pixelwidth': pixelwidth,
            'pixelheight': pixelheight,
        })
        self.event.set()
        return True

    def check_channel_request(self, kind, chanid):
        logger.info("Check channel request: %s %d" % (kind, chanid))
        return paramiko.OPEN_SUCCEEDED

    def check_channel_shell_request(self, channel):
        logger.info("Check channel shell request: %s" % channel.get_id())
        self.event.set()
        return True

    def check_channel_subsystem_request(self, channel, name):
        logger.info("Check channel subsystem request: %s %s" % (channel, name))
        self.request.type.append('subsystem')
        self.request.meta.update({'channel': channel.get_id(), 'name': name})
        self.event.set()
        return super().check_channel_subsystem_request(channel, name)

    def check_channel_window_change_request(self, channel, width, height,
                                            pixelwidth, pixelheight):
        self.request.meta.update({
            'width': width,
            'height': height,
            'pixelwidth': pixelwidth,
            'pixelheight': pixelheight,
        })
        self.request.change_size_event.set()
        return True

    def check_channel_x11_request(self, channel, single_connection,
                                  auth_protocol, auth_cookie, screen_number):
        logger.info("Check channel x11 request %s %s %s %s %s" %
                    (channel, single_connection, auth_protocol,
                     auth_cookie, screen_number))
        self.request.type.append('x11')
        self.request.meta.update({
            'channel': channel.get_id(), 'single_connection': single_connection,
            'auth_protocol': auth_protocol, 'auth_cookie': auth_cookie,
            'screen_number': screen_number,
        })
        self.event.set()
        return False

    def check_port_forward_request(self, address, port):
        logger.info("Check channel port forward request: %s %s" % (address, port))
        self.request.type.append('port-forward')
        self.request.meta.update({'address': address, 'port': port})
        self.event.set()
        return False

    def get_banner(self):
        return None, None

    # def __del__(self):
    #     print("GC: SSH interface gc")


