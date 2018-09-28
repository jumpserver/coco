# -*- coding: utf-8 -*-
#

__volumes_cached = {}


def get_cached_volume(sid):
    return __volumes_cached.get(sid)


def set_cache_volume(sid, volume):
    __volumes_cached[sid] = volume
