#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#

import os

BASE_DIR = os.path.dirname(__file__)


class Config:
    """
    Coco config file
    """
    # 默认的名字
    APP_NAME = os.environ.get("APP_NAME") or "localhost"

    # Jumpserver项目的url, api请求注册会使用
    CORE_HOST = os.environ.get("CORE_HOST") or 'http://core:8080'

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
    SSH_PASSWORD_AUTH = bool(os.environ.get("SSH_PASSWORD_AUTH")) if os.environ.get("SSH_PASSWORD_AUTH") else True

    # 登录是否支持秘钥认证
    SSH_PUBLIC_KEY_AUTH = bool(os.environ.get("SSH_PUBLIC_KEY_AUTH")) if os.environ.get("SSH_PUBLIC_KEY_AUTH") else True

    # 和Jumpserver 保持心跳时间间隔
    HEARTBEAT_INTERVAL = int(os.environ.get("HEARTBEAT_INTERVAL")) if os.environ.get("HEARTBEAT_INTERVAL") else 5

    # Admin的名字，出问题会提示给用户
    ADMINS = os.environ.get("ADMINS") or ''

    COMMAND_STORAGE = {
        "TYPE": "server"
    }


class ConfigDocker(Config):
    pass


config = ConfigDocker()