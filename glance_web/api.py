# -*- coding: utf-8 -*-
"""This module implements the read-only Python API to stored reports."""

from __future__ import (absolute_import, division, print_function)

import sys
from collections import OrderedDict
import logging

import cachetools

import glance.storage
import glance.report

from ._compat import reraise

log = logging.getLogger(__name__)


class _ReportCache(cachetools.TTLCache):
    def __init__(self, api_root, storage, reportid):
        self.api_root = api_root
        self.storage = storage
        self.reportid = reportid

        super(_ReportCache, self).__init__(maxsize=200, ttl=300)

    def __missing__(self, runid):
        log.info(
            'API root {}: report cache miss for "{}/{}". Read and store.'.format(
                self.api_root,
                self.reportid,
                runid,
            )
        )
        report = glance.report.read_report(self.storage, self.reportid, runid)
        self[runid] = report
        return report


class _ReportInfoCache(cachetools.TTLCache):
    def __init__(self, storage):
        self.storage = storage
        self.reports = {}
        self.reportlist = []

        super(_ReportInfoCache, self).__init__(maxsize=5000, ttl=60)

        self.list_reports()

    def __hash__(self):
        return id(self)

    def __missing__(self, reportid):
        """Get metadata, including list of runs, of one report.

        If the report has since been removed from storage, return None.

        :param str reportid: Report ID

        :return: Dict of report properties

        Example return value::

            {
                'title':'My report',
                'group':'',
                'shorttitle':'My report',
                'latest':'runid3',
                'runs': {
                    'runid1':{ 'runid':'runid1', 'timestamp':datetime(...), 'runtitle':'...'},
                    'runid2':{ 'runid':'runid2', 'timestamp':datetime(...), 'runtitle':'...'},
                    'runid3':{ 'runid':'runid3', 'timestamp':datetime(...), 'runtitle':'...'},
                    ...
                },
                ...
            }
        """
        try:
            info = self._update_reportinfo(reportid)
            group, shorttitle = _groupsplit(info['title'])
            info['group'] = group
            info['shorttitle'] = shorttitle

            runlist = info['runs']
            timesorted = sorted(runlist.values(), key=lambda v: v['timestamp'], reverse=True)
            if runlist:
                info['latest'] = timesorted[0]['runid']
            else:
                info['latest'] = None
            self[reportid] = info
            return info
        except IOError:
            self[reportid] = None
            return None

    def _update_reportinfo(self, reportid):
        log.info('API root {}: reportinfo cache miss for "{}". Read and store.'.format(id(self), reportid))
        try:
            info = glance.storage.get_report_info(self.storage, reportid, check_index=False)
            return info
        except IOError as e:
            etype, evalue, etb = sys.exc_info()
            log.exception('Error reading report info for "{}"'.format(reportid))
            self.reportlist.remove(reportid)
            reraise(etype, evalue, etb)

    @cachetools.cached(cachetools.TTLCache(1, ttl=30))  # cache reportlist for 30s
    def list_reports(self):
        """Return a list of all report IDs."""
        reportlist = glance.storage.list_reports(self.storage)
        # invalidate caches for reports that have gone away:
        for reportid in self.keys():
            if reportid not in reportlist:
                self.reportinfo.pop(reportid)
        for reportid in self.reports.keys():
            if reportid not in reportlist:
                self.reports.pop(reportid)
        # make sure there's a cache for each reportid in the reports cache:
        for reportid in reportlist:
            if reportid not in self.reports:
                log.info('API root {}: adding report cache for "{}"'.format(id(self), reportid))
                c = _ReportCache(id(self), self.storage, reportid)
                self.reports[reportid] = c
        self.reportlist = reportlist
        return reportlist


class API(object):
    def __init__(self, storage, groupkey=None, titlekey=None):
        """The two optional parameters `groupkey` and `titlekey` are :py:func:`sorted` -style key
        functions for sorting report groups and reports within a group by title.

        :param simplekv.KeyValueStore storage: The storage root
        :param callable groupkey: Comparison function for report groups
        :param callable titlekey: Comparison function for reports within a group
        """
        self.groupkey = groupkey
        self.titlekey = titlekey
        self.reportinfo = _ReportInfoCache(storage)

    def index(self):
        """Return metadata about all reports.

        Returns a dictionary with a key for each report ID containing a dictionary with
        the following fields

        ==========  =========================================================
        title       The report title including the group prefix
        group       The group prefix contained in the report title
        shorttitle  The report title without the group prefix
        latest      run ID of the latest run
        timestamp   Timestamp of the latest run
        updated     String representation of the timestamp of the latest run
        status      Status counter dictionary. status value -> count
        ==========  =========================================================
        """
        reports = {}
        for rid in self.list_reports():
            info = self.reportinfo[rid]
            group, shorttitle = _groupsplit(info['title'])
            latest_id = info['latest']

            if latest_id is None:
                continue

            latest_run = info['runs'][latest_id]
            reports[rid] = {
                'title': info['title'],
                'group': group,
                'shorttitle': shorttitle,
                'latest': latest_id,
                'timestamp': latest_run['timestamp'],
                'updated': latest_run['timestamp'].isoformat(),
                'status': latest_run['status'],

            }
        return reports

    def report_groups(self):
        """Returns an `OrderedDict` with all report groups and the reports belonging to each group."""
        groups = OrderedDict()

        def _groupkey(reportid):
            group = _groupsplit(self.reportinfo[reportid]['title'])[0]
            if self.groupkey is None:
                return group
            else:
                return self.groupkey(group)

        def _titlekey(reportid):
            title = _groupsplit(self.reportinfo[reportid]['title'])[1]
            if self.titlekey is None:
                return title
            else:
                return self.titlekey(title)

        for reportid in sorted(sorted(self.list_reports(), key=_titlekey), key=_groupkey):
            info = self.reportinfo[reportid]
            latest_id = info['latest']

            if latest_id is None:
                continue

            group = self.reportinfo[reportid]['group']
            groups.setdefault(group, []).append(reportid)

        return groups

    def list_reports(self):
        """Return a list of all report IDs."""
        return self.reportinfo.list_reports()

    @property
    def reports(self):
        return self.reportinfo.reports


def _groupsplit(name):
    if '|' in name:
        return list(map(str.strip, name.split('|', 1)))
    else:
        return '', name
