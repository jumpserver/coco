#!coding: utf-8

import logging
import paramiko
import threading


logger = logging.getLogger(__file__)


class SSHInterface(paramiko.ServerInterface):
    """
    使用paramiko提供的接口实现ssh server.

    More see paramiko ssh server demo
    https://github.com/paramiko/paramiko/blob/master/demos/demo_server.py
    """

    def __init__(self, app, request):
        self.app = app
        self.request = request
        self.event = threading.Event()

    def check_auth_interactive(self, username, submethods):
        """
        :param username:  the username of the authenticating client
        :param submethods: a comma-separated list of methods preferred
                           by the client (usually empty)
        :return: AUTH_FAILED if this auth method isn’t supported;
                 otherwise an object containing queries for the user
        """
        logger.info("Check auth interactive: %s %s" % (username, submethods))
        return paramiko.AUTH_FAILED

    def check_auth_interactive_response(self, responses):
        logger.info("Check auth interactive response: %s " % responses)
        # TODO：MFA Auth
        pass

    def enable_auth_gssapi(self):
        return False

    def get_allowed_auths(self, username):
        # Todo: Check with server settings or self config
        return ",".join(["password", "publickkey"])

    def check_auth_none(self, username):
        return paramiko.AUTH_FAILED

    def check_auth_password(self, username, password):
        return self.validate_auth(username, password=password)

    def check_auth_publickey(self, username, key):
        return self.validate_auth(username, key=key)

    def validate_auth(self, username, password="", key=""):
        # Todo: Implement it
        self.request.user = "guang"
        return True

    def check_channel_direct_tcpip_request(self, chanid, origin, destination):
        logger.debug("Check channel direct tcpip request: %d %s %s" %
                    (chanid, origin, destination))
        self.request.type = 'direct-tcpip'
        self.request.meta = {
            'chanid': chanid, 'origin': origin,
            'destination': destination,
        }
        self.event.set()
        return 0

    def check_channel_env_request(self, channel, name, value):
        logger.debug("Check channel env request: %s, %s, %s" %
                     (channel, name, value))
        return False

    def check_channel_exec_request(self, channel, command):
        logger.debug("Check channel exec request: %s `%s`" %
                     (channel, command))
        self.request.type = 'exec'
        self.request.meta = {'channel': channel, 'command': command}
        self.event.set()
        return False

    def check_channel_forward_agent_request(self, channel):
        logger.debug("Check channel forward agent request: %s" % channel)
        self.request.type = "forward-agent"
        self.request.meta = {'channel': channel}
        self.event.set()
        return False

    def check_channel_pty_request(
            self, channel, term, width, height,
            pixelwidth, pixelheight, modes):
        logger.debug("Check channel pty request: %s %s %s %s %s %s" %
                    (channel, term, width, height, pixelwidth, pixelheight))
        self.request.type = 'pty'
        self.request.meta = {
            'channel': channel, 'term': term, 'width': width,
            'height': height, 'pixelwidth': pixelwidth,
            'pixelheight': pixelheight, 'models': modes,
        }
        self.event.set()
        return True

    def check_channel_request(self, kind, chanid):
        logger.info("Check channel request: %s %d" % (kind, chanid))
        return paramiko.OPEN_SUCCEEDED

    def check_channel_shell_request(self, channel):
        logger.info("Check channel shell request: %s" % channel)
        return True

    def check_channel_subsystem_request(self, channel, name):
        logger.info("Check channel subsystem request: %s %s" % (channel, name))
        self.request.type = 'subsystem'
        self.request.meta = {'channel': channel, 'name': name}
        self.event.set()
        return False

    def check_channel_window_change_request(self, channel, width, height,
                                            pixelwidth, pixelheight):
        self.request.meta['width'] = width
        self.request.meta['height'] = height
        self.request.meta['pixelwidth'] = pixelwidth
        self.request.meta['pixelheight'] = pixelheight
        self.request.change_size_event.set()
        return True

    def check_channel_x11_request(self, channel, single_connection,
                                  auth_protocol, auth_cookie, screen_number):
        logger.info("Check channel x11 request %s %s %s %s %s" %
                    (channel, single_connection, auth_protocol,
                     auth_cookie, screen_number))
        self.request.type = 'x11'
        self.request.meta = {
            'channel': channel, 'single_connection': single_connection,
            'auth_protocol': auth_protocol, 'auth_cookie': auth_cookie,
            'screen_number': screen_number,
        }
        self.event.set()
        return False

    def check_port_forward_request(self, address, port):
        logger.info("Check channel port forward request: %s %s" % (address, port))
        self.request.type = 'port-forward'
        self.request.meta = {'address': address, 'port': port}
        self.event.set()
        return False

    def get_banner(self):
        return None, None















