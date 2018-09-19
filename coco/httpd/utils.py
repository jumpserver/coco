# -*- coding: utf-8 -*-
#

__sftp_cached = {}


def get_cached_sftp(sid):
    return __sftp_cached.get(sid)


def set_cache_sftp(sid, volume):
    __sftp_cached[sid] = volume
