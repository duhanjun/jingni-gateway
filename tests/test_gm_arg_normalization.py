# -*- coding: utf-8 -*-
"""GM RPC 入参归一化测试。"""

import pandas as pd

from api.gm import _normalize_gm_kwargs


def test_l2_symbols_list_to_comma_string():
    kwargs = _normalize_gm_kwargs(
        "gmdata",
        "get_history_l2bars",
        {"symbols": ["SHSE.600000", "SZSE.000001"], "frequency": "60s"},
    )

    assert kwargs["symbols"] == "SHSE.600000,SZSE.000001"
    assert kwargs["frequency"] == "60s"


def test_symbol_sector_type_int_to_string():
    kwargs = _normalize_gm_kwargs(
        "gmdata", "stk_get_symbol_sector", {"symbols": ["SHSE.600000"], "sector_type": 1003}
    )

    assert kwargs["sector_type"] == "1003"


def test_option_hv_price_list_to_series():
    kwargs = _normalize_gm_kwargs(
        "gmdata", "option_calculate_hv", {"price": [100.0, 101.0, 99.0], "frequency": "1d"}
    )

    assert isinstance(kwargs["price"], pd.Series)
    assert kwargs["price"].dtype == "float64"


def test_other_gm_function_kwargs_unchanged():
    kwargs = _normalize_gm_kwargs(
        "gmdata", "stk_get_daily_basic", {"symbol": "SHSE.600000", "fields": "tclose"}
    )

    assert kwargs == {"symbol": "SHSE.600000", "fields": "tclose"}


def test_non_gmdata_module_unchanged():
    kwargs = _normalize_gm_kwargs("gmtrade", "get_cash", {"account_id": "x"})

    assert kwargs == {"account_id": "x"}
