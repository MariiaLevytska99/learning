# -*- coding: utf-8 -*-

from __future__ import absolute_import
import re
from unicodedata import normalize
import collections
import logging
import warnings

warnings.filterwarnings('module', module='glance')

import numpy as np
import pandas
from debtcollector import moves

from glance.constants import NEUTRAL, GOOD, WARNING, BAD, status_names
from .core.compat import text_type, binary_type

log = logging.getLogger(__name__)


_punct_re = re.compile(br'\W+')
_spaces_re = re.compile(br'\s+')

german_chars = {u'Ä': 'Ae', u'Ö': 'Oe', u'Ü': 'Ue', u'ä': 'ae', u'ö': 'oe',
                    u'ü': 'ue', u'ß': 'ss'}
umap = {ord(key): text_type(val) for key, val in german_chars.items()}


def slugify(text, delim='-', default_char='_'):
    """Generates a slightly worse ASCII-only slug.

    :param str text: The string to be slugified
    :param str delim: The delimiter that will connect 'word-like' sections in the slug (default: `-`)
    :param str default_char: The character that will be used to replace non-ascii characters that can not be normalized to ascii (default: `_`)

    :returns: A string of only lowercase ascii letters and digits, `delim` and `default_char`
    """
    result = []
    sanitized = normalize('NFKD', text_type(text).translate(umap))
    sanitized_ascii = sanitized.encode('ascii', 'ignore')
    for word in _punct_re.split(sanitized_ascii):
        word = word.lower()
        # handle characters lost in the ascii encoding (end up as space characters):
        word = _spaces_re.sub(default_char, word)
        result.append(word.decode('ascii'))
    return delim.join(result)


def _df_locations(df):
    """Return a sequence of (irow, icol) for each True value in df"""
    irow = pandas.DataFrame(list(df.columns) * len(df.index))  # sequence of col-indices
    icol = pandas.DataFrame(df.index.repeat(len(df.columns)))  # sequence of row-indices
    coltrue = irow[df.values.flatten()]  # col-indices where df is true
    rowtrue = icol[df.values.flatten()]  # row-indices where df is true
    return _array2tuple(np.hstack((rowtrue, coltrue)))   # numpy-equivalent of zip() -> [[r0,c0], [r1,c1], ...]


def _array2tuple(a):
    """Turn a two-dimensional numpy array into a tuple of tuples ((), (), ...)"""
    return tuple(tuple(elem for elem in row) for row in a)


def status_max(data):
    """If the argument is a pandas DataFrame, return the maximum,
    otherwise return the argument itself"""
    data = validate_status(data)
    if data is None:
        return None
    if isinstance(data, pandas.DataFrame):
        flat = data.values.flatten()
        if len(flat) > 0:
            return int(flat.max())
        else:
            return None
    else:
        return int(data)


pandas_max = moves.moved_function(
    status_max, 'pandas_max', __name__, removal_version='1.0.0')


def validate_status(stat, replace_invalid=None):
    """Make sure a scalar or DataFrame only contains valid status values.
    NaN values are silently mapped to :const:NEUTRAL.

    If :param:replace_invalid is not given, invalid values cause a :exception:ValueError
    to be raised. Otherwise, invalid values will be replaced
    with the value of :param:`replace_invalid`, and a warning will be logged."""

    # Internal function for making a verbose error message:
    def format_message(invalid):
        badlocs = _df_locations(invalid)  # Locate bad values
        ninvalid = invalid.values.sum()
        firstrow, firstcol = badlocs[0]  # Pick out the first one as an example
        badval = stat.iloc[firstrow, firstcol]
        valmsg = '{} in row {}(#{}), col {}(#{})'.format(
            badval,
            stat.index[firstrow], firstrow,
            stat.columns[firstcol], firstcol)
        if ninvalid == 1:
            msg = 'Invalid status found: ' + valmsg
        else:
            msg = 'Found ' + str(
                ninvalid) + ' invalid status values. First one: ' + valmsg + '. '
        badcols = list(
            set(str(invalid.columns[badcol]) for badcol, _ in
                badlocs))  # Find all columns containing bad values
        if len(badcols) > 1:
            colmsg = str(len(badcols)) + ' columns contain bad status values: '
        else:
            colmsg = 'One column contains bad status values: '
        colmsg += ', '.join(badcols)
        msg += colmsg
        return msg

    valid_values = list(status_names.keys())
    if isinstance(stat, pandas.DataFrame):
        stat = stat.where(~stat.isnull(), other=NEUTRAL)  # NaNs are acceptable ⇨ set to NEUTRAL
        invalid = ~stat.isin(valid_values)   # Find invalid status values
        ninvalid = invalid.values.sum()
        if ninvalid > 0:
            msg = format_message(invalid)
            log.warning(msg)
            if replace_invalid is None:
                raise ValueError(msg)
            stat = stat.where(~invalid, other=replace_invalid)
    else:
        if stat is None:
            stat = NEUTRAL
        if isinstance(stat, np.integer):
            stat = int(stat)
        good = stat in valid_values
        if not good:
            msg = 'Invalid status: {} {}'.format(stat, type(stat))
            log.warning(msg)
            if replace_invalid is None:
                raise ValueError(msg)
            stat = replace_invalid
    return stat


def ensure_dataframe(data):
    """Accept number (int, float), Series, or DataFrame and always return a DataFrame"""
    if isinstance(data, pandas.DataFrame):
        return data
    if isinstance(data, pandas.Series):
        return data.to_frame()
    if isinstance(data, (int, float)) or data is None:
        return pandas.DataFrame([data])
    raise TypeError("Can't handle something of type {}".format(type(data)))


def combine_status(ref, statuslist):
    """Overlay a list of Series and DataFrames into one DataFrame according
    to a reference shape

    Combines the Series and DataFrame objects in statuslist into one DataFrame
    which has the same index and columns as ref. Where the objects overlap,
    takes the maximum.
    """
    if ref is None:
        return None

    if not isinstance(statuslist, collections.Sequence):
        statuslist = [statuslist]
    statuslist = [validate_status(ensure_dataframe(d)) for d in statuslist]

    status = pandas.DataFrame(index=ref.index, columns=ref.columns, dtype=int).fillna(NEUTRAL)

    refcols = set(ref.columns)
    refind = set(ref.index)

    notnone = lambda v: v is not None

    for overlay in filter(notnone, statuslist):
        ocols = set(overlay.columns)
        oind = set(overlay.index)

        direct_match = ocols.issubset(refcols) and oind.issubset(refind)
        rot_match = oind.issubset(refcols) and ocols.issubset(refind)

        if rot_match and not direct_match:
            overlay = overlay.T

        if rot_match or direct_match:
            combined = pandas.concat([status, overlay], sort=True)
            status = combined.groupby(combined.index).max().astype(int)
    return status
