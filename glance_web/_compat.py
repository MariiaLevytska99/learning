from __future__ import absolute_import
import sys

PY2 = sys.version_info[0] == 2
if PY2:
    text_type = unicode
    string_types = (str, unicode)
    unichr = unichr
    binary_type = str
    import cPickle as pickle
    from cStringIO import StringIO as BytesIO
    from itertools import imap
else:
    text_type = str
    string_types = (str,)
    unichr = chr
    binary_type = bytes
    import pickle
    from io import BytesIO
    imap = map
if PY2:
    def exec_(_code_, _globs_=None, _locs_=None):
        """Execute code in a namespace."""
        if _globs_ is None:
            frame = sys._getframe(1)
            _globs_ = frame.f_globals
            if _locs_ is None:
                _locs_ = frame.f_locals
            del frame
        elif _locs_ is None:
            _locs_ = _globs_
        exec ("""exec _code_ in _globs_, _locs_""")

    # this is done via exec, because the code we need for Python 2
    # causes a SyntaxError with Python 3
    exec_("""def reraise(tp, value, tb=None):
    try:
        raise tp, value, tb
    finally:
        tb = None
""")
else:
    def reraise(tp, value, tb=None):
        try:
            if value is None:
                value = tp()
            if value.__traceback__ is not tb:
                raise value.with_traceback(tb)
            raise value
        finally:
            value = None
            tb = None
