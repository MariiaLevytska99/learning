# -*- coding: utf-8 -*-
"""
A glance plugin for a downloadable text file.
The text input is saved to a file and linked in the glance report.

"""
from __future__ import division, print_function, absolute_import

from glance.report import tagged, BaseResult

import os
import codecs


@tagged
class TextDownloadResult(BaseResult):
    """Text data to be downloaded via the glance interface.

    Given a text is written to a file and linked in a glance report.

    :param str file: Filename to save the file as.  This will be suffixed by
        a unique hex string to prevent overwriting different files.  If a file
        of the same name exists (if unique is set to False) then files will not
        be overwritten.
    :param str data: Text data to write to file.
    :param str title: Title name to display on the glance report.
    :param key use_key: Key to store data to.  If None a new key will be made.

    """
    externals = ('data',)

    def __init__(self,
                 file,
                 data=None,
                 title='Download File',
                 use_key=None):
        self.file = file
        self.data = data
        self.title = title
        if use_key is not None:
            self._external = use_key
        else:
            self._external = codecs.encode(os.urandom(4), 'hex').decode('utf8')

    def _get_externals(self, storage=None):
        if self.data is not None:
            data = dict([(attr, getattr(self, attr)) for attr in self.externals])
            return self._external, data
        else:
            return 'dummy', 0

    def get_key(self):
        return self._external
