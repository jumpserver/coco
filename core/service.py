# ~*~ coding: utf-8 ~*~

from jms import AppService
from jms.exceptions import LoadAccessKeyError
from .conf import config

name = config.get('NAME')
endpoint = config.get('JUMPSERVER_ENDPOINT')


app_service = AppService(app_name=name, endpoint=endpoint)

app_service.access_key.load_from_config(config, 'ACCESS_KEY')



