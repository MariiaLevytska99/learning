# -*- coding: utf-8 -*-
"""Status constants

.. data:: NEUTRAL

    The element was not checked, or has no status for some reason.

.. data:: GOOD

    The element passed the check.

.. data:: WARNING

    The element passed the check, but was classified as needing
    attention.

.. data:: BAD

    The element was qualified as bad.
"""

from __future__ import absolute_import
NEUTRAL, GOOD, WARNING, BAD = [0, 1, 2, 3]

status_names = {NEUTRAL: 'No Status', GOOD: 'Good', WARNING: 'Warning', BAD: 'Bad'}
