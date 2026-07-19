from __future__ import annotations

import unittest

from ibkr_quant_bot.live_report import format_live_report


SAMPLE_OUTPUT = """market_session_source=cache
live_quote_source=cache
live_bar_source=cache
{"tradable_capital":{"cash_reserve_usd":10.0,"source":"live_context_cache","status":"available","strategy_capital_usd":4500.0,"usable_cash":4402.96}}
{"session_trade_status":{"daily_entry_count":0,"max_daily_entries":1,"current_positions":[],"entries":[]},"core_decisions":[{"symbol":"SOXL","action":"HOLD","signal":false,"position_status":"flat","strategy_status":"flat_no_signal","reason":"need at least 30 bars","fast_ema":131.1,"slow_ema":null,"latest_trade_price":132.5,"stop_loss_pct":0.006,"take_profit_pct":0.0375,"protection_status":"not_applicable"},{"symbol":"SOXS","action":"HOLD","signal":false,"position_status":"flat","strategy_status":"flat_no_signal","reason":"need at least 30 bars","fast_ema":56.2,"slow_ema":null,"latest_trade_price":55.72,"stop_loss_pct":0.006,"take_profit_pct":0.0375,"protection_status":"not_applicable"}]}
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

        self.assertIn("【交易状态】", report)
        self.assertIn("⚪ SOXL｜132.50｜今日未成交｜空仓", report)
        self.assertIn("【资金与运行】", report)
        self.assertIn("策略本金：4500.00 USD｜可用现金：4402.96 USD｜预留：10.00 USD", report)
        self.assertIn("执行耗时：731 ms", report)
        self.assertIn("QQQ：695.49（趋势基准）", report)
        self.assertIn("【数据诊断】", report)
        self.assertIn("Bar：SMART / cache", report)
        self.assertIn("Quote：SMART / cache / 273.8 ms", report)
        self.assertIn("Bar 数量：QQQ=16, SOXL=16, SOXS=16", report)
        self.assertIn("本轮结论：不下单｜当前没有入场或退场信号", report)

    def test_marks_completed_trade_and_blocks_reentry(self) -> None:
        output = SAMPLE_OUTPUT.replace(
            '"daily_entry_count":0,"max_daily_entries":1,"current_positions":[],"entries":[]',
            '"daily_entry_count":1,"max_daily_entries":1,"current_positions":[],"entries":[{"symbol":"SOXL","filled_quantity":21,"average_fill_price":138.88}]',
        ).replace("no signal: no order", "daily entry limit reached: 1/1; no new entry")
        report = format_live_report(
            output,
            exit_code=0,
            started_at_ms=1_752_765_600_000,
            ended_at_ms=1_752_765_600_731,
        )

        self.assertIn("🟢 今日 SOXL 已成交并清仓；今日不会再次开仓", report)
        self.assertIn("🟢 SOXL｜132.50｜已成交·已清仓｜空仓", report)
        self.assertIn("不会：入场额度 1/1", report)
        self.assertIn("本轮结论：不下单｜今日入场次数已达上限", report)

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
