# -*- coding: utf-8 -*-
""""""

from __future__ import (absolute_import, division, print_function)

import logging

from flask import Blueprint, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from prometheus_client.core import CollectorRegistry, GaugeMetricFamily
from prometheus_client.process_collector import ProcessCollector

from glance.utils import slugify


log = logging.getLogger(__name__)


class GlanceCollector(object):
    def __init__(self, api):
        self.api = api

    def collect(self):
        family = GaugeMetricFamily(
            name='report_status',
            documentation='Status of Glance reports',
            labels=[
                'group',
                'report',
                'status',
            ]
        )

        idx = self.api.index()

        for rid in sorted(idx.keys()):
            info = idx[rid]

            group = slugify(info['group'])
            report = slugify(rid)

            for status, count in info['status'].items():
                status = str(status)
                family.add_metric(
                    labels=[
                        group,
                        report,
                        status,
                    ],
                    value=count,
                )

        yield family


def make_prometheus_blueprint(api, name, prefix=''):
    log.info('creating blueprint "%s"', __name__)

    registry = CollectorRegistry(auto_describe=True)
    ProcessCollector(registry=registry)
    registry.register(GlanceCollector(api))

    blueprint = Blueprint(
        'metrics-' + slugify(name), __name__,
        url_prefix=prefix,
    )

    @blueprint.route('/')
    def index():
        metrics = generate_latest(registry)
        return Response(metrics, mimetype=CONTENT_TYPE_LATEST)

    return blueprint
