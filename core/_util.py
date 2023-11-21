# -*- coding: utf-8 -*-
""""""

from __future__ import (absolute_import, division, print_function)

import re
from fnmatch import fnmatch
from glance.core.compat import string_types


def popdefault(l, index=-1, default=None):
    """Try to pop and return an element from a list. If the element does not exist or
    has a False-y value, return a default value."""
    try:
        part = l.pop(index)
        if part:
            return part
        else:
            return default
    except IndexError:
        return default


def title_fnmatch(s, pattern):
    try:
        return fnmatch(s.lower(), pattern.lower())
    except AttributeError:
        return True


def title_re_match(s, pattern):
    if isinstance(s, string_types) and isinstance(pattern, string_types):
        return re.search(pattern, s) is not None
    else:
        return True


def find_in_report(rep, pattern, default_pattern, match_func):
    parts = pattern.split('/')
    secpat = popdefault(parts, 0, default_pattern)
    blkpat = popdefault(parts, 0, default_pattern)
    respat = popdefault(parts, 0, default_pattern)
    results = []
    for sec in rep:
        if match_func(sec.title, secpat):
            for blk in sec:
                if match_func(blk.title, blkpat):
                    for res in blk:
                        if match_func(res.title, respat):
                            results.append(res)
    return results
