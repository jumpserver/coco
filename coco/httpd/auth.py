# -*- coding: utf-8 -*-
#
from functools import wraps

from flask import request, abort, redirect

from ..ctx import app_service


def login_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        session_id = request.cookies.get('sessionid', '')
        csrf_token = request.cookies.get('csrftoken', '')
        x_forwarded_for = request.headers.get("X-Forwarded-For", '').split(',')
        if x_forwarded_for and x_forwarded_for[0]:
            remote_ip = x_forwarded_for[0]
        else:
            remote_ip = request.remote_addr
        request.real_ip = remote_ip

        if session_id and csrf_token:
            user = app_service.check_user_cookie(session_id, csrf_token)
            request.current_user = user
        if not hasattr(request, 'current_user') or not request.current_user:
            url = '/users/login/?next={}'.format(request.path)
            return redirect(url)
        response = func(*args, **kwargs)
        return response
    return wrapper
