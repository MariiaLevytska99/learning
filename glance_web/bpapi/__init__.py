# -*- coding: utf-8 -*-
""""""

from __future__ import (absolute_import, division, print_function)

import logging

from flask import (Blueprint, jsonify)

from glance.utils import slugify


log = logging.getLogger(__name__)


def make_api_blueprint(api, name, prefix=''):
    log.info('creating blueprint "{}"'.format(__name__))
    blueprint = Blueprint(
        'api-' + slugify(name), __name__,
        url_prefix=prefix,
    )

    @blueprint.route('/')
    def index():
        return jsonify(api.index())

    return blueprint
