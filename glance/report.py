# coding=utf-8

from __future__ import absolute_import
import codecs
import traceback
from datetime import (timedelta, datetime)
import functools
import itertools
import json
import collections
import os
import os.path
import logging
import threading
import sys
import warnings
from io import StringIO

import yaml
from yaml import YAMLError
import pandas
import debtcollector as dc
from debtcollector.removals import removed_kwarg
from debtcollector import deprecate
import six

# noinspection PyUnresolvedReferences
from . import patch_yaml

from .core import _util
from .core import compat
from .core._util import title_fnmatch, title_re_match
from .core.compat import pickle, reraise, BytesIO, PY2, binary_type
from .storage import _add_to_index, format_version, join_key, OLD_KEY_SEPARATOR, NEW_KEY_SEPARATOR, \
    split_key, list_reports, list_runs, check_and_repair
from .utils import status_max, combine_status, slugify, ensure_dataframe, validate_status
from . import constants as stat

warnings.filterwarnings('default', module='glance')

__all__ = ['Report', 'Section', 'Block', 'TextResult', 'TableResult',
           'PlotResult', 'ImageResult', 'Serializable']


tagged_serializables = {}
plugin_template_paths = []
plugin_static_paths = {}
plugin_static_links = []

log = logging.getLogger(__name__)

_ctx = threading.local()


def get_context():
    if not getattr(_ctx, '_is_initialized', False):
        _ctx.current_file_format = None  # Version of the format currently being read
        _ctx._is_initialized = True
    return _ctx


def tagged(cls):
    """Class decorator. Register a class to be serialized with a tag.

    When deserializing, if the type of an object is not determined (for
    example by the structure), we need a hint regarding its type.

    Classes with this decorator will serialize into a tuple *(<tag>, { "data" })*
    instead of just *{ "data" }*, and when deserializing will use the *<tag>* to
    instanciate the appropriate class.
    """
    # if the class sets an explicit serialization tag, use that:
    tag = getattr(cls, 'serialization_tag', cls.__name__)
    cls.type = tag
    if not tag in tagged_serializables:
        tagged_serializables[tag] = cls
    return cls


def to_tagged(obj):
    """Serialize an object into a (<tag>, <data>) tuple.

    The class of the object needs to be registered in the module variable
    tagged_serializables.
    """
    tagged_classes = dict([(value, key) for key, value in tagged_serializables.items()])
    if obj.__class__ not in tagged_classes:
        errmsg = 'Class {} is not installed/registered as a glance result type plugin.'
        errmsg = errmsg.format(obj.__class__.__name__)
        log.error(errmsg)
        raise KeyError(errmsg)
    return tagged_classes[obj.__class__], obj.to_dict()


def from_tagged(s):
    """Deserialize an object from a (<tag>, <data>) tuple.

    The class of the object needs to be registerede in the module variable
    tagged_serializables.
    """
    tag, data = s
    if tag not in tagged_serializables:
        errmsg = 'Unknown result type {}. Maybe you need to install a glance-plugin.'
        errmsg = errmsg.format(tag)
        log.warn(errmsg)
        return TextResult(title='Unknown result type', status=stat.NEUTRAL, message=errmsg)
    else:
        return tagged_serializables[tag].from_dict(data)


def fix_multiindices(d):
    def fix_index(idx):
        if isinstance(idx[0], (list, tuple)):
            return pandas.MultiIndex.from_tuples([tuple(i) for i in idx])
        else:
            return idx
    for ind in ('columns', 'index'):
        d[ind] = fix_index(d[ind])
    return d


class Serializable(object):
    """Base class for serializable classes.

    Provides basic methods for turning an instance into a nested structure of
    Python-native objects (to_dict), turning a nested structure of native
    objects into an instance (from_dict), as well as methods to transform the
    nested structure during serialization(fix_dict) and deserialization
    (unfix_dict), to take care of non trivial data.

    gather() is a method that when called propagates the call to all objects
    in the attributes listed in the containers attribute.
    """
    children_attr = None
    externals = ()

    @classmethod
    def from_dict(cls, d):
        d = cls.unfix_dict(d.copy())
        externals = d.pop('_external', None)
        instance = cls(**d)
        instance._external = externals
        return instance

    def fix_dict(self, d):
        for attr in self.externals:
            d[attr] = None
        return d

    @staticmethod
    def unfix_dict(d):
        return d

    def to_dict(self):
        fixed = self.fix_dict(self.__dict__.copy())
        # remove keys that are added externally
        for key in ['_id', '_secid', '_blkid', '_resid', '_resources']:
            fixed.pop(key, None)
        return fixed

    def _get_externals(self, storage=None):
        if storage is not None:
            deprecate('The storage parameter is no longer needed or supported and will be removed in one of the next releases')
        # to avoid name collisions, we generate a (hopefully) unique id, and
        # add it to the original file name:
        if self.externals:
            data = dict([(attr, getattr(self, attr)) for attr in self.externals])
            # If this method has been called before, return the same values again
            if getattr(self, '_external', None) is not None:
                return self._external, data
            key = codecs.encode(os.urandom(4), 'hex').decode('utf8')
            self._external = key
            return key, data

    def _load_externals(self, resources):
        if self.externals and self._external:
            log.debug('Retrieving external resource %s', self._external)
            data = resources[self._external]
            for attr in self.externals:
                if attr in data:
                    setattr(self, attr, data[attr])

    def __getitem__(self, item):
        return getattr(self, self.children_attr)[item]

    def iter_children(self):
        if self.children_attr:
            for child in getattr(self, self.children_attr):
                yield child
                if isinstance(child, Serializable):
                    for grandchild in child.iter_children():
                        yield grandchild


class BaseResult(Serializable):
    """Base class for all result types"""

    @classmethod
    def from_dict(cls, d):
        try:
            return super(BaseResult, cls).from_dict(d)
        except Exception:
            errmsg = '\n'.join('    ' + line for line in traceback.format_exception_only(*sys.exc_info()[:2]))
            log.error('Error reading result:', exc_info=True)
            return TextResult(title='Error reading {}'.format(cls.__name__), status=stat.BAD,
                              message=errmsg)


@tagged
class TextResult(BaseResult):
    """Textual result.

    :param str title: Text displayed as the title of the element
    :param int status: (Optional) Status value from :mod:`glance.constants`.
        Other than a scalar, this can be a pandas Series or DataFrame,
        in which case the maximum (worst) status value will be used.
    :param str message: (Optional) Text to be displayed when the element is
        expanded. You can use markdown syntax here, which will be interpreted
        if the server can import the flask-markdown module.
    """

    def __init__(self, title, status=None, message=None):
        self.title = title
        self.message = message
        self.status = status_max(validate_status(status))


@tagged
class TableResult(BaseResult):
    """Tabular result.

    :param str title: Text displayed as the title of the element
    :param pandas.DataFrame data: The table data
    :param pandas.DataFrame statustable: (Optional) Table(s)
        containing the status values for elements of `data`. Can contain
        a DataFrame with only a subset of rows and columns of `data`.
        Can also be a list of such partial or complete DataFrames. Where
        they overlap, the individual maximum (worst) values are used.
    :param str format: (Optional) Format string that will be applied to all cells
        when the table is displayed.
    :param bool allow_data_export: Show option to download raw data in web UI (default: False).
    :param str features: Select UI features. Currently either 'all' (sort, paging etc.) or 'none'.
        """

    externals = ('data', 'statustable')

    def __init__(self, title, data, format=None, statustable=None, allow_data_export=False, features=None):
        self.title = title
        self.format = format
        self.statustable = combine_status(data, statustable)
        self.status = status_max(self.statustable)
        self.allow_data_export = allow_data_export
        self.features = features if features is not None else 'all'
        if data is not None:
            for colname, col in data.iteritems():
                col = col.copy()
                if col.dtype == 'O':  # potentially a str
                    for ind, v in col.iteritems():
                        if type(v) == binary_type:
                            col[ind] = v.decode('utf8')
                    data[colname] = col
        self.data = data

    # Most of this is only needed for reading reports generated with glance<=0.7.2
    @staticmethod
    def unfix_dict(d):
        d.pop('status', None)
        ctx = get_context()
        if ctx.current_file_format == 1:
            d['data'] = pandas.DataFrame(**fix_multiindices(d['data']))
        elif ctx.current_file_format == 0:
            d['data'] = pandas.DataFrame.from_dict(d['data'])
        if d.get('statustable') is not None:
            if ctx.current_file_format == 1:
                d['statustable'] = pandas.DataFrame(**fix_multiindices(d['statustable']))
            elif ctx.current_file_format == 0:
                d['statustable'] = pandas.DataFrame.from_dict(d['statustable'])
        return d

    def export_data(self):
        # returns the csv-formatted data, as binary string
        data = self.data.to_csv(index=False, encoding='utf8')
        if not isinstance(data, six.binary_type):
            data = data.encode('utf8')
        return data


@tagged
class ImageResult(BaseResult):
    """Image result.

    :param str file: file handle or path to the image file, or matplotlib figure handle
    :param str title: Title of the image result
    :param str filename: (Optional) Used as the filename in the web ui, eg. when linking
        to the file. Overrides a file name given in the `file` parameter or found in
        a file-like object or figure handle. If not given and no file name is supplied
        through the `file` parameter, one will be generated.
    """

    externals = ('data',)

    def __init__(self, file=None, title=None, filename=None, key=None):
        self.title = title
        self.key = key

        ctx = get_context()

        self._pre3 = False
        if (ctx.current_file_format is not None) and (ctx.current_file_format < 3):
            self._pre3 = True
            self.file = file
            return

        # file can be one of several kinds of objects:
        # 1. The name of a file in the local file system:
        if isinstance(file, compat.string_types):
            fh = open(file, mode='rb')
            self.filename = slugify(filename or os.path.basename(file))
            self.data = fh.read()
        # 2. A matplotlib figure handle:
        elif hasattr(file, 'savefig'):  # just check if the method is there
            imgdata = BytesIO()
            file.savefig(imgdata, format='png')
            self.data = imgdata.getvalue()
            if filename is not None:
                self.filename = slugify(filename)
            elif file.gca().title.get_text():
                self.filename = slugify(file.gca().title.get_text())
            else:
                self.filename = 'plot.png'
        # 3. An object with a .read() method (file-like):
        elif hasattr(file, 'read'):
            fh = file
            if hasattr(fh, 'title'):
                self.filename = slugify(fh.title())
            else:
                self.filename = slugify(title)
            self.data = fh.read()
        else:
            self.filename = slugify(filename)

    def _load_externals(self, resources):
        # once we stop supporting pre-v3 data, this method can go. It is just there to
        # passivate the method for pre-v3 data
        if not self._pre3:
            super(ImageResult, self)._load_externals(resources)

    @staticmethod
    def unfix_dict(d):
        d.pop('data', None)
        return d

    def fix_dict(self, d):
        d = super(ImageResult, self).fix_dict(d)
        d.pop('_pre3', None)
        return d

    def open(self, storage, reportid, runid):
        if self._pre3:
            respath = os.path.join(reportid, runid, 'resources', self.file)
            return storage.open(respath, mode='rb')

        return BytesIO(self.data)


@tagged
class PlotResult(BaseResult):
    """Result data to be displayed as a plot.

    :param str title: Text displayed as the title of the plot
    :param pandas.DataFrame data: The data to be shown. Each column will be
      shown as a line.
    :param bool allow_data_export: Show option to download raw data in web UI (default:
      False).
    """

    externals = ('data',)

    def __init__(self, title, data, allow_data_export=False):
        self.title = title
        self.data = ensure_dataframe(data)
        self.allow_data_export = allow_data_export

    # This method is only needed for reading reports generated with glance<=0.7.2
    @staticmethod
    def unfix_dict(d):
        ctx = get_context()

        if ctx.current_file_format == 1:
            d['data'] = pandas.DataFrame(**d['data'])
        elif ctx.current_file_format == 0:
            d['data'] = pandas.DataFrame.from_dict(d['data'])
        return d

    def render_html(self):
        from bokeh import plotting as bk
        from bokeh.embed import components

        x_axis_type = 'auto'
        if isinstance(self.data.index, pandas.DatetimeIndex):
            x_axis_type = 'datetime'

        p = bk.figure(
            title=self.title,
            tools="pan,wheel_zoom,box_zoom,reset,hover,save",
            plot_width=600,
            plot_height=265,
            x_axis_type=x_axis_type
        )
        p.sizing_mode = 'scale_width'

        css_color_names = 'crimson dodgerblue forestgreen goldenrod hotpink lightseagreen lightslategray'
        colors = itertools.cycle(col for col in css_color_names.split())

        for col in self.data:
            s = self.data[col]
            p.line(
                x=s.index.values,
                y=s.values,
                legend=s.name,
                color=next(colors),
                line_width=2,
                line_join='round')  # color = cls[i]

        p.grid.grid_line_alpha = 0.3
        p.xaxis.axis_label = self.data.index.name

        # return '\n'.join(bokeh.embed.components(bk.curplot(), bokeh.resources.CDN))
        script, div = components(p)
        return div + '\n' + script

    def export_data(self):
        # returns the csv-formatted data, as binary string
        data = self.data.to_csv(index=False, encoding='utf8')
        if not isinstance(data, six.binary_type):
            data = data.encode('utf8')
        return data


@tagged
class VegaChart(BaseResult):
    """A chart in vega or vega-lite form"""

    def __init__(self, chart=None, height=None, json=None):
        if chart is not None:
            buf = StringIO()
            chart.save(buf, format='json')
            json = buf.getvalue()

        self.height = height
        self.json = json

    def export_json(self):
        return self.json


@tagged
class StaticResult(BaseResult):
    """Pre-rendered result that will be included verbatim.

    :param str title: Text displayed as the title
    :param str content: Content to be embedded in the page"""

    def __init__(self, title, content, status=None):
        self.title = title
        self.content = content
        self.status = status_max(validate_status(status))


class Block(Serializable):
    """A Block grouping all individual results related to one check.

    :param str title: Text displayed as the title of the block
    :param list results: Results contained in this block
    :param int status: (Optional) Overall status of this check. If not given, is set to
      maximum of the status attributes of all results.
    :param str description: (Optional) Longer description of the check.
      Probably not displayed to the user initially, but only when they click
      on a "details" button.
    :param bool emphasize: (Optional) True if info-panel style is to be used when rendering the block marking it
                                         with a grey bar and bold text.
    :param tuple link: (Optional) A tuple like `(endpoint_id, path, text)`. The web UI can
      show a link with the text `text` pointing to the URL constructed from a base-URL + the `path`.
      The glance server is configured with a list of `endpoint_id`s and base-URLs`.
    """
    children_attr = 'results'

    def __init__(self, title, results, status=None, tags=None, description=None, emphasize=False, link=None):
        def assert_resulttype(res):
            # TODO: Now we fail hard if it's not a Serializable subclass and warn if
            #   it's not a BaseResult subclass. Once we reach 1.0.0, change this to
            #   BaseResult and remove the deprecation warning
            if not isinstance(res, Serializable):
                classname = BaseResult.__module__ + BaseResult.__name__
                raise TypeError('Results in a Block need to be subclasses of ' + classname)
            if not isinstance(res, BaseResult):
                dc.deprecate(
                    'Custom result types not subclassing glance.report.BaseResult are '
                    'unsupported',
                    message=res.__class__.__name__ + ' does not subclass glance.report.BaseResult',
                    removal_version='1.0.0')
            return res

        self.title = title
        self.results = [assert_resulttype(res) for res in results]
        self.description = description
        self.emphasize = emphasize
        if link is None or isinstance(link, dict):
            self.link = link
        else:
            self.link = dict(zip(['endpoint_id', 'path', 'text'], link))
        if status is None:
            statorneutral = lambda resu: getattr(resu, 'status', None) or stat.NEUTRAL
            self.status = max(status_max(statorneutral(res)) for res in self.results)
        else:
            self.status = validate_status(status)

        if tags:
            if isinstance(tags, compat.string_types):
                tags = [tags]
            self.tags = list(set(tags))
        else:
            self.tags = []

    def fix_dict(self, d):
        d['results'] = [to_tagged(result) for result in d['results']]
        return d

    @staticmethod
    def unfix_dict(d):
        d['results'] = [from_tagged(data) for data in d['results']]
        return d


class Section(Serializable):
    """A Section groups a number of checks to separate them visually

    :param str title: Text displayed as the title of the section
    :param list blocks: Blocks contained in this section
    :param str description: (Optional) Longer description of the Section.
      Probably not displayed to the user initially, but only when they click
      on a "details" button.
    :param bool always_expand: (deprecated) True if Section should be expanded by default
    """
    children_attr = 'blocks'

    @removed_kwarg('always_expand', removal_version='1.0.0')
    def __init__(self, title, description='', blocks=[], always_expand=False):
        def assert_block(blok):
            if not isinstance(blok, Block):
                classname = Block.__module__ + Block.__name__
                raise TypeError('Blocks in a Section need to be instances of ' + classname)
            return blok

        self.title = title
        self.description = description
        self.blocks = [assert_block(blk) for blk in blocks]
        self.always_expand = always_expand

    def fix_dict(self, d):
        d['blocks'] = [block.to_dict() for block in d['blocks']]
        d.pop('always_expand', None)  # Remove before 1.0.0
        return d

    @staticmethod
    def unfix_dict(d):
        d['blocks'] = [Block.from_dict(data) for data in d['blocks']]
        return d


class Report(Serializable):
    """Bundle of checks that are run at the same time and should be displayed
    together

    :param str title: Text displayed as the title of the report (toplevel, all runs)
    :param list sections: Sections contained in this report
    :param str runtitle: (Optional, default: `runid`) Title of this run, displayed e.g. in the navbar. If
      not set, the timestamp will be used in place of this.
    :param str runid: (Optional, default: `timestamp`) Identity- and sequence key for this particular run. Will be used
      as sorting key, eg. in the navbar.
    :param datetime.datetime timestamp: (default: now) When the report
      was generated.
    """
    children_attr = 'sections'
    slug_fmt = '%Y_%m_%d_%H_%M_%S'

    @classmethod
    def timestamp_from_runid(cls, runid):
        return datetime.strptime(runid, cls.slug_fmt)

    def __init__(self, title='', sections=[], runtitle=None, runid=None, timestamp=None):
        def assert_section(sec):
            if not isinstance(sec, Section):
                classname = Section.__module__ + Section.__name__
                raise TypeError(
                    'Sections in a Report need to be instances of ' + classname)
            return sec

        self.title = title
        self.sections = [assert_section(sec) for sec in sections]
        self.id = slugify(self.title)
        if timestamp is None:
            timestamp = datetime.now()
        self.timestamp = timestamp
        self.runid = slugify(runid) if runid else timestamp.strftime(self.slug_fmt)

        if runtitle:
            self.runtitle = runtitle
        elif runid:
            self.runtitle = runid
        else:
            self.runtitle = self.timestamp.strftime('%Y-%m-%d %H:%M:%S')

    @staticmethod
    def from_storage(metafilename, storage):
        log.debug('Loading report object from %s', metafilename)
        ctx = get_context()

        metafile = storage.open(metafilename)
        parsed = yaml.safe_load(metafile)
        metafile.close()
        # if the file contains format version information, write that
        # into the global state
        if isinstance(parsed, collections.Sequence):
            header, reportdata = parsed
            ctx.current_file_format = header['version']
            if ctx.current_file_format < 3:
                dc.deprecate('This file format is no longer supported', removal_version='1.0.0')
        # if not, assume older version
        else:
            dc.deprecate('This file format is no longer supported', removal_version='1.0.0')
            reportdata = parsed
            ctx.current_file_format = 0
        report = Report.from_dict(reportdata)

        # Let the reportid actually used in the storage overwrite the one derived
        # from the title:
        storage_id = split_key(metafilename)[-4]
        report.id = storage_id
        report._set_element_ids()
        report.load_resources(storage)
        return report

    def _set_element_ids(self):
        """Assign element IDs that can be used to address individual results, blocks
        and sections"""
        for isec, sec in enumerate(self):
            sec._secid = isec
            sec._id = str(isec)
            for iblk, blk in enumerate(sec):
                blk._secid = isec
                blk._blkid = iblk
                blk._id = '-'.join(map(str, (isec, iblk)))
                for ires, res in enumerate(blk):
                    res._secid = isec
                    res._blkid = iblk
                    res._resid = ires
                    res._id = '-'.join(map(str, (isec, iblk, ires)))

    def fix_dict(self, d):
        DATETIME_FORMAT = '%Y-%m-%d %H:%M:%S.%f'
        d['sections'] = [section.to_dict() for section in d['sections']]
        d['timestamp'] = d['timestamp'].strftime(DATETIME_FORMAT)
        del d['id']
        return d

    @staticmethod
    def unfix_dict(d):
        DATETIME_FORMAT = '%Y-%m-%d %H:%M:%S.%f'
        OLD_FORMAT = '%Y-%m-%d %H:%M:%S'
        d['sections'] = [Section.from_dict(data) for data in d['sections']]
        try:
            d['timestamp'] = datetime.strptime(d['timestamp'], DATETIME_FORMAT)
        except (ValueError,):
            d['timestamp'] = datetime.strptime(d['timestamp'], OLD_FORMAT)
        d.pop('description', None)  # Remove deprecated attribute, if present
        return d

    def store(self, storage):
        """Serialize and write the report to disk

        All contents of this report will be serialized and written to storage
        in a newly created subdirectory underneath the directory given in
        *path*.
        This method also stores other resources like image files referenced in
        :class:`~ImageResult` s.

        :param storage: Storage root. Should be a `simplekv.KeyValueStore`.
        """
        basekey = join_key(self.id, self.runid)
        mainkey = join_key(basekey, 'report.json')
        reskey = join_key(basekey, 'res')

        # 1. if target already exists, delete
        storage.delete(mainkey)
        storage.delete(reskey)

        # 2. collect externals
        resources = [elem._get_externals() for elem in self.iter_children()]
        resources = dict(e for e in resources if e)

        try:
            #   3. store externals
            storage.put(reskey, pickle.dumps(resources, protocol=2))

            #   4. store report.json
            header = {'version': format_version}  # add format version info
            native = self.to_dict()
            json_opts = dict(sort_keys=True, indent=4, separators=(',', ': '))
            json_str = json.dumps([header, native], **json_opts)
            if not PY2:
                json_str = json_str.encode('utf-8')
            storage.put(mainkey, json_str)

            #   5. add to index
            _add_to_index(storage, self.id, self.runid, self.runtitle,
                          self.timestamp, self.title, self.status_stats())
            check_and_repair(storage=storage, reportid=self.id)

        except (IOError, ValueError):
            etype, evalue, etb = sys.exc_info()
            #   6. remove target
            try:
                storage.delete(reskey)
            except (IOError, ValueError):
                # make sure we attempt deleting the second key even if the first fails:
                pass
            storage.delete(basekey)
            reraise(etype, evalue, etb)

    def build_resourcepath(self):
        resourcepath = os.path.join(self.build_basepath(), 'resources')
        return resourcepath

    def build_basepath(self):
        reportpath = os.path.join(self.id, self.runid)
        return reportpath

    def load_resources(self, storage):
        oldkey = OLD_KEY_SEPARATOR.join([self.id, self.runid, 'res'])
        newkey = NEW_KEY_SEPARATOR.join([self.id, self.runid, 'res'])
        if oldkey in storage:
            reskey = oldkey
        else:
            reskey = newkey
        if reskey in storage:
            resources = pandas.read_pickle(BytesIO(storage.get(reskey)), compression=None)
            self._resources = resources
            for child in self.iter_children():
                child._load_externals(resources)

    def iter_blocks(self, min_badness=stat.NEUTRAL, with_all_indices=False):
        blockcount = 0
        for sind, section in enumerate(self):
            for bind, block in enumerate(section):
                block.blockind = blockcount
                blockcount += 1
                if block.status >= min_badness:
                    if with_all_indices:
                        yield sind, bind, blockcount, block.title
                    else:
                        yield block

    def worst_status(self):
        """Return the worst status value in this report."""
        return max(blk.status for blk in self.iter_blocks())

    def status_stats(self):
        count = collections.Counter(blk.status for blk in self.iter_blocks())
        stats = dict((k, count[k]) for k in stat.status_names.keys())
        return stats

    def get_element(self, section, block=None, result=None):
        sec = self.sections[section]
        if block is None:
            return sec
        blk = sec.blocks[block]
        if result is None:
            return blk
        return blk.results[result]

    def element_match(self, pattern):
        # match using fnmatch.fnmatch()
        return _util.find_in_report(self, pattern, '*', title_fnmatch)

    def element_re(self, pattern):
        # match by looking for RE-matches
        return _util.find_in_report(self, pattern, '', title_re_match)


def ttlcache(ttl_seconds=30):
    """Caching decorator that caches function results for a certain time"""

    def cache_decorator(func):
        func.max_age = timedelta(seconds=ttl_seconds)
        func.cache_time = datetime.now() - func.max_age - timedelta(seconds=1)
        func.cache = None

        @functools.wraps(func)
        def wrapped(*args, **kwargs):
            ttlcache = kwargs.pop('ttlcache', True)
            if ttlcache:
                cache_age = datetime.now() - func.cache_time
                if cache_age > func.max_age:
                    func.cache = func(*args, known=func.cache, **kwargs)
                    func.cache_time = datetime.now()
                return func.cache
            else:
                return func(*args, **kwargs)
        return wrapped
    return cache_decorator


def read_report(storage, reportid, runid):
    metafilename = os.path.join(reportid, runid, 'report.json')
    if metafilename in storage:
        tstart = datetime.now()
        try:
            report = Report.from_storage(metafilename, storage)
        except (Exception, YAMLError) as e:
            log.error('Error reading report', exc_info=True)
            exc_str = traceback.format_exception_only(type(e), e)
            raise IOError('Error reading %s / %s: %s' % (reportid, runid, exc_str))
        duration = (datetime.now() - tstart)
        log.info(
            'read_report({0}, {1}) [{2.seconds:d}.{2.microseconds:06d}s]'.format(reportid,
                                                                                 runid,
                                                                                 duration))
        return report
    else:
        raise IOError('report id %s, runid %s not found', reportid, runid)


@ttlcache()
def findreports(storage, known=None):
    """Walk the storage and return a nested data structure with all
    monitoring reports found. If you have already called this function earlier,
    you can provide its last return value in the parameter `known` which avoids
    reading the same data again. Only new reports/runs will be added.

    :param :class:`fs.base.FS` storage: Storage instance
    :param known: (optional) reports found earlier
    """
    # Are we starting from scratch?
    if known:
        reports = known
    else:
        reports = {}

    start = datetime.now()
    ind = 0
    log.debug('Starting to read reports')
    for reportid in list_reports(storage):
        # Can we find this report in the old dict?
        if reportid not in reports:
            thisreport = {'title': '', 'id': '', 'runs': {}}
        else:
            thisreport = reports[reportid]

        for runid in list_runs(storage, reportid):
            metakeyname = join_key(reportid, runid, 'report.json')
            if runid not in thisreport['runs'] and (metakeyname in storage):
                log.debug('Start reading ' + metakeyname)
                ind += 1
                readstart = datetime.now()
                report = Report.from_storage(metakeyname, storage)
                deltat = (datetime.now() - readstart)
                log.info(' Done reading {0}, took {1.seconds:d}.{1.microseconds:06d}s'.format(metakeyname, deltat))
                thisreport['runs'][runid] = report
                thisreport['title'] = report.title
                thisreport['id'] = report.id
        if len(thisreport['runs']) > 0:
            reports[reportid] = thisreport
    deltat = (datetime.now() - start).seconds
    log.info('Finished reading reports. Read {} reports in {} seconds'.format(ind, deltat))
    return reports


def register_plugins():
    from pkg_resources import iter_entry_points, resource_filename
    for entry_point in iter_entry_points(group='glance.resulttype', name=None):
        ep_module = entry_point.module_name
        template_path = resource_filename(ep_module, 'templates')
        if template_path not in plugin_template_paths:
            plugin_template_paths.append(template_path)
            log.debug('Added template path %s from %s', template_path, ep_module)

        static_path = resource_filename(ep_module, 'static')
        if static_path not in plugin_static_paths:
            plugin_static_paths[ep_module] = static_path

        cls = entry_point.load()  # nosec
        if not issubclass(cls, BaseResult):
            dc.deprecate('Custom result types not subclassing glance.report.BaseResult are unsupported',
                message=cls.__name__ + ' does not subclass glance.report.BaseResult',
                removal_version='1.0.0')
        log.debug('Loaded additional result type %s from %s', cls.__name__, repr(ep_module))

        if hasattr(cls, "static_links"):
            plugin_static_links.extend([dict(link, module=ep_module) for link in cls.static_links()])

        tagged(cls)


register_plugins()
