# coding: utf-8
import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

# 项目名称, 会用来向Jumpserver注册
NAME = 'coco'

# Jumpserver项目的url, api请求注册会使用
JUMPSERVER_ENDPOINT = 'http://127.0.0.1:8080'

# 启动时绑定的ip, 默认 0.0.0.0
# BIND_HOST = '0.0.0.0'

# 监听的端口号, 默认2222
LISTEN_PORT = 2222

# 是否开启DEBUG
# DEBUG = True

# 项目使用的ACCESS KEY, 默认会注册,并保存到 ACCESS_KEY_STORE中,
# 如果有需求, 可以写到配置文件中, 格式 access_key_id:access_key_secret
# ACCESS_KEY = None

# 可以设置ACCESS KEY环境变量, 如果在KEY STORE和配置中没有发现, 会从环境变量中读取
# ACCESS_KEY_ENV = 'COCO_ACCESS_KEY'

# ACCESS KEY 保存的地址, 默认注册后会保存到该文件中
# ACCESS_KEY_STORE = os.path.join(BASE_DIR, 'keys', '.access_key')

# 加密密钥
# SECRET_KEY = None

# 设置日志级别 ['DEBUG', 'INFO', 'WARN', 'ERROR', 'FATAL', 'CRITICAL']
# LOG_LEVEL = 'DEBUG'

# 日志存放的目录
# LOG_DIR = os.path.join(BASE_DIR, 'logs')

# 资产显示排序方式, ['ip', 'hostname']
# ASSET_LIST_SORT_BY = 'ip'

# 登录是否支持密码认证
# SSH_PASSWORD_AUTH = True

# 登录是否支持秘钥认证
# SSH_PUBLIC_KEY_AUTH = True

# 和Jumpserver 保持心跳时间间隔
# HEATBEAT_INTERVAL = 5

