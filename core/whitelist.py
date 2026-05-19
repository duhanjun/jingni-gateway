"""
RPC 函数白名单模块。

本模块定义了每个数据源提供者允许调用的 RPC 函数白名单。
只有在白名单中列出的函数才能通过 RPC 接口调用。

模块说明：
- xtdata: XtQuant 数据模块函数
- xttrader: XtQuant 交易模块函数
- gmdata: GM (掘金量化) 数据模块函数
- gmtrade: GM (掘金量化) 交易模块函数

安全说明：
白名单是一种安全措施，用于防止未经授权的函数调用。
只添加可以安全暴露给 RPC 接口的函数。
"""

RPC_WHITELIST = {
    "xtdata": [
        "subscribe_quote", "subscribe_whole_quote", "unsubscribe_quote", "run",
        "get_market_data", "get_local_data", "get_full_tick", "get_divid_factors",
        "get_l2_quote", "get_l2_order", "get_l2_transaction", "get_full_kline",
        "download_history_data", "download_history_data2",
        "download_financial_data", "download_financial_data2",
        "download_sector_data", "download_index_weight",
        "download_cb_data", "download_etf_info", "download_holiday_data",
        "download_history_contracts",
        "get_financial_data",
        "get_instrument_detail", "get_instrument_type", "get_trading_dates",
        "get_sector_list", "get_stock_list_in_sector", "get_index_weight",
        "get_holidays", "get_trading_calendar", "get_trading_time",
        "get_cb_info", "get_ipo_info", "get_period_list",
        "get_etf_info", "get_data_dir",
        "create_sector_folder", "create_sector", "add_sector",
        "remove_stock_from_sector", "remove_sector", "reset_sector",
        "subscribe_formula", "unsubscribe_formula",
        "call_formula", "call_formula_batch", "generate_index_data",
        "reconnect",
    ],
    "xttrader": [
        "create_trader", "register_callback", "start", "connect", "stop",
        "run_forever", "set_relaxed_response_order_enabled",
        "subscribe", "unsubscribe",
        "order_stock", "order_stock_async",
        "cancel_order_stock", "cancel_order_stock_sysid",
        "cancel_order_stock_async", "cancel_order_stock_sysid_async",
        "fund_transfer",
        "bank_transfer_in", "bank_transfer_in_async",
        "bank_transfer_out", "bank_transfer_out_async",
        "ctp_transfer_option_to_future", "ctp_transfer_option_to_future_async",
        "ctp_transfer_future_to_option", "ctp_transfer_future_to_option_async",
        "sync_transaction_from_external",
        "query_stock_asset", "query_stock_orders", "query_stock_trades",
        "query_stock_positions", "query_position_statistics",
        "query_credit_detail", "query_stk_compacts",
        "query_credit_subjects", "query_credit_slo_code",
        "query_new_purchase_limit", "query_ipo_data",
        "query_account_infos", "query_com_fund", "query_com_position",
        "export_data", "query_data",
        "query_bank_info", "query_bank_amount",
        "query_bank_transfer_stream", "query_secu_account",
        "smt_query_quoter", "smt_negotiate_order_async", "smt_query_compact",
    ],
    "gmdata": [
        "history_n", "history", "get_fundamentals", "get_fundamentals_n",
        "get_symbol_infos", "get_symbols", "get_history_symbol",
        "get_trading_dates_by_year", "get_trading_dates", "get_trading_session",
        "get_instrumentinfos", "get_instruments", "get_history_instruments",
        "get_constituents", "get_history_constituents",
        "get_industry", "get_sector", "get_concept",
        "stk_get_adj_factor", "stk_get_dividend", "stk_get_daily_basic",
        "stk_get_daily_basic_pt", "stk_get_daily_mktvalue",
        "stk_get_daily_mktvalue_pt", "stk_get_daily_valuation",
        "stk_get_daily_valuation_pt", "stk_get_index_constituents",
        "stk_get_industry_category", "stk_get_industry_constituents",
        "stk_get_sector_category", "stk_get_sector_constituents",
        "stk_get_money_flow", "stk_get_share_change", "stk_get_shareholder_num",
        "stk_get_symbol_industry", "stk_get_symbol_sector",
        "stk_get_top_shareholder", "stk_get_ration",
        "stk_get_fundamentals_balance", "stk_get_fundamentals_balance_pt",
        "stk_get_fundamentals_cashflow", "stk_get_fundamentals_cashflow_pt",
        "stk_get_fundamentals_income", "stk_get_fundamentals_income_pt",
        "stk_get_finance_audit", "stk_get_finance_deriv",
        "stk_get_finance_deriv_pt", "stk_get_finance_forecast",
        "stk_get_finance_prime", "stk_get_finance_prime_pt",
        "fut_get_continuous_contracts", "fut_get_contract_info",
        "fut_get_transaction_ranking", "fut_get_transaction_rankings",
        "fut_get_warehouse_receipt", "get_continuous_contracts",
        "get_contract_expire_rest_days", "get_expire_rest_days",
        "fnd_get_adj_factor", "fnd_get_dividend", "fnd_get_etf_constituents",
        "fnd_get_net_value", "fnd_get_portfolio", "fnd_get_share", "fnd_get_split",
        "bnd_get_amount_change", "bnd_get_analysis", "bnd_get_call_info",
        "bnd_get_conversion_price", "bnd_get_put_info",
        "option_calculate_delta", "option_calculate_gamma",
        "option_calculate_greeks", "option_calculate_hv",
        "option_calculate_iv", "option_calculate_ivsurface",
        "option_calculate_price", "option_calculate_rho",
        "option_calculate_t", "option_calculate_theta", "option_calculate_vega",
        "option_get_comb_info", "option_get_comb_pos",
        "option_get_delisted_dates", "option_get_exercise_prices",
        "option_get_symbols_by_exchange", "option_get_symbols_by_in_at_out",
        "get_history_bars_l2", "get_history_l2bars",
        "get_history_l2orders", "get_history_l2orders_queue",
        "get_history_l2ticks", "get_history_l2transactions",
        "get_history_ticks_l2", "get_history_transaction_l2",
        "get_version", "get_strerror", "last_tick", "current_price", "current",
        "stk_hk_inst_holding_detail_info", "stk_hk_inst_holding_info",
        "stk_quota_shszhk_infos", "stk_active_stock_top10_shszhk_info",
        "stk_abnor_change_detail", "stk_abnor_change_stocks",
        "ipo_get_instruments", "ipo_get_lot_info",
        "ipo_get_match_number", "ipo_get_quota",
    ],
    "gmtrade": [
        "run", "stop", "set_token", "set_account_id", "set_serv_addr",
        "set_option", "set_parameter", "add_parameter",
        "subscribe", "unsubscribe",
        "order_volume", "order_value", "order_percent",
        "order_target_volume", "order_target_value", "order_target_percent",
        "order_batch", "order_cancel", "order_cancel_all", "order_close_all",
        "get_cash", "get_position", "get_orders",
        "get_unfinished_orders", "get_execution_reports",
        "algo_order", "algo_order_batch", "algo_order_cancel",
        "algo_order_pause", "algo_smart_reorder", "algo_smart_reorder_cancel",
        "get_algo_orders", "get_algo_child_orders",
        "credit_buying_on_margin", "credit_short_selling",
        "credit_repay_cash_directly", "credit_repay_cash_by_selling_share",
        "credit_repay_share_directly", "credit_repay_share_by_buying_share",
        "credit_collateral_in", "credit_collateral_out",
        "credit_buying_on_collateral", "credit_selling_on_collateral",
        "credit_get_cash", "credit_get_contracts",
        "credit_get_borrowable_instruments",
        "credit_get_borrowable_instruments_positions",
        "credit_get_collateral_instruments",
        "option_comb", "option_sep", "option_comb_by_comb_info",
        "option_sep_by_comb_pos", "option_covered_open", "option_covered_close",
        "option_exercise", "option_preorder_sell_margin",
        "option_preorder_valid_volume",
        "bond_convertible_call", "bond_convertible_put",
        "bond_convertible_put_cancel", "bond_convertible_get_call_info",
        "fund_buy", "fund_redemption", "fund_subscribing",
        "fund_etf_buy", "fund_etf_redemption",
        "ipo_buy", "bond_reverse_repurchase_agreement",
        "schedule", "timer", "timer_stop",
        "get_account_id",
        "universe_set", "universe_get_symbols",
        "universe_get_names", "universe_delete",
    ],
}


def is_function_whitelisted(module: str, function: str) -> bool:
    """
    检查函数是否在 RPC 白名单中。

    参数：
        module: 模块名称 (xtdata, xttrader, gmdata, gmtrade)
        function: 要检查的函数名称

    返回：
        如果函数在白名单中则返回 True，否则返回 False

    示例：
        >>> is_function_whitelisted("xtdata", "get_market_data")
        True
        >>> is_function_whitelisted("xtdata", "dangerous_function")
        False
    """
    if module not in RPC_WHITELIST:
        return False
    return function in RPC_WHITELIST[module]


def get_whitelisted_modules() -> list:
    """
    获取所有白名单模块列表。

    返回：
        模块名称列表

    示例：
        >>> get_whitelisted_modules()
        ['xtdata', 'xttrader', 'gmdata', 'gmtrade']
    """
    return list(RPC_WHITELIST.keys())


def get_whitelisted_functions(module: str) -> list:
    """
    获取指定模块的白名单函数列表。

    参数：
        module: 模块名称

    返回：
        函数名称列表，如果模块不存在则返回空列表

    示例：
        >>> get_whitelisted_functions("xtdata")
        ['subscribe_quote', 'subscribe_whole_quote', ...]
    """
    return RPC_WHITELIST.get(module, [])
