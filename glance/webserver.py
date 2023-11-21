from __future__ import absolute_import
import logging
import warnings

import debtcollector as dc

log = logging.getLogger(__name__)
warnings.filterwarnings('module', module='glance')

dc.deprecate(
    prefix='glance.webserver was moved to the glance.web package',
    postfix=' Please "import glance.web" instead.',
    version='0.9.5', removal_version='1.0')

from glance.web import *
