#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#

import os

BASE_DIR = os.path.dirname(__file__)


class Config:
    """
    Coco config file, coco also load config from server update setting below
    """
    # 项目名称, 会用来向Jumpserver注册, 识别而已, 不能重复
    NAME = os.environ.get("NAME") or "coco"

    # Jumpserver项目的url, api请求注册会使用
    CORE_HOST = os.environ.get("CORE_HOST") or 'http://core:8080'

    # Bootstrap Token, 预共享秘钥, 用来注册coco使用的service account和terminal
    # 请和jumpserver 配置文件中保持一致，注册完成后可以删除
    BOOTSTRAP_TOKEN = os.environ.get("BOOTSTRAP_TOKEN") or "PleaseChangeMe"

    # 启动时绑定的ip, 默认 0.0.0.0
    BIND_HOST = '0.0.0.0'

    # 监听的SSH端口号, 默认2222
    SSHD_PORT = 2222

    # 监听的HTTP/WS端口号，默认5000
    HTTPD_PORT = 5000

    # 项目使用的ACCESS KEY, 默认会注册,并保存到 ACCESS_KEY_STORE中,
    # 如果有需求, 可以写到配置文件中, 格式 access_key_id:access_key_secret
    ACCESS_KEY = os.environ.get("ACCESS_KEY") or None

    # ACCESS KEY 保存的地址, 默认注册后会保存到该文件中
    # ACCESS_KEY_STORE = os.path.join(BASE_DIR, 'keys', '.access_key')

    # 加密密钥
    SECRET_KEY = os.environ.get("SECRET_KEY") or 'SKdfm239LSKdfj())_23jK*^2'

    # 设置日志级别 ['DEBUG', 'INFO', 'WARN', 'ERROR', 'FATAL', 'CRITICAL']
    LOG_LEVEL = os.environ.get("LOG_LEVEL") or 'DEBUG'

    # 日志存放的目录
    LOG_DIR = os.environ.get("LOG_DIR") or os.path.join(BASE_DIR, 'logs')

    # Session录像存放目录
    SESSION_DIR = os.environ.get("SESSION_DIR") or os.path.join(BASE_DIR, 'sessions')

    # 资产显示排序方式, ['ip', 'hostname']
    ASSET_LIST_SORT_BY = os.environ.get("SESSION_DIR") or 'ip'

    # 登录是否支持密码认证
    PASSWORD_AUTH = bool(os.environ.get("PASSWORD_AUTH")) if os.environ.get("PASSWORD_AUTH") else True

    # 登录是否支持秘钥认证
    PUBLIC_KEY_AUTH = bool(os.environ.get("PUBLIC_KEY_AUTH")) if os.environ.get("PUBLIC_KEY_AUTH") else True

    # SSH白名单
    ALLOW_SSH_USER = os.environ.get("ALLOW_SSH_USER").split(",") if os.environ.get("ALLOW_SSH_USER") else None  # ['test', 'test2']

    # SSH黑名单, 如果用户同时在白名单和黑名单，黑名单优先生效
    BLOCK_SSH_USER = os.environ.get("BLOCK_SSH_USER").split(",") if os.environ.get("BLOCK_SSH_USER") else []

    # 和Jumpserver 保持心跳时间间隔
    HEARTBEAT_INTERVAL = int(os.environ.get("HEARTBEAT_INTERVAL")) if os.environ.get("HEARTBEAT_INTERVAL") else 5

    # Admin的名字，出问题会提示给用户
    ADMINS = os.environ.get("ADMINS") or ''

    COMMAND_STORAGE = {
        "TYPE": "server"
    }
    REPLAY_STORAGE = {
        "TYPE": "server"
    }

    # SSH连接超时时间 (default 15 seconds)
    SSH_TIMEOUT = 15

    # 语言 = en
    LANGUAGE_CODE = 'zh'

class ConfigDocker(Config):
    pass


config = ConfigDocker()