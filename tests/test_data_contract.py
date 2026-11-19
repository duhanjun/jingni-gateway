# -*- coding: utf-8 -*-
"""数据契约测试：DataFrame 序列化后的结构与黄金样本。"""

import pandas as pd

from providers.base import serialize_data


def test_dataframe_contract_for_tdx_daily_bars():
    close = pd.DataFrame(
        {"600000.SH": [10.86, 10.72, 10.64]},
        index=["2026-11-17", "2026-11-18", "2026-11-19"],
    )
    volume = pd.DataFrame(
        {"600000.SH": [92524744.0, 65527092.0, 39843896.0]},
        index=["2026-11-17", "2026-11-18", "2026-11-19"],
    )

    payload = serialize_data({"Close": close, "Volume": volume})

    assert payload["Close"]["__type__"] == "DataFrame"
    assert payload["Close"]["columns"] == ["600000.SH"]
    assert payload["Close"]["shape"] == [3, 1]
    assert [row["600000.SH"] for row in payload["Close"]["data"]] == [10.86, 10.72, 10.64]
    assert [row["600000.SH"] for row in payload["Volume"]["data"]] == [
        92524744.0, 65527092.0, 39843896.0,
    ]


def test_plain_structures_round_trip():
    payload = serialize_data({
        "asset": {"Cash": "998908.59", "Asset": "1000109.59"},
        "orders": [{"Wtbh": "274203", "Status": 0}],
        "ok": True,
    })

    assert payload["asset"]["Cash"] == "998908.59"
    assert payload["orders"][0]["Wtbh"] == "274203"
    assert payload["ok"] is True
