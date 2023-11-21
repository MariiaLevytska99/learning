# -*- coding: utf-8 -*-
""""""

from __future__ import (absolute_import, division, print_function)

import os
import socket
import logging
import warnings
from functools import wraps

import flask

log = logging.getLogger(__name__)
warnings.filterwarnings('module', module='glance.web')


def find_external_address():
    try:
        import netifaces
    except ImportError:
        log.info(
            'netifaces module not installed, unable to determine external interface')
        return None

    default_gateway = netifaces.gateways()['default']
    ext_interface = default_gateway[netifaces.AF_INET][1]
    ext_ifaddress = netifaces.ifaddresses(ext_interface)[netifaces.AF_INET][0]['addr']
    log.debug('Discovered external IP address {}'.format(ext_ifaddress))
    return ext_ifaddress


def find_hostname(bind_addr=None):
    ext_ifaddress = bind_addr
    if not bind_addr or bind_addr == '0.0.0.0':
        ext_ifaddress = find_external_address()
    myhostname = ext_ifaddress
    log.debug('Using external IP address {}'.format(ext_ifaddress))
    ext_name = socket.getfqdn(ext_ifaddress)
    log.debug('{} has a PTR record of {}'.format(ext_ifaddress, ext_name))
    try:
        ext_name_addr = socket.gethostbyname(ext_name)
        if ext_name_addr == ext_ifaddress:
            quality = 'nice'
            myhostname = ext_name
        else:
            quality = 'bad'
        log.debug('{} resolves to {} which is {}'.format(ext_name, ext_name_addr, quality))
    except socket.gaierror:
        log.debug('DNS lookup for {} failed'.format(ext_name))
    log.info('Using {} as my external hostname.'.format(myhostname))
    return myhostname


def templated(template=None):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            template_name = template
            if template_name is None:
                template_name = flask.request.endpoint.replace('.', '/') + '.html'
            ctx = f(*args, **kwargs)
            if ctx is None:
                ctx = {}
            elif not isinstance(ctx, dict):
                return ctx
            return flask.render_template(template_name, **ctx)
        return decorated_function
    return decorator


class ReverseProxied(object):
    '''Wrap the application in this middleware and configure the
    front-end server to add these headers, to let you quietly bind
    this to a URL other than / and to an HTTP scheme that is
    different than what is used locally.

    see: http://flask.pocoo.org/snippets/35/

    In nginx:
    location /myprefix {
        proxy_pass http://192.168.0.1:5001;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Scheme $scheme;
        proxy_set_header X-Script-Name /myprefix;
        }

    :param app: the WSGI application
    '''
    def __init__(self, app):
        self.app = app

    def __call__(self, environ, start_response):
        script_name = environ.get('HTTP_X_SCRIPT_NAME', '')
        if script_name:
            environ['SCRIPT_NAME'] = script_name
            path_info = environ['PATH_INFO']
            if path_info.startswith(script_name):
                environ['PATH_INFO'] = path_info[len(script_name):]

        scheme = environ.get('HTTP_X_SCHEME', '')
        if scheme:
            environ['wsgi.url_scheme'] = scheme
        return self.app(environ, start_response)


def mime_from_filepointer(fp):
    """Detect MIME type from file pointer if libmagic is available.

    The filepointer must be seekable. The position of the pointer is restored after the detection procedure. The
    detection is done at the beginning of the file where up to 1024 bytes are read.

    In case the file type cannot be detected, ``'application/octet-stream'`` is returned.

    :param fp: file pointer
    :returns: string representing the MIME type of the file pointer.
    """
    try:
        import magic
    except ImportError:
        log.warn('libmagic is not available. Can not determine MIME type for static resource.')
        return None
    pos = fp.tell()
    fp.seek(0)
    data = fp.read(1024)
    mime = magic.from_buffer(data, mime=True)
    fp.seek(pos, os.SEEK_SET)
    return mime


def compose(*funcs):
    """Compose functions.

    ``c = compose(f, g, h)`` returns a new function `c`, so that ``c(x)`` is equivalent to ``f(g(h(x)))``."""
    first, tail = funcs[-1], reversed(funcs[:-1])
    def composed(*args, **kwargs):
        ret = first(*args, **kwargs)
        for f in tail:
            ret = f(ret)
        return ret
    return composed