from __future__ import absolute_import
from collections import namedtuple

import six

import numpy as np
import pandas as pd

from .constants import NEUTRAL, GOOD, WARNING, BAD
from .utils import ensure_dataframe


class CheckResult(namedtuple('CheckResult', ['description', 'message', 'status'])):
    """Result of a single check. Implemented as a :obj:`~python:collections.namedtuple`

    .. attribute:: description

        Description of the check. Generally displayed as a title in the web UI

    .. attribute:: message

        Optional message containing extra information about the results

    .. attribute:: status

        Scalar, :class:`~pandas.Series` or :class:`~pandas.DataFrame` containing the status
        of each checked element
    """


def _setup_threshold(data, threshold):
    """
    Convert threshold to an object that can be compared by pandas.

    If ``data`` is a Series, the return value will be a Series w/ identical index. If ``data`` is a DataFrame, the
    return value will a DataFrame w/ identical index, column names and column order.

    For object column in ``data``, strings will be converted to None since the cannot be compared numerically.

    :param data: The data to be checked
    :type data: :class:`~pandas.Series` or :class:`~pandas.DataFrame`
    :param threshold: Maximum allowed value. Values in *data*
        greater than this will be labeled as :const:`~glance.constants.BAD`
    :type threshold: scalar
    :returns: Converted/adjusted threshold
    """
    def _convert(series, threshold):
        result = pd.Series(threshold, dtype=series.dtype, index=series.index)
        if result.dtype == object:
            result[
                series.apply(
                    lambda x: isinstance(x, six.string_types)
                )
            ] = None
        return result

    if isinstance(data, pd.Series):
        threshold = _convert(data, threshold)

    elif isinstance(data, pd.DataFrame):
        threshold = pd.DataFrame(
            data={
                col: _convert(data[col], threshold)
                for col in data.columns
            },
            columns=data.columns,
            index=data.index,
        )
    return threshold


def below(data, threshold, warn_threshold=None):
    """Check if all elements are at or below a threshold

    :param data: The data to be checked
    :type data: :class:`~pandas.Series` or :class:`~pandas.DataFrame`
    :param threshold: Maximum allowed value. Values in *data*
        greater than this will be labeled as :const:`~glance.constants.BAD`
    :param warn_threshold: Maximum :const:`~glance.constants.GOOD` values. Values greater
        than this will be labeled as :const:`~glance.constants.WARNING`
    :return: Results of the check
    :rtype: :class:`~CheckResult`
    """
    data = ensure_dataframe(data)

    name = u', '.join(map(six.text_type, data.columns))

    if len(data.values[:]) == 1:
        scalar = True
    else:
        scalar = False

    messages = []

    res = pd.DataFrame(GOOD, index=data.index, columns=data.columns, dtype=int)
    if warn_threshold is not None:
        res[data > _setup_threshold(data, warn_threshold)] = WARNING
    res[data > _setup_threshold(data, threshold)] = BAD

    if scalar:
        description = u'Check if {name} is <= {threshold}.'.format(name=name, threshold=threshold)
        if (res == BAD).values.flatten().any():
            messages.append(u'{} is too large (>{})'.format(data.values[0], threshold))
        if (res == WARNING).values.flatten().any():
            messages.append(u'{} is quite large (>{})'.format(data.values[0], warn_threshold))
    else:
        description = u'Check if all values in {name} are <= {threshold}.'.format(name=name, threshold=threshold)

        nall = len(res)
        if (res == BAD).values.flatten().any():
            nbad = int((res == BAD).values.flatten().sum())
            messages.append(
                u'{n:d} of {nall:d} values ({perc:f}%) are above {thresh} (largest value: {max})'.format(
                    n=nbad, nall=nall, perc=100.0 * nbad / nall, thresh=threshold, max=data.max()))
        if (res == WARNING).values.flatten().any():
            nwarn = (res == WARNING).values.flatten().sum()
            messages.append(u'{n} of {nall} values ({perc:f}%) are quite large (>{thresh})'.format(
                n=nwarn, nall=nall, perc=100.0 * nwarn / nall, thresh=warn_threshold))

    return CheckResult(description, u'\n'.join(messages), res)


def above(data, threshold, warn_threshold=None):
    """Check if all elements are at or above a threshold

    :param data: The data to be checked
    :type data: :class:`~pandas.Series` or :class:`~pandas.DataFrame`
    :param threshold: Minimum allowed value. Values in *data*
        smaller than this will be labeled as :const:`~glance.constants.BAD`
    :param warn_threshold: Minimum :const:`~glance.constants.GOOD` values. Values smaller
        than this will be labeled as :const:`~glance.constants.WARNING`
    :return: Results of the check
    :rtype: :class:`~CheckResult`
    """
    data = ensure_dataframe(data)

    name = u', '.join(map(six.text_type, data.columns))

    if len(data.values[:]) == 1:
        scalar = True
    else:
        scalar = False

    messages = []

    res = pd.DataFrame(GOOD, index=data.index, columns=data.columns, dtype=int)
    if warn_threshold is not None:
        res[data < _setup_threshold(data, warn_threshold)] = WARNING
    res[data < _setup_threshold(data, threshold)] = BAD

    if scalar:
        description = u'Check if {name} is >= {threshold}.'.format(name=name, threshold=threshold)
        if (res == BAD).values.flatten().any():
            messages.append(u'{} is too small (<{})'.format(data.values[0], threshold))
        if (res == WARNING).values.flatten().any():
            messages.append(u'{} is quite small (<{})'.format(data.values[0], warn_threshold))
    else:
        description = u'Check if all values in {name} are >= {threshold}.'.format(name=name, threshold=threshold)
        nall = len(res)
        if (res == BAD).values.flatten().any():
            nbad = int((res == BAD).values.flatten().sum())
            messages.append(
                u'{n:d} of {nall:d} values ({perc:f}%) are below {thresh} (smallest value: {min})'.format(
                    n=nbad, nall=nall, perc=100.0 * nbad / nall, thresh=threshold,
                    min=data.min()))
        if (res == WARNING).values.flatten().any():
            nwarn = (res == WARNING).values.flatten().sum()
            messages.append(
                u'{n} of {nall} values ({perc:f}%) are quite small (<{thresh})'.format(
                    n=nwarn, nall=nall, perc=100.0 * nwarn / nall, thresh=warn_threshold))
    return CheckResult(description, u'\n'.join(messages), res)


def all_equal(data, value=True):
    """Check if all elements have a certain value

    :param data: The data to be checked
    :type data: :class:`~pandas.Series` or :class:`~pandas.DataFrame`
    :param value: Reference value. Values in *data*
        equal to this will be labeled as :const:`~glance.constants.GOOD`, all others
        as :const:`~glance.constants.BAD`
    :return: Results of the check
    :rtype: :class:`~CheckResult`
    """
    data = ensure_dataframe(data)

    name = u', '.join(map(six.text_type, data.columns))

    if len(data.values[:]) == 1:
        scalar = True
    else:
        scalar = False

    messages = []

    res = pd.DataFrame(GOOD, index=data.index, columns=data.columns, dtype=int)
    res[data != _setup_threshold(data, value)] = BAD

    if scalar:
        description = u'Check if {name} == {value}.'.format(name=name, value=value)
        if (res == BAD).values.flatten().any():
            messages.append(u'{} is not == {}'.format(data.values[0], value))
    else:
        description = u'Check if all values in {name} are == {value}.'.format(name=name, value=value)
        if (res == BAD).values.flatten().any():
            messages.append(u'Some values are not == {}'.format(value))
    return CheckResult(description, u'\n'.join(messages), res)


def inrange(data, lower=None, upper=None, lower_warn=None, upper_warn=None):
    """Check if all elements are within a given range

    :param data: The data to be checked
    :type data: :class:`~pandas.Series` or :class:`~pandas.DataFrame`
    :param lower: Minimum allowed value. Values in *data*
        smaller than this will be labeled as :const:`~glance.constants.BAD`
    :param lower_warn: Minimum :const:`~glance.constants.GOOD` values. Values smaller
        than this will be labeled as :const:`~glance.constants.WARNING`
    :param upper: Maximum allowed value. Values in *data*
        greater than this will be labeled as :const:`~glance.constants.BAD`
    :param upper_warn: Maximum :const:`~glance.constants.GOOD` values. Values greater
        than this will be labeled as :const:`~glance.constants.WARNING`

    :return: Results of the check
    :rtype: :class:`~CheckResult`
    """
    if lower is None and lower_warn is None:
        raise ValueError(
            u'Both arguments \'lower\' and \'lower_warn\' are given as `None`')
    elif upper is None and upper_warn is None:
        raise ValueError(
            u'Both arguments \'upper\' and \'upper_warn\' are given as `None`')

    data = ensure_dataframe(data)

    name = u', '.join(map(six.text_type, data.columns))

    if len(data.values[:]) == 1:
        scalar = True
    else:
        scalar = False

    messages = []

    res = pd.DataFrame(GOOD, index=data.index, columns=data.columns, dtype=int)
    if lower_warn is not None:
        res[data < _setup_threshold(data, lower_warn)] = WARNING
    if upper_warn is not None:
        res[data > _setup_threshold(data, upper_warn)] = WARNING
    if lower is not None:
        res[data < _setup_threshold(data, lower)] = BAD
    if upper is not None:
        res[data > _setup_threshold(data, upper)] = BAD

    if scalar:
        description = u'Check if {} is in the range [{}, {}].'.format(name, lower, upper)
        if (res == BAD).values.flatten().any():
            messages.append(u'{} is outside of the range [{}, {}]'.format(data.values[0], lower, upper))
        if (res == WARNING).values.flatten().any():
            messages.append(u'{} is quite extreme (<{} or >{})'.format(data.values[0], lower_warn, upper_warn))
    else:
        description = u'Check if all values for {} are in the range [{}, {}].'.format(name, lower, upper)
        if (res == BAD).values.flatten().any():
            messages.append(u'Some values are outside of the range [{}, {}]'.format(lower, upper))
        if (res == WARNING).values.flatten().any():
            messages.append(u'Some values are in range, but might require attention (<{} or >{})'.format(lower_warn, upper_warn))
    return CheckResult(description, u'\n'.join(messages), res)


def monotonous(data, strict=False):
    """Check if all elements of a *pandas.Series* rise or fall monotonously

    :param data: The data to be checked
    :type data: :class:`~pandas.Series` or :class:`~pandas.DataFrame`
    :param bool strict: Require strict monotonicity

    :return: Results of the check
    :rtype: :class:`~CheckResult`
    """
    strictly = u' strictly' if strict else u''
    description = u'Check if the values in {} rise/fall{} monotonously'.format(data.name, strictly)

    res = pd.Series(GOOD, index=data.index, dtype=int)
    res.iloc[0] = NEUTRAL

    direction = pd.Series(np.sign(data.diff()), index=data.index)
    if not strict:
        direction[direction == 0] = np.nan
        direction.ffill(inplace=True)
    dirchange = pd.Series(np.sign(direction.diff()), index=data.index)
    bad = dirchange.fillna(0) != 0

    res[bad] = BAD

    if (res == BAD).values.flatten().any():
        message = u'{} is not{} monotonous in some places'.format(data.name, strictly)
    else:
        message = u''
    return CheckResult(description, message, res)


def ratio_range(data, lower, upper, lower_warn=None, upper_warn=None):
    """Check if the successive ratios (x :sub:`i` / x :sub:`i-1`) of all elements are within a given range

    :param pandas.Series data: The data to be checked
    :param lower: Minimum allowed value. Values in *data*
        smaller than this will be labeled as :const:`~glance.constants.BAD`
    :param lower_warn: Minimum :const:`~glance.constants.GOOD` values. Values smaller
        than this will be labeled as :const:`~~glance.constants.WARNING`
    :param upper: Maximum allowed value. Values in *data*
        greater than this will be labeled as :const:`~glance.constants.BAD`
    :param upper_warn: Maximum :const:`~glance.constants.GOOD` values. Values greater
        than this will be labeled as :const:`~~glance.constants.WARNING`

    :return: Results of the check
    :rtype: :class:`~CheckResult`
    """
    values = data.astype(float).values
    sratio = pd.Series(index=data.index, name=u'Successive ratios of {}'.format(data.name))
    sratio.iloc[0] = 1
    sratio.iloc[1:] = np.divide(values[1:], values[:-1])

    res = inrange(sratio, lower=lower, upper=upper, lower_warn=lower_warn, upper_warn=upper_warn)
    description = (u'Check if the successive ratios of elements in {} '
                   u'are within the range [{}, {}]').format(
        data.name, lower, upper
        )
    res = CheckResult(description=description, message=res.message, status=res.status)
    return res


def n_outside_range(data, lower, upper,
                    n_lower_bad=0, n_upper_bad=0,
                    n_lower_warn=None, n_upper_warn=None,
                    ):
    """Check if not too many elements are outside a given range

    :param data: The data to be checked
    :type data: pandas.Series | pandas.DataFrame | int | float
    :param lower: Minimum allowed value. For too many values smaller than this, *data*
        will be labeled as :const:`~glance.constants.WARNING` or :const:`~glance.constants.BAD`
        depending on *n_lower_warn* and *n_lower_bad*.
    :param upper: Maximum allowed value. For too many values larger than this, *data*
        will be labeled as :const:`~glance.constants.WARNING` or :const:`~glance.constants.BAD`
        depending on *n_upper_warn* and *n_upper_bad*.
    :param n_lower_warn: Maximal number of values still allowed below *lower* before the data is
        labeled with :const:`~glance.constants.WARNING`.
    :param n_upper_warn: Maximal number of values still allowed above *upper* before the data is
        labeled with :const:`~glance.constants.WARNING`.
    :param n_lower_bad: Maximal number of values still allowed below *lower* before the data is
        labeled with :const:`~glance.constants.BAD`. Defaults to 0.
    :param n_upper_bad: Maximal number of values still allowed above *upper* before the data is
        labeled with :const:`~glance.constants.BAD`. Defaults to 0.
    :return: Results of the check
    :rtype: :class:`~CheckResult`
    """

    data = ensure_dataframe(data)
    name = u', '.join(map(six.text_type, data.columns))

    messages = []

    # evaluation
    res = pd.DataFrame(GOOD, index=data.index, columns=data.columns, dtype=int)
    # the number thresholds can reduce the status from BAD if the entries is within the n leading ones
    for col in data.columns:
        # too large values
        too_large = data[col] > upper
        n_too_large = too_large.sum()
        if n_too_large > n_upper_bad:
            res.loc[too_large] = BAD
        elif n_upper_warn is not None and n_too_large > n_upper_warn:
            res.loc[too_large] = WARNING

        # too low values
        too_low = data[col] < lower
        n_too_low = too_low.sum()
        if n_too_low > n_lower_bad:
            res.loc[too_low] = BAD
        elif n_lower_warn is not None and n_too_low > n_lower_warn:
            res.loc[too_low] = WARNING

    # nan values are not detected
    res[pd.isnull(data)] = NEUTRAL

    description = u'Check that not too many values for {} are outside range [{}, {}].'.format(name, lower, upper)
    if (res == BAD).values.flatten().any():
        messages.append(u'Too many values outside range: n(<{}) > {} or n(>{}) > {}'.format(
            lower, n_lower_bad, upper, n_upper_bad))
    elif (res == WARNING).values.flatten().any():
        messages.append(u'Some values outside range: {} > n(<{}) > {} or {} > n(>{}) > {}'
                        u''.format(n_lower_bad, lower, n_lower_warn, n_upper_bad, upper, n_upper_warn))
    return CheckResult(description, u'\n'.join(messages), res)
