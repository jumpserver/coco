# -*- coding: utf-8 -*-
#

import os
import json
import base64
import logging
import sys

import paramiko
import requests
import time
from requests.structures import CaseInsensitiveDict
from cachetools import cached, TTLCache

from .auth import AppAccessKey, AccessKeyAuth
from .utils import sort_assets, PKey, timestamp_to_datetime_str
from .exception import RequestError, ResponseError


_USER_AGENT = 'jms-sdk-py'
CACHED_TTL = os.environ.get('CACHED_TTL', 30)
logger = logging.getLogger(__file__)

API_URL_MAPPING = {
    'terminal-register': '/api/applications/v1/terminal/',
    'terminal-heatbeat': '/api/applications/v1/terminal/heatbeat/',
    'send-proxy-log': '/api/audits/v1/proxy-log/receive/',
    'finish-proxy-log': '/api/audits/v1/proxy-log/%s/',
    'send-command-log': '/api/audits/v1/command-log/',
    'send-record-log': '/api/audits/v1/record-log/',
    'user-auth': '/api/users/v1/auth/',
    'user-assets': '/api/perms/v1/user/%s/assets/',
    'user-asset-groups': '/api/perms/v1/user/%s/asset-groups/',
    'user-asset-groups-assets': '/api/perms/v1/user/my/asset-groups-assets/',
    'assets-of-group': '/api/perms/v1/user/my/asset-group/%s/assets/',
    'my-profile': '/api/users/v1/profile/',
    'system-user-auth-info': '/api/assets/v1/system-user/%s/auth-info/',
    'validate-user-asset-permission':
        '/api/perms/v1/asset-permission/user/validate/',
}


class Request(object):
    methods = {
        'get': requests.get,
        'post': requests.post,
        'patch': requests.patch,
        'put': requests.put,
        'delete': requests.delete,
    }

    def __init__(self, url, method='get', data=None, params=None,
                 headers=None, content_type='application/json'):
        self.url = url
        self.method = method
        self.params = params or {}

        if not isinstance(headers, dict):
            headers = {}
        self.headers = CaseInsensitiveDict(headers)
        self.headers['Content-Type'] = content_type
        if data is None:
            data = {}
        self.data = json.dumps(data)

    def do(self):
        result = self.methods.get(self.method)(
            url=self.url, headers=self.headers,
            data=self.data, params=self.params)
        return result


class AppRequests(object):

    def __init__(self, endpoint, auth=None):
        self.auth = auth
        self.endpoint = endpoint

    @staticmethod
    def clean_result(resp):
        if resp.status_code >= 500:
            raise ResponseError("Response code is {0.status_code}: {0.text}".format(resp))

        try:
            _ = resp.json()
        except json.JSONDecodeError:
            raise ResponseError("Response json couldn't be decode: {0.text}".format(resp))
        else:
            return resp

    def do(self, api_name=None, pk=None, method='get', use_auth=True,
           data=None, params=None, content_type='application/json'):

        if api_name in API_URL_MAPPING:
            path = API_URL_MAPPING.get(api_name)
            if pk and '%s' in path:
                path = path % pk
        else:
            path = '/'

        url = self.endpoint.rstrip('/') + path
        req = Request(url, method=method, data=data,
                      params=params, content_type=content_type)
        if use_auth:
            if not self.auth:
                raise RequestError('Authentication required')
            else:
                self.auth.sign_request(req)

        try:
            resp = req.do()
        except (requests.ConnectionError, requests.ConnectTimeout) as e:
            raise RequestError("Connect endpoint {} error: {}".format(self.endpoint, e))

        return self.clean_result(resp)

    def get(self, *args, **kwargs):
        kwargs['method'] = 'get'
        return self.do(*args, **kwargs)

    def post(self, *args, **kwargs):
        kwargs['method'] = 'post'
        return self.do(*args, **kwargs)

    def put(self, *args, **kwargs):
        kwargs['method'] = 'put'
        return self.do(*args, **kwargs)

    def patch(self, *args, **kwargs):
        kwargs['method'] = 'patch'
        return self.do(*args, **kwargs)


class AppService:
    access_key_class = AppAccessKey

    def __init__(self, app):
        self.app = app
        self.access_key = None
        self.requests = AppRequests(app.config['CORE_HOST'])

    def initial(self):
        self.load_access_key()
        self.set_auth()
        self.valid_auth()

    def load_access_key(self):
        # Must be get access key if not register it
        self.access_key = self.access_key_class()
        self.access_key.set_app(self.app)
        self.access_key = self.access_key.load()
        if self.access_key is None:
            logger.info("No access key found, register it")
            self.register_and_save()

    def set_auth(self):
        self.requests.auth = AccessKeyAuth(self.access_key)

    def valid_auth(self):
        delay = 1
        while delay < 300:
            if self.heatbeat() is None:
                msg = "Access key is not valid or need admin " \
                      "accepted, waiting %d s" % delay
                logger.info(msg)
                delay += 3
                time.sleep(3)
            else:
                break
        if delay >= 300:
            logger.info("Start timeout")
            sys.exit()

    def register_and_save(self):
        self.register()
        self.save_access_key()

    def save_access_key(self):
        self.access_key.save_to_file()

    def register(self):
        try:
            resp = self.requests.post(
                'terminal-register', data={'name': self.app.name}, use_auth=False
            )
        except (RequestError, ResponseError) as e:
            logger.error(e)
            return

        if resp.status_code == 201:
            access_key = resp.json()['access_key']
            access_key_id = access_key['id']
            access_key_secret = access_key['secret']
            self.access_key = self.access_key_class(
                id=access_key_id, secret=access_key_secret
            )
            self.access_key.set_app(self.app)
            logger.info('Register app success: %s' % access_key_id,)
        elif resp.status_code == 409:
            msg = '{} exist already, register failed'.format(self.app.name)
            logging.error(msg)
            sys.exit()
        else:
            logging.error('Register terminal {} failed unknown: {}'.format(self.app.name, resp.json()))
            sys.exit()

    def heatbeat(self):
        """和Jumpserver维持心跳, 当Terminal断线后,jumpserver可以知晓

        Todo: Jumpserver发送的任务也随heatbeat返回, 并执行,如 断开某用户
        """
        try:
            resp = self.requests.post('terminal-heatbeat', use_auth=True)
        except (ResponseError, RequestError):
            return None

        if resp.status_code == 201:
            return True
        else:
            return None

    def validate_user_asset_permission(self, user_id, asset_id, system_user_id):
        """验证用户是否有登录该资产的权限"""
        params = {
            'user_id': user_id,
            'asset_id': asset_id,
            'system_user_id': system_user_id,
        }
        r, content = self.requests.get(
            'validate-user-asset-permission', use_auth=True, params=params
        )
        if r.status_code == 200:
            return True
        else:
            return False

    def get_system_user_auth_info(self, system_user):
        """获取系统用户的认证信息: 密码, ssh私钥"""
        r, content = self.requests.get('system-user-auth-info', pk=system_user['id'])
        if r.status_code == 200:
            password = content['password'] or ''
            private_key_string = content['private_key'] or ''

            if private_key_string and private_key_string.find('PRIVATE KEY'):
                private_key = PKey.from_string(private_key_string)
            else:
                private_key = None

            if isinstance(private_key, paramiko.PKey) \
                    and len(private_key_string.split('\n')) > 2:
                private_key_log_msg = private_key_string.split('\n')[1]
            else:
                private_key_log_msg = 'None'

            logging.debug('Get system user %s password: %s*** key: %s***' %
                          (system_user['username'], password[:4],
                           private_key_log_msg))
            return password, private_key
        else:
            logging.warning('Get system user %s password or private key failed'
                            % system_user['username'])
            return None, None

    def send_proxy_log(self, data):
        """
        :param data: 格式如下
        data = {
            "user": "username",
            "asset": "name",
            "system_user": "web",
            "login_type": "ST",
            "was_failed": 0,
            "date_start": timestamp,
        }
        """
        assert isinstance(data.get('date_start'), (int, float))
        data['date_start'] = timestamp_to_datetime_str(data['date_start'])
        data['is_failed'] = 1 if data.get('is_failed') else 0

        r, content = self.requests.post('send-proxy-log', data=data, use_auth=True)
        if r.status_code != 201:
            logging.warning('Send proxy log failed: %s' % content)
            return None
        else:
            return content['id']

    def finish_proxy_log(self, data):
        """ 退出登录资产后, 需要汇报结束 时间等

        :param data: 格式如下
        data = {
            "proxy_log_id": 123123,
            "date_finished": timestamp,
        }
        """
        assert isinstance(data.get('date_finished'), (int, float))
        data['date_finished'] = timestamp_to_datetime_str(data['date_finished'])
        data['is_failed'] = 1 if data.get('is_failed') else 0
        data['is_finished'] = 1
        proxy_log_id = data.get('proxy_log_id') or 0
        r, content = self.requests.patch('finish-proxy-log', pk=proxy_log_id, data=data)

        if r.status_code != 200:
            logging.warning('Finish proxy log failed: %s' % proxy_log_id)
            return False
        return True

    def send_command_log(self, data):
        """用户输入命令后发送到Jumpserver保存审计
        :param data: 格式如下
        data = [{
            "proxy_log_id": 22,
            "user": "admin",
            "asset": "localhost",
            "system_user": "web",
            "command_no": 1,
            "command": "ls",
            "output": cmd_output, ## base64.b64encode(output),
            "timestamp": timestamp,
        },..]
        """
        assert isinstance(data, (dict, list))
        if isinstance(data, dict):
            data = [data]

        for d in data:
            if not d.get('output'):
                continue
            output = d['output'].encode('utf-8', 'ignore')
            d['output'] = base64.b64encode(output).decode("utf-8")

        result, content = self.requests.post('send-command-log', data=data)
        if result.status_code != 201:
            logging.warning('Send command log failed: %s' % content)
            return False
        return True

    def send_record_log(self, data):
        """将输入输出发送给Jumpserver, 用来录像回放
        :param data: 格式如下
        data = [{
            "proxy_log_id": 22,
            "output": "backend server output, either input or output",
            "timestamp": timestamp,
        }, ...]
        """
        assert isinstance(data, (dict, list))
        if isinstance(data, dict):
            data = [data]
        for d in data:
            if d.get('output') and isinstance(d['output'], str):
                d['output'] = d['output'].encode('utf-8')
            d['output'] = base64.b64encode(d['output'])
        result, content = self.requests.post('send-record-log', data=data)
        if result.status_code != 201:
            logging.warning('Send record log failed: %s' % content)
            return False
        return True

    # Todo: 或许没什么用
    # def check_user_authentication(self, token=None, session_id=None,
    #                               csrf_token=None):
    #     """
    #     用户登陆webterminal或其它网站时,检测用户cookie中的sessionid和csrf_token
    #     是否合法, 如果合法返回用户,否则返回空
    #     :param session_id: cookie中的 sessionid
    #     :param csrf_token: cookie中的 csrftoken
    #     :return: user object or None
    #     """
    #     user_service = UserService(endpoint=self.endpoint)
    #     user_service.auth(token=token, session_id=session_id,
    #                       csrf_token=csrf_token)
    #     user = user_service.is_authenticated()
    #     return user

    @cached(TTLCache(maxsize=100, ttl=60))
    def get_user_assets(self, user):
        """获取用户被授权的资产列表
        [{'hostname': 'x', 'ip': 'x', ...,
         'system_users_granted': [{'id': 1, 'username': 'x',..}]
        ]
        """
        r, content = self.requests.get('user-assets', pk=user['id'], use_auth=True)
        if r.status_code == 200:
            assets = content
        else:
            assets = []

        assets = sort_assets(assets)
        for asset in assets:
            asset['system_users'] = \
                [system_user for system_user in asset.get('system_users_granted')]
        return to_dotmap(assets)

    @cached(TTLCache(maxsize=100, ttl=60))
    def get_user_asset_groups(self, user):
        """获取用户授权的资产组列表
        [{'name': 'x', 'comment': 'x', 'assets_amount': 2}, ..]
        """
        r, content = self.requests.get('user-asset-groups', pk=user['id'], uassetsse_auth=True)
        if r.status_code == 200:
            asset_groups = content
        else:
            asset_groups = []
        asset_groups = [asset_group for asset_group in asset_groups]
        return to_dotmap(asset_groups)

    @cached(TTLCache(maxsize=100, ttl=60))
    def get_user_asset_groups_assets(self, user):
        """获取用户授权的资产组列表及下面的资产
        [{'name': 'x', 'comment': 'x', 'assets': []}, ..]
        """
        r, content = self.requests.get('user-asset-groups-assets', pk=user['id'], use_auth=True)
        if r.status_code == 200:
            asset_groups_assets = content
        else:
            asset_groups_assets = []
        return to_dotmap(asset_groups_assets)

    @cached(TTLCache(maxsize=100, ttl=60))
    def get_assets_in_group(self, asset_group_id):
        """获取用户在该资产组下的资产, 并非该资产组下的所有资产,而是授权了的
        返回资产列表, 和获取资产格式一致

        :param asset_group_id: 资产组id
        """
        r, content = self.requests.get('assets-of-group', use_auth=True,
                              pk=asset_group_id)
        if r.status_code == 200:
            assets = content
        else:
            assets = []

        for asset in assets:
            asset['system_users'] = \
                [system_user for system_user in asset.get('system_users_granted')]

        assets = sort_assets(assets)
        return to_dotmap([asset for asset in assets])
