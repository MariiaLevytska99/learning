# -*- coding: utf-8 -*-
""""""

from __future__ import (absolute_import, division, print_function)

import logging
import os

import sys

import click
import flask
import yaml
from debtcollector import deprecate

from flask import Flask
from flask_caching import Cache
from flaskext.markdown import Markdown

import simplekv, simplekv.decorator
from storefact._hstores import HFilesystemStore

from glance.web._utils import ReverseProxied, compose
from glance.web.api import API
from glance.web.bpui import make_ui_blueprint
from glance.web.bpapi import make_api_blueprint
from glance.web.bpprometheus import make_prometheus_blueprint


logging.basicConfig(level=logging.DEBUG)
log = logging.getLogger('glance.web.newapp')


def _require_login():
    if 'cas' not in flask.current_app.blueprints:
        return
    logged_in_user = flask.session.get('CAS_USERNAME')
    logged_in = logged_in_user is not None
    authorized = logged_in_user in flask.current_app.config.get('allowed_users', [])

    if logged_in and authorized:
        # -> no further action required
        return

    if not logged_in:
        flask.session['CAS_AFTER_LOGIN_SESSION_URL'] = flask.request.path
        log.debug('Not authenticated, forwarding to {}'.format(
            flask.url_for('cas.login', _external=True)))
        return flask.redirect(flask.url_for('cas.login', _external=True))

    # logged in, but user is not authorized
    return flask.render_template('authfail.html', logged_in_user=logged_in_user)


def _configure_app(app, config):
    if config['debug']:
        app.debug = True
    app.jinja_options = dict(trim_blocks=True, lstrip_blocks=True,
                             extensions=['jinja2.ext.loopcontrols',
                                         'jinja2.ext.with_'])
    app.config['SECRET_KEY'] = 'squeamish ossifrage'
    app.config['SESSION_COOKIE_NAME'] = 'glance'

    if 'server_name' in config:
        app.config['SERVER_NAME'] = config['server_name']
        app.config['SESSION_COOKIE_DOMAIN'] = app.config['SERVER_NAME'].rsplit(':', 1)[0]


    # Flask extensions
    Markdown(app)
    Cache(app, config={'CACHE_TYPE': 'simple'})

    # Require logged-in user if CAS options are set:
    if config.get('auth', False):
        from flask_cas import CAS
        authconf = config['auth']

        if sys.version_info >= (2, 7, 9):
            # monkeypatch ssl to avoid
            # http://stackoverflow.com/questions/27835619/ssl-certificate-verify-failed-error
            import ssl
            ssl._create_default_https_context = ssl._create_unverified_context

        CAS(app)
        app.config['CAS_SERVER'] = authconf['cas_server']
        app.config['CAS_AFTER_LOGIN'] = '/'
        if 'cas_login_route' in authconf:
            app.config['CAS_LOGIN_ROUTE'] = authconf['cas_login_route']

        app.config['allowed_users'] = authconf['allowed_users']

    app.wsgi_app = ReverseProxied(app.wsgi_app)

    return app


def _register_auth_check(blueprint):
    def _authcheck():
        from flask import request
        if flask.request.endpoint == blueprint.name + '.static':
            log.debug('AUTH: static route [{}] is whitelisted'.format(request.endpoint))
            return
        else:
            log.debug('AUTH: non-static route [{}] needs authorization'.format(request.endpoint))
            return _require_login()
    blueprint.before_request(_authcheck)


def create_app(reports_path, title, debug=None, config=()):
    """Create the monitoring flask app

    :param Union[str, simplekv.KeyValueStore] reports_path: SimpleKV store object or base
        path of serialized monitoring reports.
    :param str title: (Optional) Overall title of the monitoring page
    :param bool debug: (Deprecated) Use config['debug'] instead.
    :param dict config: (Optional) Dictionary of configuration options

    **Configuration Options:**

    +---------------------+----------------+-------------------------------------------------------+
    | Name                | Default        | Meaning                                               |
    +=====================+================+=======================================================+
    | debug               | False          | Turn on debugging mode                                |
    +---------------------+----------------+-------------------------------------------------------+
    | sidebar_status      | False          | Show block status indicators in sidebar               |
    +---------------------+----------------+-------------------------------------------------------+
    | server_name         | None           | Flask SERVER_NAME setting                             |
    +---------------------+----------------+-------------------------------------------------------+
    | auth                | None           | Dictionary with settings for authentication via CAS:: |
    |                     |                |                                                       |
    |                     |                |     {'cas_server': 'https://sso.blue-yonder.org',     |
    |                     |                |      'cas_login_route': '/cas/login',                 |
    |                     |                |      'allowed_users': [...]},                         |
    |                     |                |      'server_name': 'some.machine.rack.zone:5000',    |
    |                     |                |     }                                                 |
    +---------------------+----------------+-------------------------------------------------------+
    | group_sort_key      | None           | Sort key for groups. See :py:func:`sorted`            |
    +---------------------+----------------+-------------------------------------------------------+
    | title_sort_key      | None           | Sort key for reports within a group                   |
    +---------------------+----------------+-------------------------------------------------------+
    | link_endpoints      | None           | Dictionary with mapping endpoint IDs to base-URLs.    |
    |                     |                | Example::                                             |
    |                     |                |                                                       |
    |                     |                |     { 'bybokeh': 'https://vs0.stable.ipc3.rack.zone', |
    |                     |                |       'wiki': 'https://wiki.blue-yonder.org' }        |
    +---------------------+----------------+-------------------------------------------------------+

    """
    config_defaults = {
        'debug': False,
        'sidebar_status': False,
        'group_sort_key': None,
        'title_sort_key': None,
        'link_endpoints': None,
    }

    config_defaults.update(config)
    config = config_defaults

    if not isinstance(reports_path, (simplekv.decorator.StoreDecorator, simplekv.KeyValueStore)):
        reports_path = HFilesystemStore(os.path.abspath(reports_path))

    if debug is not None:
        deprecate('Using the debug parameter is deprecated',
                  postfix='. Use the config dictionary instead.', removal_version='1.0.0')
        config['debug'] = debug

    app_config = {
        'debug': config['debug'],
    }

    auth_configured = 'auth' in config
    servername_set = 'server_name' in config

    if auth_configured:
        app_config['auth'] = config['auth']
    if servername_set:
        app_config['server_name'] = config['server_name']

    app = Flask(__name__)

    _configure_app(app, app_config)

    api1 = API(reports_path, groupkey=config['group_sort_key'], titlekey=config['title_sort_key'])

    bp_ui = make_ui_blueprint(api1, title, link_endpoints=config['link_endpoints'], sidebar_status=config['sidebar_status'])
    if auth_configured:
        _register_auth_check(bp_ui)
    bp_api = make_api_blueprint(api1, title)
    bp_prometheus = make_prometheus_blueprint(api1, title)

    app.register_blueprint(bp_ui)
    app.register_blueprint(bp_api, url_prefix='/api1')
    app.register_blueprint(bp_prometheus, url_prefix='/metrics')

    # api2 = API(fsopendir('../../glance/example/reports'))
    # app.register_blueprint(make_ui_blueprint(api2, {'title': 'Other'}), url_prefix='/other')

    return app

# noinspection PyDocstring
@click.command()
@click.option('address', '-a', default=None, help='Address to bind to')
@click.option('port', '-p', default=None, help='Port to listen on', type=click.INT)
@click.option('debug', '-d', default=False, help='Start in debug mode')
@click.option('option', '-o', multiple=True, help='Options for create_app (see documentation). Values are parsed as YAML.')
@click.argument('reports_path', default=os.getcwd(), type=click.Path(exists=True, dir_okay=True, resolve_path=True))
def cli(reports_path=None, title='Reports', debug=False, address=None, port=None, option=()):
    def parse_value(tup):
        return tup[0], yaml.load(tup[1])
    def split_eq(s):
        return s.split('=')
    launch_address = address if address else '127.0.0.1'
    launch_port = port if port else 5000
    url = 'http://{}:{}/'.format(launch_address, launch_port)
    log.info('Starting web server on {}'.format(url))
    click.launch(url)
    app_opts = dict(map(compose(parse_value, split_eq), option))
    run(reports_path=reports_path, title=title, debug=debug, address=address, port=port, app_opts=app_opts)


def run(reports_path=None, title='Reports', debug=False, address=None, port=None, app_opts={}):
    """Start a monitoring web server and serve the files from REPORT_PATH.
    If no path is given, serve reports from the current working directory.
    """

    if reports_path is None:
        reports_path = os.getcwd()
    if not isinstance(reports_path, (simplekv.decorator.StoreDecorator, simplekv.KeyValueStore)):
        reports_path = HFilesystemStore(os.path.abspath(reports_path))

    opts = dict(debug=debug)
    if app_opts:
        opts.update(app_opts)

    app = create_app(reports_path=reports_path, title=title, config=opts)

    app_options = {}
    if debug:
        app_options.update(dict(
            debug=True,
            use_debugger=True,
            use_reloader=False,
        ))
        from flask.ext.debugtoolbar import DebugToolbarExtension
        # from flask_debugtoolbar_lineprofilerpanel.profile import line_profile  # @line_profile decorator
        app.config['DEBUG_TB_PANELS'] = [
            'flask_debugtoolbar.panels.versions.VersionDebugPanel',
            'flask_debugtoolbar.panels.timer.TimerDebugPanel',
            'flask_debugtoolbar.panels.headers.HeaderDebugPanel',
            'flask_debugtoolbar.panels.request_vars.RequestVarsDebugPanel',
            'flask_debugtoolbar.panels.config_vars.ConfigVarsDebugPanel',
            'flask_debugtoolbar.panels.template.TemplateDebugPanel',
            'flask_debugtoolbar.panels.logger.LoggingPanel',
            'flask_debugtoolbar.panels.route_list.RouteListDebugPanel',
            'flask_debugtoolbar.panels.profiler.ProfilerDebugPanel',
            # Add line profiling
            'flask_debugtoolbar_lineprofilerpanel.panels.LineProfilerPanel'
        ]
        # noinspection PyUnusedLocal
        toolbar = DebugToolbarExtension(app)
        log.debug('added debugtoolbar')

    app.run(host=address, port=port, **app_options)

if __name__ == '__main__':
    run(sys.argv[1])
