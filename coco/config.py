#!/usr/bin/env python
# -*- coding: utf-8 -*-
#


class Config(dict):
    def __init__(self, defaults=None):
        super(Config, self).__init__(defaults or {})

    def from_object(self, obj):
        for key in dir(obj):
            if key.isupper():
                self[key] = getattr(obj, key)

    def __getattr__(self, item):
        return self.__getitem__(item)