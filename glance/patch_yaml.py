# -*- coding: utf-8 -*-
"""Importing this module replaces all yaml.loader.Loader and yaml.dumper.Dumper default
parameters in all top-level functions in yaml (load(), safe_load(), ...) with their
libyaml-based versions (CLoader, CDumper), if libyaml is available."""

from __future__ import absolute_import
import yaml

if yaml.__with_libyaml__:
    # Monkeypatching
    yaml.Loader = yaml.CLoader
    yaml.Dumper = yaml.CDumper
    yaml.SafeLoader = yaml.CSafeLoader
    yaml.SafeDumper = yaml.CSafeDumper

    # Just monkeypatching yaml.loader.Loader (and ...Dumper) with their C-based versions
    # won't work, because this doesn't overwrite the default values in the function
    # definitions.

    repl = {
        yaml.loader.Loader: yaml.CLoader,
        yaml.loader.SafeLoader: yaml.CSafeLoader,
        yaml.dumper.Dumper: yaml.CDumper,
        yaml.dumper.SafeDumper: yaml.CSafeDumper,
    }

    for obj in yaml.__dict__.values():
        if getattr(obj, 'func_defaults', None) is not None:
            obj.__defaults__ = tuple(repl.get(_, _) for _ in obj.__defaults__)
