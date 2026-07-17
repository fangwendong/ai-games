from __future__ import annotations

import unittest

from ibkr_quant_bot.live_report import format_live_report


SAMPLE_OUTPUT = """market_session_source=cache
live_quote_source=cache
live_bar_source=cache
{"tradable_capital":{"cash_reserve_usd":10.0,"source":"live_context_cache","status":"available","usable_cash":4402.96}}
{"core_decisions":[{"symbol":"SOXL","action":"HOLD","signal":false,"position_status":"flat","strategy_status":"flat_no_signal","reason":"need at least 30 bars","fast_ema":131.1,"slow_ema":null,"latest_trade_price":132.5,"stop_loss_pct":0.006,"take_profit_pct":0.0375,"protection_status":"not_applicable"},{"symbol":"SOXS","action":"HOLD","signal":false,"position_status":"flat","strategy_status":"flat_no_signal","reason":"need at least 30 bars","fast_ema":56.2,"slow_ema":null,"latest_trade_price":55.72,"stop_loss_pct":0.006,"take_profit_pct":0.0375,"protection_status":"not_applicable"}]}
{"benchmark_quote":{"latest_trade_price":695.49,"quote_age_ms":273.8,"bar_count":16,"bar_data_exchange":"SMART","quote_data_exchange":"SMART"}}
[{"symbol":"SOXL","action":"HOLD","signal":false,"position_status":"flat","strategy_status":"flat_no_signal","reason":"need at least 30 bars","fast_ema":131.1,"slow_ema":null,"latest_trade_price":132.5,"stop_loss_pct":0.006,"take_profit_pct":0.0375,"protection_status":"not_applicable","bar_count":16,"bar_data_exchange":"SMART","quote_data_exchange":"SMART"},{"symbol":"SOXS","action":"HOLD","signal":false,"position_status":"flat","strategy_status":"flat_no_signal","reason":"need at least 30 bars","fast_ema":56.2,"slow_ema":null,"latest_trade_price":55.72,"stop_loss_pct":0.006,"take_profit_pct":0.0375,"protection_status":"not_applicable","bar_count":16,"bar_data_exchange":"SMART","quote_data_exchange":"SMART"}]
no signal: no order
"""


class LiveReportTest(unittest.TestCase):
    def test_formats_capital_timing_and_decisions(self) -> None:
        report = format_live_report(
            SAMPLE_OUTPUT,
            exit_code=0,
            started_at_ms=1_752_765_600_000,
            ended_at_ms=1_752_765_600_731,
        )

        self.assertIn("本次策略执行本金：4402.96 USD", report)
        self.assertIn("已预留 10.00 USD", report)
        self.assertIn("执行耗时：731 ms", report)
        self.assertIn("结束时间：", report)
        self.assertIn("QQQ：latest_trade_price=695.49", report)
        self.assertIn("SOXL：latest_trade_price=132.50", report)
        self.assertIn("bar_data_exchange=SMART", report)
        self.assertIn("quote_age_ms=273.8", report)
        self.assertIn("bar 数量：QQQ=16, SOXL=16, SOXS=16", report)
        self.assertIn("订单最终结果：未下单", report)

    def test_failure_is_fail_closed_without_raw_details(self) -> None:
        report = format_live_report(
            "BrokerError: account U123 request failed",
            exit_code=1,
            started_at_ms=1_752_765_600_000,
            ended_at_ms=1_752_765_603_000,
        )

        self.assertIn("🔴", report)
        self.assertIn("策略失败关闭", report)
        self.assertNotIn("U123", report)


if __name__ == "__main__":
    unittest.main()
