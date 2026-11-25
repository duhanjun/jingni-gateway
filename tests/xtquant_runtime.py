#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Detect whether the MiniQMT runtime is reachable, not merely whether the SDK is installed."""

from functools import lru_cache


@lru_cache(maxsize=1)
def xtquant_runtime_available() -> bool:
    try:
        import xtquant.xtdata as xtdata
    except Exception:
        return False
    try:
        # get_client() raises immediately when the local MiniQMT data service is absent.
        xtdata.get_client()
        return True
    except Exception:
        return False


XTQUANT_RUNTIME_AVAILABLE = xtquant_runtime_available()
