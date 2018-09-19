# -*- coding: utf-8 -*-
#

__volume_cached = {}


def get_cache_volume(sid):
    return __volume_cached.get(sid)


def set_cache_volume(sid, volume):
    __volume_cached[sid] = volume
