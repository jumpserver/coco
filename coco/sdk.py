# -*- coding: utf-8 -*-
#

import os
import json
import base64
import logging

import paramiko
import requests
from requests.structures import CaseInsensitiveDict
from cachetools import cached, TTLCache

from .auth import Auth, ServiceAccessKey
from .utils import sort_assets, PKey, to_dotmap, timestamp_to_datetime_str
from .exception import RequestError, LoadAccessKeyError
from .config import API_URL_MAPPING


_USER_AGENT = 'jms-sdk-py'
CACHED_TTL = os.environ.get('CACHED_TTL', 30)


class FakeResponse(object):
    def __init__(self):
        self.status_code = 500

    @staticmethod
    def json():
        return {}


class Request(object):
    func_mapping = {
        'get': requests.get,
        'post': requests.post,
        'patch': requests.patch,
        'put': requests.put,
    }

    def __init__(self, url, method='get', data=None, params=None, headers=None,
                 content_type='application/json', app_name=''):
        self.url = url
        self.method = method
        self.params = params or {}
        self.result = None

        if not isinstance(headers, dict):
            headers = {}
        self.headers = CaseInsensitiveDict(headers)

        self.headers['Content-Type'] = content_type
        if data is None:
            data = {}
        self.data = json.dumps(data)

        if 'User-Agent' not in self.headers:
            if app_name:
                self.headers['User-Agent'] = _USER_AGENT + '/' + app_name
            else:
                self.headers['User-Agent'] = _USER_AGENT

    def request(self):
        self.result = self.func_mapping.get(self.method)(
            url=self.url, headers=self.headers,
            data=self.data,
            params=self.params)
        print(self.headers)
        return self.result


class ApiRequest(object):
    api_url_mapping = API_URL_MAPPING

    def __init__(self, app_name, endpoint, auth=None):
        self.app_name = app_name
        self._auth = auth
        self.req = None
        self.endpoint = endpoint

    @staticmethod
    def parse_result(result):
        try:
            content = result.json()
        except ValueError:
            content = {'error': 'We only support json response'}
            logging.warning(result.content)
            logging.warning(content)
        except AttributeError:
            content = {'error': 'Request error'}
        return result, content

    def request(self, api_name=None, pk=None, method='get', use_auth=True,
                data=None, params=None, content_type='application/json'):

        if api_name in self.api_url_mapping:
            path = self.api_url_mapping.get(api_name)
            if pk and '%s' in path:
                path = path % pk
        else:
            path = '/'

        url = self.endpoint.rstrip('/') + path
        print(url)
        self.req = req = Request(url, method=method, data=data,
                                 params=params, content_type=content_type,
                                 app_name=self.app_name)
        if use_auth:
            if not self._auth:
                raise RequestError('Authentication required')
            else:
                self._auth.sign_request(req)
        try:
            result = req.request()
            if result.status_code > 500:
                logging.warning('Server internal error')
        except (requests.ConnectionError, requests.ConnectTimeout):
            result = FakeResponse()
            logging.warning('Connect endpoint: {} error'.format(self.endpoint))
        return self.parse_result(result)

    def get(self, *args, **kwargs):
        kwargs['method'] = 'get'
        print("+"* 10)
        print(*args)
        print("+"* 10)
        # print(**kwargs)
        print("+"* 10)

        return self.request(*args, **kwargs)

    def post(self, *args, **kwargs):
        kwargs['method'] = 'post'
        return self.request(*args, **kwargs)

    def put(self, *args, **kwargs):
        kwargs['method'] = 'put'
        return self.request(*args, **kwargs)

    def patch(self, *args, **kwargs):
        kwargs['method'] = 'patch'
        return self.request(*args, **kwargs)


class AppService(ApiRequest):
    """使用该类和Jumpserver api进行通信,将terminal用到的常用api进行了封装,
    直接调用方法即可.
        from jms import AppService

        service = AppService(app_name='coco', endpoint='http://localhost:8080')

        # 如果app是第一次启动, 注册一下,并得到 access key, 然后认真
        service.register()
        service.auth()  # 直接使用注册得到的access key进行认证

        # 如果已经启动过, 需要使用access key进行认证
        service.auth(access_key_id, access_key_secret)

        service.check_auth()  # 检测一下是否认证有效
        data = {
            "username": "ibuler",
            "name": "Guanghongwei",
            "hostname": "localhost",
            "ip": "127.0.0.1",
            "system_user": "web",
            "login_type": "ST",
            "is_failed": 0,
            "date_start": 1484206685,
        }
        service.send_proxy_log(data)

    """
    access_key_class = ServiceAccessKey

    def __init__(self, app_name, endpoint, auth=None, config=None):
        super(AppService, self).__init__(app_name, endpoint, auth=auth)
        self.config = config
        self.access_key = self.access_key_class(config=config)
        self.user = None
        self.token = None
        self.session_id = None
        self.csrf_token = None

    def auth(self, access_key_id=None, access_key_secret=None):
        """App认证, 请求api需要签名header
        :param access_key_id: 注册时或新建app用户生成access key id
        :param access_key_secret: 同上access key secret
        """
        if None not in (access_key_id, access_key_secret):
            self.access_key.id = access_key_id
            self.access_key.secret = access_key_secret

        self._auth = Auth(access_key_id=self.access_key.id,
                          access_key_secret=self.access_key.secret)

    def auth_magic(self):
        """加载配置文件定义的变量,尝试从配置文件, Keystore, 环境变量加载
        Access Key 然后进行认证
        """
        self.access_key = self.access_key_class(config=self.config)
        self.access_key.load_from_conf_all()
        if self.access_key:
            self._auth = Auth(access_key_id=self.access_key.id,
                              access_key_secret=self.access_key.secret)
        else:
            raise LoadAccessKeyError('Load access key all failed, auth ignore')

    def register_terminal(self):
        """注册Terminal, 通常第一次启动需要向Jumpserver注册

        content: {
            'terminal': {'id': 1, 'name': 'terminal name', ...},
            'user': {
                        'username': 'same as terminal name',
                        'name': 'same as username',
                    },
            'access_key_id': 'ACCESS KEY ID',
            'access_key_secret': 'ACCESS KEY SECRET',
        }
        """
        r, content = self.post('terminal-register',
                               data={'name': self.app_name},
                               use_auth=False)
        if r.status_code == 201:
            logging.info('Your can save access_key: %s somewhere '
                         'or set it in config' % content['access_key_id'])
            return True, to_dotmap(content)
        elif r.status_code == 200:
            logging.error('Terminal {} exist already, register failed'
                          .format(self.app_name))
        else:
            logging.error('Register terminal {} failed'.format(self.app_name))
        return False, None

    def terminal_heatbeat(self):
        """和Jumpserver维持心跳, 当Terminal断线后,jumpserver可以知晓

        Todo: Jumpserver发送的任务也随heatbeat返回, 并执行,如 断开某用户
        """
        r, content = self.post('terminal-heatbeat', use_auth=True)
        if r.status_code == 201:
            return content
        else:
            return None

    def is_authenticated(self):
        """执行auth后只是构造了请求头, 可以使用该方法连接Jumpserver测试认证"""
        result = self.terminal_heatbeat()
        return result

    def validate_user_asset_permission(self, user_id, asset_id, system_user_id):
        """验证用户是否有登录该资产的权限"""
        params = {
            'user_id': user_id,
            'asset_id': asset_id,
            'system_user_id': system_user_id,
        }
        r, content = self.get('validate-user-asset-permission',
                              use_auth=True,
                              params=params)
        if r.status_code == 200:
            return True
        else:
            return False

    def get_system_user_auth_info(self, system_user):
        """获取系统用户的认证信息: 密码, ssh私钥"""
        r, content = self.get('system-user-auth-info', pk=system_user['id'])
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

        r, content = self.post('send-proxy-log', data=data, use_auth=True)
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
        r, content = self.patch('finish-proxy-log', pk=proxy_log_id, data=data)

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

        result, content = self.post('send-command-log', data=data)
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
        result, content = self.post('send-record-log', data=data)
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


    def login(self, data):
        """用户登录Terminal时需要向Jumpserver进行认证, 登陆成功后返回用户和token
        data = {
            'username': 'admin',
            'password': 'admin',
            'public_key': 'public key string',
            'login_type': 'ST',  # (('ST', 'SSH Terminal'),
                                 #  ('WT', 'Web Terminal'))
            'remote_addr': '2.2.2.2',  # User ip address not app address
        }
        """
        r, content = self.post('user-auth', data=data, use_auth=False)
        if r.status_code == 200:
            self.token = content['token']
            self.user = content['user']
            self.auth(self.token)
            return self.user,  self.token
        else:
            return None, None

    @cached(TTLCache(maxsize=100, ttl=60))
    def get_user_assets(self, user):
        """获取用户被授权的资产列表
        [{'hostname': 'x', 'ip': 'x', ...,
         'system_users_granted': [{'id': 1, 'username': 'x',..}]
        ]
        """
        r, content = self.get('user-assets', pk=user['id'], use_auth=True)
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
        r, content = self.get('user-asset-groups', pk=user['id'], uassetsse_auth=True)
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
        r, content = self.get('user-asset-groups-assets', pk=user['id'], use_auth=True)
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
        r, content = self.get('assets-of-group', use_auth=True,
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
