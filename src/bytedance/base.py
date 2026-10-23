# -*- coding: utf-8 -*-
"""Shared errors and backwards compatible dictionary attribute access."""
__all__ = ("Map", "ByteDanceError")


class ByteDanceError(Exception):
    def __init__(self, msg, code=None, log_id=None, response=None,
                 status_code=None, payload=None):
        super(ByteDanceError, self).__init__(msg)
        self.code = code
        self.log_id = log_id
        self.response = response
        self.status_code = status_code
        self.payload = payload


class Map(dict):
    """Dictionary with dot access, including dictionaries nested in lists.

    Missing item/attribute access retains the historical empty-Map behavior.
    Use .get() or membership tests when inspecting optional protocol fields.
    Standard dict methods take precedence over same-named JSON attributes.
    """
    def __init__(self, *args, **kwargs):
        super(Map, self).__init__()
        self.update(*args, **kwargs)

    @staticmethod
    def _convert(value):
        if isinstance(value, dict) and not isinstance(value, Map):
            return Map(value)
        if isinstance(value, list):
            return [Map._convert(item) for item in value]
        return value

    def __missing__(self, key):
        value = Map()
        self[key] = value
        return value

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return self[name]

    def __setattr__(self, name, value):
        self[name] = value

    def __delattr__(self, name):
        del self[name]

    def __setitem__(self, key, value):
        super(Map, self).__setitem__(key, self._convert(value))

    def update(self, *args, **kwargs):
        for key, value in dict(*args, **kwargs).items():
            self[key] = value

    def setdefault(self, key, default=None):
        if key not in self:
            self[key] = default
        return dict.__getitem__(self, key)
