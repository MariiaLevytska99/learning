# -*- coding: utf-8 -*-
"""
A glance plugin for a PlotResult that supports specifying columns as X-axis of the plot.
"""
from __future__ import division, print_function, absolute_import
import logging

import numpy as np
import pandas as pd

from glance.report import PlotResult


_logger = logging.getLogger(__name__)


class PlotWithXResult(PlotResult):
    """Result data to be displayed as a plot, where one can specify which column of the data frame should be used
    as X-axis.
    Also supports dates as values for the X-axis.

    :param str title: Text displayed as the title of the plot
    :param pandas.DataFrame data: The data to be shown. Each column will be
      shown as a line.
    :param str x_column: The column which should be used as the plot's X-axis
    :param str y_axis_label: Label for the plot's Y-axis.
    :param bool build_legend: Whether to build legend for the plot.
    :param bool dots: Whether to also plot dots for each data point (default is lines only).
    :param int linewidth: The line width for the plots.
    :param list(str) colors: List of color names.
    :param list(float) vbars: List of x_coordinates to draw horizontal lines .
    """
    def __init__(self, title, data, x_column, **kwargs):
        if x_column not in data.columns:
            raise ValueError("column '{}' not in DataFrame.\n Available columns: {}".format(x_column, data.columns))
        super(PlotWithXResult, self).__init__(title, data)
        self.x_column = x_column
        self.y_axis_label = kwargs.pop('y_axis_label', '')
        self.build_legend = kwargs.pop('build_legend', True)
        self.dots = kwargs.pop('dots', False)
        self.linewidth = kwargs.pop('linewidth', 2)
        self.colors = kwargs.pop('colors', ['crimson',
                                            'dodgerblue',
                                            'forestgreen',
                                            'goldenrod',
                                            'hotpink',
                                            'lightseagreen',
                                            'lightslategray'])
        self.vbars = kwargs.pop('vbars', [])

    def fix_dict(self, d):
        d['datetime_columns'] = get_datetime_columns(d['data'])
        for col in d['datetime_columns']:
            d['data'][col] = d['data'][col].apply(lambda x: x.strftime('%Y-%m-%d-%H-%M-%S'))
        d['data'] = d['data'].to_dict(orient='split')
        return d

    @staticmethod
    def unfix_dict(d):
        d['data'] = pd.DataFrame(**d['data'])
        for col in d['datetime_columns']:
            d['data'][col] = pd.to_datetime(d['data'][col], format='%Y-%m-%d-%H-%M-%S')
        del d['datetime_columns']
        return d

    def render_html(self):
        from bokeh import plotting as bk
        from bokeh.embed import components
        from bokeh.resources import Resources

        args = {'title': self.title,
                'tools': "pan,wheel_zoom,box_zoom,reset,resize,previewsave",
                'x_axis_label': self.x_column,
                'y_axis_label': self.y_axis_label,
                }
        if self.x_column in get_datetime_columns(self.data):
            args['x_axis_type'] = 'datetime'
        fig = bk.figure(**args)
        if self.build_legend:
            colors = self.colors
        else:
            colors = self.colors[:1]
        source = bk.ColumnDataSource(self.data)
        for i, col in enumerate(self.data):
            legend = col if self.build_legend else None
            if col == self.x_column:
                continue
            fig.line(x=self.x_column,
                     y=col,
                     source=source,
                     legend=legend,
                     color=colors[i % len(colors)],
                     line_width=self.linewidth,
                     line_join='round')
            if self.dots:
                fig.circle(x=self.x_column,
                           y=col,
                           source=source,
                           color=colors[i % len(colors)],
                           size=9)

        for i, col in enumerate(self.vbars):
            fig.line([self.vbars[col], self.vbars[col]],
                     [self.data.drop([self.x_column], axis=1).min().min() * 1.1,
                     self.data.drop([self.x_column], axis=1).max().max() * 1.1],
                     legend=col,
                     color=colors[i % len(colors)],
                     alpha=0.8,
                     line_width=2)
        fig.grid.grid_line_alpha = 0.3
        script, div = components(fig, Resources('inline'))
        return div + '\n' + script


def get_datetime_columns(df):
    dt_columns = list()
    for col in df.columns:
        if df[col].dtype.type == np.datetime64:
            dt_columns.append(col)
            continue
        if len(df[col]) == 0:
            continue
        if hasattr(df[col].iloc[0], 'strftime'):
            dt_columns.append(col)
    return dt_columns
