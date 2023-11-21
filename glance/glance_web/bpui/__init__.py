# -*- coding: utf-8 -*-
""""""

from __future__ import (absolute_import, division, print_function)

from operator import itemgetter

import six
from six import BytesIO
import os.path

import flask
import jinja2
import pkg_resources
from datetime import datetime
import logging
from bokeh.util.paths import bokehjsdir

from flask import (Blueprint, session, abort, url_for, current_app)
from jinja2 import evalcontextfilter, Markup

import glance.constants
from glance.utils import slugify
from glance.storage import check_and_repair
from glance.report import plugin_static_paths, plugin_template_paths, plugin_static_links

from .._utils import templated, mime_from_filepointer

log = logging.getLogger(__name__)


def make_ui_blueprint(api, title, link_endpoints=None, sidebar_status=False):
    """Create a flask Blueprint for a report Web front-end.

    :param api: (:) API-object for a report root
    """

    if link_endpoints is None:
        link_endpoints = ()

    log.info('creating blueprint "{}"'.format(__name__))
    blueprint = Blueprint(
        'ui-' + slugify(title), __name__,
        static_url_path='/uistatic',
        static_folder=pkg_resources.resource_filename(__name__, 'static'),
        template_folder=pkg_resources.resource_filename(__name__, 'templates'),
    )

    # If there are plugins providing additional templates, add template
    # loaders for them here. Could probably also be done while the server
    # is running, so new plugins would be usable without restart.
    loaders = [jinja2.FileSystemLoader(tmpl_path)
               for tmpl_path in plugin_template_paths]
    blueprint.jinja_loader = jinja2.ChoiceLoader([blueprint.jinja_loader] + loaders)

    @blueprint.context_processor
    def inject_definitions():
        return {
            'session': session,
            'now': datetime.now,
            'constants': glance.constants,
            'general': {
                'name': title,
                'sidebar_status': sidebar_status,
            },
            'reportdata': {
                'reportlist': api.list_reports(),
                'reportinfo': api.reportinfo,
                'reports': api.reports,
            },
            'static_links': list(map(link_to_html, plugin_static_links)),
            'link_endpoints': link_endpoints,
            'version': {
                'glance': glance.core.__version__,
                'glance-web': glance.web.__version__,
            },
        }

    blueprint.add_app_template_filter(slugify, 'slugify')

    @blueprint.app_template_filter('datetimeformat')
    def datetimeformat(value, format='%d-%m-%Y %H:%M'):
        try:
            formatted = value.strftime(format)
        except ValueError:
            formatted = '-'
        return formatted

    @blueprint.app_template_filter
    @evalcontextfilter
    def nl2br(eval_ctx, value):
        result = value.replace('\n', '<br>\n')
        if eval_ctx.autoescape:
            result = Markup(result)
        return result

    @blueprint.route('/')
    @templated('index.html')
    def index():
        reports = api.index()
        groups = api.report_groups()
        return {'reports': reports, 'report_groups': groups}

    @blueprint.route('/reports/<reportid>/')
    @blueprint.route('/reports/<reportid>/<runid>')
    @blueprint.route('/reports/<reportid>/<runid>/<int:blockind>')
    @templated('report_page.html')
    def report_page(reportid, runid=None, blockind=None):
        if reportid not in api.list_reports():
            return abort(404)

        if runid in (None, 'latest'):
            runid = api.reportinfo[reportid]['latest']
            log.info('"latest" is "{}"'.format(runid))

        runlist = api.reportinfo[reportid]['runs']
        timesorted = sorted(runlist.values(), key=lambda v: v['timestamp'], reverse=True)

        if (runid not in runlist) and (len(runlist) > 0):
            log.debug('report %s has no runid %s', reportid, runid)
            runid = _find_closest_run(api, reportid, runid)
            newurl = flask.url_for('.report_page', reportid=reportid, runid=runid)
            log.debug('redirecting to %s', newurl)
            return flask.redirect(newurl)

        try:
            current_report = api.reports[reportid][runid]
        except LookupError:
            flask.abort(404)
        except Exception as ex:  # Not sure if we can be more specific here
            log.exception('Error reading report {}/{}: "{}"'.format(reportid, runid, ex))
            flask.flash(
                '{}/{} seems to be damaged. See server log for details.'.format(reportid, runid))
            return flask.redirect(flask.request.referrer)

        _setup_tags(current_report)

        if current_report is None:
            log.debug('Check/repair missing index entries')
            check_and_repair(api.storage, reportid)

        reportnavdata = [
            {'reportid': thereport,
             'shorttitle': api.reportinfo[thereport]['shorttitle'],
             'url': flask.url_for('.report_page', reportid=thereport, runid=runid),
             'label': api.reportinfo[thereport]['title'],
             'is_current': (thereport == reportid),
             } for thereport in sorted(api.list_reports())]
        runnavdata = [
            {'url': flask.url_for('.report_page', reportid=reportid,
                                  runid=rundata['runid'], blockind=blockind),
             'label': rundata['runtitle'],
             } for rundata in timesorted]
        blocknavdata = [
            {'url': flask.url_for('.report_page', reportid=reportid, runid=runid,
                                  blockind=seq_index),
             'label': label, 'section_index': sind, 'block_index': bind,
             } for sind, bind, seq_index, label in current_report.iter_blocks(with_all_indices=True)]

        current_block = None
        if blockind is not None:
            sind = blocknavdata[blockind]['section_index']
            bind = blocknavdata[blockind]['block_index']
            current_block = current_report.sections[sind].blocks[bind]
        timesorted_index = list(map(itemgetter('runid'), timesorted)).index(runid)

        current = {
            'report_groups': api.report_groups(),
            'report': api.reports[reportid][runid],
            'blockindex': blockind,
            'reportid': reportid,
            'runid': runid,
            'runnavdata': runnavdata,
            'runindex': timesorted_index,
            'reportnavdata': reportnavdata,
            'reportindex': api.list_reports().index(reportid),
            'blocknavdata': blocknavdata,
            'block': current_block,
        }
        return {
            'current': current,
            'tags': _setup_tags(api.reports[reportid][runid]),
        }

    @blueprint.route('/<reportid>/<runid>/data-export/csv/<resid>')
    def data_export(reportid, runid, resid):
        report = api.reports[reportid][runid]
        isec, iblk, ires = map(int, resid.split('-'))
        res = report.get_element(isec, iblk, ires)
        if getattr(res, 'allow_data_export', False):
            filename = '{}-{}-{}.csv'.format(reportid, runid, resid)
            return flask.send_file(
                BytesIO(res.export_data()),
                mimetype='text/csv',
                add_etags=False,
                as_attachment=True,
                attachment_filename=filename)

    @blueprint.route('/<reportid>/<runid>/data-export/json/<resid>.json')
    def data_export_json(reportid, runid, resid):
        report = api.reports[reportid][runid]
        isec, iblk, ires = map(int, resid.split('-'))
        res = report.get_element(isec, iblk, ires)
        current_app.logger.info(str(res))
        return res.export_json()

    @blueprint.route('/<reportid>/<runid>/resources/<filename>')  # pre-3 file format
    @blueprint.route('/<reportid>/<runid>/resource/<key>/<filename>')
    def report_resource(reportid, runid, filename=None, key=None):
        current_report = api.reports[reportid][runid]
        if key is not None:
            try:
                res = current_report._resources[key]['data']
            except KeyError:
                abort(404)

            if isinstance(res, six.text_type):
                # potentially an issue during py2->py3 migration
                # 'raw_unicode_escape' is used by pickle so we reverse the wrong pickle type
                res = res.encode('raw_unicode_escape')

            fp = BytesIO(res)
            mime = mime_from_filepointer(fp)
            return flask.send_file(
                fp,
                add_etags=False,
                attachment_filename=filename,
                mimetype=mime,
            )
        else:
            respath = os.path.join(reportid, runid, 'resources', filename)
            fp = api.storage.open(respath, mode='rb')
            mime = mime_from_filepointer(fp)
            return flask.send_file(
                fp,
                add_etags=False,
                mimetype=mime,
            )

    @blueprint.route('/bokehstatic/<path:filename>')
    def bokehstatic(filename):
        return flask.send_from_directory(bokehjsdir(), filename)

    # Plugin support

    @blueprint.route('/plugin/<plugin>/<path:filename>')
    def plugin_static(plugin, filename):
        try:
            path = plugin_static_paths[plugin]
            return flask.send_from_directory(path, filename)
        except KeyError:
            flask.abort(404)

    return blueprint


def _set_status_tags(report):
    for section in report.sections:
        for block in section.blocks:
            status_tag = glance.constants.status_names.get(block.status, None)
            if status_tag is not None:
                if (block.tags == []) or (status_tag != 'No Tag'):
                    if status_tag not in block.tags:
                        block.tags += [status_tag]


def _get_all_tags(report):
    """:return list of all unique tags used in the report
       :return dict of number of blocks with each tag
    """
    _set_status_tags(report)
    counter = {'All': 0}
    for status_name in glance.constants.status_names.values():
        # set up counters for default filters
        counter[status_name] = 0

    for section in report.sections:
        for block in section.blocks:
            for tag in block.tags:
                if tag not in counter:
                    counter[tag] = 0
                counter[tag] += 1
            counter['All'] += 1
    tags = list(counter.keys())
    tags.remove('All')
    tagids = {}
    for tag in tags:
        tagids[tag] = slugify(tag)
    return tags, tagids, counter


def _setup_tags(report):
    tags, tagids, counter = _get_all_tags(report)
    tags.sort()
    section_tags = {}
    for section in report.sections:
        section_tags[section] = list(
            set(tag for blk in section.blocks for tag in blk.tags))
    return {'tags': tags, 'counter': counter, 'sections': section_tags, 'tagids': tagids}


def _find_closest_run(api, reportid, runid=None):
    # This gets called when a runid was requested that doesn't exist for this report
    # This can happen for example when the user navigates between reports. So we try
    # to find the requested runid in the other reports.  If we find it  we take its
    # timestamp and look for the run of the report the user has  requested that has
    # the closest timestamp.  If no runid was given or no other report can be found
    # with that runid,  we use now() for the timestamp, which means we end up using
    # the most recent run.
    if runid is None:
        src_timestamp = datetime.now()
    else:
        for other_report in api.list_reports():
            log.debug('looking in %s', other_report)
            if (other_report != reportid) and runid in api.reportinfo[other_report]['runs']:
                src_report = other_report
                src_timestamp = api.reportinfo[src_report]['runs'][runid]['timestamp']
                log.debug('found runid %s in report %s with timestamp %s', runid,
                          other_report, str(src_timestamp))
                break
        else:
            src_timestamp = datetime.now()
            log.debug('runid %s not found in any other report, set to now (%s)', runid,
                      str(src_timestamp))

    runlist = api.reportinfo[reportid]['runs']
    timesorted = sorted(runlist.values(), key=lambda v: v['timestamp'])

    closest = timesorted[-1]
    log.debug('looking for run in %s with timestamp closest to %s', reportid,
              str(src_timestamp))
    for therun in api.reportinfo[reportid]['runs'].values():
        if abs(src_timestamp - therun['timestamp']) < abs(src_timestamp - closest['timestamp']):
            log.debug('run %s is closer with timestamp %s', therun['runid'],
                      str(therun['timestamp']))
            closest = therun
        else:
            log.debug('run %s is not closer with timestamp %s', therun['runid'],
                      str(therun['timestamp']))

    closest_runid = closest['runid']
    log.debug('found runid %s', closest_runid)
    return closest_runid


def link_to_html(link_dict):
    link_type = link_dict.get("type", None)
    link_plugin = link_dict['plugin']
    link_filename = link_dict['filename']
    if link_type == "js":
        result = "<script src=\"{}\"></script>".format(url_for('.plugin_static', plugin=link_plugin, filename=link_filename))
    elif link_type == "css":
        result = "<link href=\"{}\" rel=\"stylesheet\">".format(url_for('.plugin_static', plugin=link_plugin, filename=link_filename))
    else:
        result = ""

    return result.format(**link_dict)
