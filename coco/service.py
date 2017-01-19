# ~*~ coding: utf-8 ~*~
import time
import threading

from jms import AppService
from jms.exceptions import LoadAccessKeyError
from .conf import config
from .logger import get_logger


logger = get_logger(__name__)
service = AppService(
    app_name=config.get('NAME'),
    endpoint=config.get('JUMPSERVER_ENDPOINT'),
    config=config)


def auth_it():
    try:
        service.auth_magic()
    except LoadAccessKeyError:
        is_success, content = service.register_terminal()
        if is_success:
            service.access_key.id = content.access_key_id
            service.access_key.secret = content.access_key_secret
            service.access_key.save_to_key_store()
            service.auth()
        else:
            raise SystemExit('Register terminal failed, may be'
                             'have been exist, you should look for'
                             'the terminal access key, set in config, '
                             'or put it in access key store'
                             )

    print('Using access key %s:***' % service.access_key.id)
    while True:
        if service.is_authenticated():
            logger.info('App auth passed')
            break
        else:
            logger.warn('App auth failed, Access key error '
                        'or need admin active it')
            time.sleep(5)


def keep_heatbeat():
    def _keep():
        while True:
            result = service.terminal_heatbeat()
            if not result:
                logger.warning('Terminal heatbeat failed or '
                               'Terminal need accepted by administrator')
            time.sleep(service.config['HEATBEAT_INTERVAL'])

    thread = threading.Thread(target=_keep, args=())
    thread.daemon = True
    thread.start()

auth_it()
keep_heatbeat()
