"""Storage API

This is the still experimental API for managing stored reports.

The most useful functions for users are:

* To list the reports in a top-level storage, use :func:`~list_reports()`.
* :func:`~get_report_info()` returns metadata of one report and the list of all runs with
  some metadata for each run.
* :func:`~delete_older()` deletes all runs older than a given timestamp
* :func:`~delete_keeping_n()` deletes all runs but the newest `n`

Open questions:
* Should the list of reports and the list of runs be a dictionary?"""
from __future__ import absolute_import

from operator import itemgetter
import logging
import re
import simplekv
import yaml
from simplekv.decorator import PrefixDecorator

from .core.compat import BytesIO
# noinspection PyUnresolvedReferences
from . import patch_yaml

# The file format has a header structure before the actual Report data.
# Since this makes the top-level data structure a list [ header, data ] where
# it used to be a mapping (the fields/values of the Report object), we can
# detect right after parsing if we are dealing with an old-style or new-style
# file.
#
# When a file is opened, we look for this difference and in case of a new-style
# file the specific version information, and save it in a global variable, so
# our unfix_dict() methods can use it.
# This is messy and, I guess, not thread safe, but I can't think of a nicer
# way off of the top of my head.

format_version = 4  # Version of the format when writing

NEW_KEY_SEPARATOR = '.'
OLD_KEY_SEPARATOR = '/'
WRITE_KEY_SEPARATOR = OLD_KEY_SEPARATOR

log = logging.getLogger(__name__)


def _ensure_fs(storage):
    if not isinstance(storage, simplekv.KeyValueStore):
        from storefact import get_store
        storage = get_store(type='hfs', path=storage)
    return storage


def list_runs(storage, reportid):
    """List all runs of a given reportid.

    :param storage: storage handle (`simplekv.KeyValueStore`)
    :param str reportid: report-id
    """
    def has_sep(key):
        return (OLD_KEY_SEPARATOR in key) or (NEW_KEY_SEPARATOR in key)

    prefix = join_key(reportid, '')
    keys = [k[len(prefix):] for k in storage.keys() if k.startswith(prefix)]  # everything belonging to this report
    runs = list(set(split_key(key)[0] for key in keys if has_sep(key)))  # keep only 'path'-like key components
    return runs


def list_reports(storage):
    """List reports (top-level "directory").

    :param storage: Storage handle of report root

    :return: List of report-ids: ``['report1', 'report2', ... ]``
    """
    allkeys = list(storage.keys())
    dirs = list(set([split_key(key)[0] for key in allkeys]))

    def containsrun(prefix):
        rundirs = [key for key in allkeys
                   if key.startswith(prefix) and key.endswith('json')]
        return len(rundirs) > 0
    reports = sorted(dir for dir in dirs
                     if join_key(dir, 'index') in allkeys
                     or containsrun(join_key(dir, '')))
    return reports


def get_report_info(storage, reportid, check_index=False, repair_index=False):
    """Get metadata, including list of runs, of one reportdir.

    :param storage: Storage handle of reportdir root
    :param str reportid: Report-ID
    :param bool check_index: Compare index with storage content and log discrepancies
    :param bool repair_index: Bring index back in sync with storage content

    :return: Dict of report properties

    Example return value::

        {
            'title':'My report',
            'runs': {
                'runid1':{ 'runid':'runid1', 'timestamp':datetime(...), 'runtitle':'...'},
                'runid2':{ 'runid':'runid2', 'timestamp':datetime(...), 'runtitle':'...'},
                'runid3':{ 'runid':'runid3', 'timestamp':datetime(...), 'runtitle':'...'},
                ...
            },
            ...
        }
    """
    if check_index or repair_index:
        extra_dirs, extra_entries = _check_missing(storage, reportid)
        if extra_dirs or extra_entries:
            log.info('Found %i dirs not in index, %i index entries without data dir', len(extra_dirs), len(extra_entries))
        if repair_index:
            check_and_repair(storage, reportid)

    reportdata = {}

    indexkey = join_key(reportid, 'index')
    if indexkey in storage:
        head, runlist = yaml.safe_load(storage.get(indexkey))
        runs = dict((run['runid'], run) for run in runlist)

        reportdata = {
            'title': head['title'],
            'runs': runs,
        }

    return reportdata


def _add_missing(storage, reportid, new_runs):
    """Add index entries for runs that exist but are missing from the index.

    :param storage: Base storage
    :param reportid: Report-ID
    :param new_runs: Runs to be added"""
    import glance.report
    for runid in new_runs:
        try:
            key = join_key(reportid, runid, 'report.json')
            content = glance.report.Report.from_storage(key, storage)
            info = {'runid': content.runid, 'timestamp': content.timestamp,
                    'runtitle': content.runtitle, 'status_stats': content.status_stats(),
                    'title': content.title}
            _add_to_index(storage, reportid, **info)
        except Exception:
            log.exception('Problem reading {}:{}'.format(reportid, runid))


def _check_missing(storage, reportid):
    """Check for runs that exist in the storage but are missing from the index.

    :param storage: Base storage
    :param reportid: Report-ID

    :return: List of existing runs not in index
    """
    reportdir = PrefixDecorator(join_key(reportid, ''), storage)
    indexed_runs = {}
    if 'index' in reportdir:
        head, runlist = yaml.safe_load(reportdir.get('index'))
        indexed_runs = dict((run['runid'], run) for run in runlist)

    # check if there are dirs that are not in the index file,
    # or entries in the index without a matching dir:
    dirs = set(split_key(key)[0] for key in reportdir.keys() if len(split_key(key)) > 1)
    indexed = set(r['runid'] for r in indexed_runs.values())
    extra_dirs = list(dirs - indexed)
    extra_entries = list(indexed - dirs)

    extraruns = [path for path in extra_dirs if join_key(path, 'report.json') in reportdir]

    return extraruns, extra_entries


def check_and_repair(storage, reportid):
    """Compare index file with storage and add runs from storage that are missing in index
    and remove runs from index that are missing in storage.

    Does not check runs that are in both storage and index for consistency.

    :param storage: Storage handle of report root
    :param str reportid: Report-ID"""
    missing, extra = _check_missing(storage, reportid)
    if missing or extra:
        log.info('check_and_repair("%s"): found %i dirs not in index, %i index entries without data dir', reportid, len(missing), len(extra))
    _add_missing(storage, reportid, missing)
    for runid in extra:
        _remove_from_index(storage, reportid, runid)


def delete_run(storage, reportid, runid):
    """Remove one report run from storage.

    This deletes the run from the list of runs and deletes all data belonging to it.

    :param storage: Storage handle of report root
    :param str reportid: Report-ID
    :param str runid: Run-ID
    """
    # 1 test if path is valid
    # 2 output what will be deleted -> user confirmation

    removekey = join_key(reportid, runid)
    for key in storage.keys():
        if key.startswith(removekey):
            storage.delete(key)
    _remove_from_index(storage, reportid, runid)


def delete_older(storage, reportid, cutoff, dryrun=False):
    """Delete report runs older than the cutoff timestamp.

    This is for example how you would delete everything that's older
    than two weeks (with the help of the dateparser module)::

      cutoff = dateparser.parse('2 weeks ago')
      delete_older(st, id, cutoff)

    :param storage: Storage handle of report root
    :param str reportid: Report-ID
    :param datetime.datetime cutoff: Cut-off timestamp
    :param bool dryrun: (default: `False`) If `True`, only return what would be deleted, but don't delete anything.
    :returns: IDs of deleted runs
    """

    storage = _ensure_fs(storage)

    if not dryrun:
        check_and_repair(storage=storage, reportid=reportid)

    info = get_report_info(storage, reportid)

    deletelist = []
    for reportrun in info['runs'].values():
        if reportrun['timestamp'] < cutoff:
            if not dryrun:
                delete_run(storage, reportid, reportrun['runid'])
            deletelist.append(reportrun['runid'])
    return deletelist


def delete_keeping_n(storage, reportid, n, dryrun=False):
    """Delete older reports, but keep the newest n reports.

    :param storage: Storage handle of report root
    :param str reportid: Report-ID
    :param int n: Maximum number of reports to keep
    :param bool dryrun: (default: `False`) If `True`, only return what would be deleted, but don't delete anything.

    :returns: IDs of deleted runs
    """

    storage = _ensure_fs(storage)

    if not dryrun:
        check_and_repair(storage=storage, reportid=reportid)

    info = get_report_info(storage, reportid)
    timesorted = sorted(list(info['runs'].values()), key=itemgetter('timestamp'), reverse=True)

    deletelist = []
    for reportrun in timesorted[n:]:
        if not dryrun:
            delete_run(storage, reportid, reportrun['runid'])
        deletelist.append(reportrun['runid'])
    return deletelist


def _add_to_index(storage, reportid, runid, runtitle, timestamp, title, status_stats):
    indexkey = join_key(reportid, 'index')
    index_header = {'version': format_version, 'title': title}
    if indexkey in storage:
        try:
            parsed = yaml.safe_load(storage.get(indexkey))
            old_header, index_content = tuple(parsed)
        except (IOError, TypeError):
            index_content = []
    else:
        index_content = []
    selfindex = {
        'runid': runid,
        'runtitle': runtitle,
        'timestamp': timestamp,
        'status': status_stats,
    }
    # if same runid is already there, remove that first
    index_content = list(filter(lambda d: d['runid'] != runid, index_content))
    index_content.append(selfindex)
    timesorted = sorted(index_content, key=itemgetter('timestamp'))
    indexfile = BytesIO()
    _write_index(indexfile, index_header, timesorted)
    storage.put(indexkey, indexfile.getvalue())


def _write_index(stream, header, runs):
    class MyDumper(yaml.SafeDumper):
        def represent_sequence(self, tag, sequence, flow_style=None):
            return yaml.SafeDumper.represent_sequence(self, tag, sequence, flow_style=False)
    yaml.dump([header, runs], stream, width=500, Dumper=MyDumper, default_flow_style=True, encoding='utf-8')


def _remove_from_index(storage, reportid, runid):
    """Remove a run from the index.

    :param storage: Base storage
    :param reportid: Report-ID
    :param runid: ID of the run that should be deleted
    """
    indexkey = join_key(reportid, 'index')
    if indexkey in storage:
        indexfile = storage.open(indexkey)
        parsed = yaml.safe_load(indexfile)
        indexfile.close()
        index_header, index_content = tuple(parsed)
        index_header['version'] = format_version

        keeplist = [run for run in index_content if run['runid'] != runid]
        indexobj = BytesIO()
        _write_index(indexobj, index_header, keeplist)
        storage.put(indexkey, indexobj.getvalue())


def join_key(*args):
    """Join key components with the standard separator string."""
    return WRITE_KEY_SEPARATOR.join(args)


def split_key(key):
    separators = [OLD_KEY_SEPARATOR, NEW_KEY_SEPARATOR]
    pat = '|'.join(re.escape(ch) for ch in separators)
    return re.split(pat, key)
