from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


NEW_YORK = ZoneInfo("America/New_York")
SHANGHAI = ZoneInfo("Asia/Shanghai")


def _json_values(text: str) -> list[Any]:
    decoder = json.JSONDecoder()
    values: list[Any] = []
    offset = 0
    while offset < len(text):
        starts = [index for index in (text.find("{", offset), text.find("[", offset)) if index >= 0]
        if not starts:
            break
        start = min(starts)
        try:
            value, length = decoder.raw_decode(text[start:])
        except json.JSONDecodeError:
            offset = start + 1
            continue
        values.append(value)
        offset = start + length
    return values


def _value(value: object, *, digits: int = 2) -> str:
    if value is None:
        return "不可用"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return f"{float(value):.{digits}f}"
    return str(value)


def _order_result(output: str, exit_code: int) -> str:
    if exit_code != 0:
        return "未下单（策略失败关闭）"
    if "entry_order_result=fully_filled" in output:
        return "已全部成交，保护单已创建"
    if "entry_order_result=partially_filled" in output:
        return "部分成交，剩余已撤，保护单已按成交数量创建"
    if "entry_order_result=not_filled" in output:
        return "已提交未成交，入场单已撤"
    if "exit_order_result=filled" in output:
        return "退场单已全部成交"
    if "exit_order_result=partially_filled" in output:
        return "退场单部分成交"
    if "exit_order_result=" in output or "exit candidate:" in output:
        return "退场单已提交，成交状态待下一轮确认"
    if "dry-run: order not submitted" in output:
        return "未下单（dry-run）"
    return "未下单"


def _execution_blocker(output: str, exit_code: int) -> tuple[str, str]:
    if exit_code != 0:
        return "失败关闭", "策略失败关闭"
    if "entry_order_result=fully_filled" in output:
        return "买入已成交", "保护单已创建"
    if "entry_order_result=partially_filled" in output:
        return "买入部分成交", "余单已撤，保护单已按成交数量创建"
    if "entry_order_result=not_filled" in output:
        return "买入未成交", "入场单已撤"
    if "exit_order_result=filled" in output:
        return "卖出已成交", "退场完成"
    if "exit_order_result=partially_filled" in output:
        return "卖出部分成交", "仍需关注剩余持仓"
    if "daily entry limit reached:" in output:
        return "不下单", "今日入场次数已达上限"
    if "position already aligned: no new entry" in output:
        return "不新开仓", "已有持仓，等待保护单或退场条件"
    if "no signal: no order" in output:
        return "不下单", "当前没有入场或退场信号"
    if "end-of-day flatten window: no new entry" in output:
        return "不下单", "已进入收盘前禁止开仓窗口"
    if "possible split/reverse-split" in output:
        return "不下单", "价格尺度异常，疑似拆股或合股"
    if "active entry order exists" in output:
        return "不重复下单", "已有活动入场单"
    if "dry-run: order not submitted" in output:
        return "不下单", "dry-run 安全验证"
    return _order_result(output, exit_code), "无额外执行信息"


def _trade_marker(*, traded: bool, holding: bool, failed: bool) -> str:
    if failed:
        return "🔴 异常"
    if traded and holding:
        return "🟡 已成交·持仓"
    if traded:
        return "🟢 已成交·已清仓"
    return "⚪ 今日未成交"


def _short_reason(reason: object) -> str:
    text = str(reason or "不可用")
    if text.startswith("entry window closed before"):
        return "已过 13:30 ET 开仓截止时间"
    if text.startswith("need at least"):
        return "Bar 数量不足，尚不能计算完整指标"
    if text == "regime bullish":
        return "QQQ 多头，仅允许 SOXL"
    if text == "regime bearish":
        return "QQQ 空头，仅允许 SOXS"
    if text.startswith("fast="):
        return "技术条件满足"
    return text.replace("|", "/")


def _source_line(output: str, key: str) -> str:
    prefix = f"{key}="
    for line in output.splitlines():
        if line.startswith(prefix):
            return line[len(prefix) :].strip()
    return "不可用"


def format_live_report(
    output: str,
    *,
    exit_code: int,
    started_at_ms: int,
    ended_at_ms: int,
) -> str:
    values = _json_values(output)
    capital: dict[str, Any] = {}
    benchmark: dict[str, Any] = {}
    decisions: list[dict[str, Any]] = []
    scan_rows: list[dict[str, Any]] = []
    session_trade_status: dict[str, Any] = {}
    for item in values:
        if isinstance(item, dict) and isinstance(item.get("tradable_capital"), dict):
            capital = item["tradable_capital"]
        elif isinstance(item, dict) and isinstance(item.get("benchmark_quote"), dict):
            benchmark = item["benchmark_quote"]
        elif isinstance(item, dict) and isinstance(
            item.get("session_trade_status"), dict
        ):
            session_trade_status = item["session_trade_status"]
            if isinstance(item.get("core_decisions"), list):
                decisions = [
                    row for row in item["core_decisions"] if isinstance(row, dict)
                ]
        elif isinstance(item, dict) and isinstance(item.get("core_decisions"), list):
            decisions = [row for row in item["core_decisions"] if isinstance(row, dict)]
        elif isinstance(item, list) and item and all(isinstance(row, dict) for row in item):
            if {str(row.get("symbol", "")) for row in item} & {"SOXL", "SOXS"}:
                scan_rows = item

    if scan_rows:
        row_by_symbol = {str(row.get("symbol", "")): row for row in scan_rows}
        decisions = [row_by_symbol.get(symbol, {}) for symbol in ("SOXL", "SOXS")]

    ended = datetime.fromtimestamp(ended_at_ms / 1000, tz=timezone.utc)
    elapsed_ms = max(0, ended_at_ms - started_at_ms)
    status_icon = "🟢" if exit_code == 0 else "🔴"
    entry_count = int(session_trade_status.get("daily_entry_count", 0) or 0)
    max_entries = int(session_trade_status.get("max_daily_entries", 0) or 0)
    entry_rows = [
        row
        for row in session_trade_status.get("entries", [])
        if isinstance(row, dict)
    ]
    traded_symbols = {
        str(row.get("symbol", "")).upper() for row in entry_rows if row.get("symbol")
    }
    position_rows = [
        row
        for row in session_trade_status.get("current_positions", [])
        if isinstance(row, dict)
    ]
    positions = {
        str(row.get("symbol", "")).upper(): int(float(row.get("quantity", 0) or 0))
        for row in position_rows
    }
    position_summary = (
        "、".join(f"{symbol} {quantity}股" for symbol, quantity in positions.items())
        if positions
        else "无"
    )
    entry_limit_reached = max_entries > 0 and entry_count >= max_entries
    execution_action, execution_reason = _execution_blocker(output, exit_code)
    if positions:
        position_text = "、".join(
            f"{symbol} {quantity}股" for symbol, quantity in positions.items()
        )
        headline = f"🟡 当前持仓：{position_text}；不再新开仓，但仍可能卖出退场"
    elif traded_symbols:
        traded_text = "、".join(sorted(traded_symbols))
        follow_up = (
            "今日不会再次开仓"
            if entry_limit_reached
            else "仍可能再次开仓"
        )
        headline = f"🟢 今日 {traded_text} 已成交并清仓；{follow_up}"
    elif exit_code != 0:
        headline = "🔴 本轮失败关闭；未执行订单"
    else:
        headline = "⚪ 今日尚未成交；后续是否下单取决于信号与风控条件"
    lines = [
        f"{status_icon} V2 实盘轮询｜退出码 {exit_code}",
        headline,
        f"本轮结论：{execution_action}｜{execution_reason}",
        "",
        "【交易状态】",
    ]

    row_by_symbol = {
        str(row.get("symbol", "")).upper(): row for row in decisions
    }
    for symbol in ("SOXL", "SOXS"):
        row = row_by_symbol.get(symbol, {})
        holding = symbol in positions
        traded = symbol in traded_symbols
        marker = _trade_marker(traded=traded, holding=holding, failed=exit_code != 0)
        current_status = f"持仓 {positions[symbol]}股" if holding else "空仓"
        action = str(row.get("action", "不可用"))
        signal = row.get("signal")
        signal_text = f"{action} / {'是' if signal else '否'}" if signal is not None else "不可用"
        if exit_code != 0:
            future_order = "不会：策略失败关闭"
        elif holding:
            future_order = "会：止盈/止损/退场卖出"
        elif entry_limit_reached:
            future_order = f"不会：入场额度 {entry_count}/{max_entries}"
        else:
            future_order = "可能：满足条件后买入"
        reason = _short_reason(row.get("reason"))
        lines.append(
            f"{marker.split()[0]} {symbol}｜{_value(row.get('latest_trade_price'))}｜"
            f"{marker.partition(' ')[2]}｜{current_status}"
        )
        lines.append(f"信号：{signal_text}｜后续：{future_order}")
        lines.append(f"原因：{reason}")

    lines.extend(
        [
            "",
            "【资金与运行】",
            (
                f"本金上限：{_value(capital.get('usable_cash'))} USD｜"
                f"预留：{_value(capital.get('cash_reserve_usd'))} USD"
            ),
            (
                f"本金状态：{capital.get('status', '不可用')}｜"
                f"来源：{capital.get('source', '不可用')}"
            ),
            (
                f"执行耗时：{elapsed_ms} ms｜结束："
                f"{ended.astimezone(SHANGHAI).strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]} CST"
            ),
            (
                "美东时间："
                f"{ended.astimezone(NEW_YORK).strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]} ET"
            ),
            f"QQQ：{_value(benchmark.get('latest_trade_price'))}（趋势基准）",
            "",
            "【资金快照】",
            (
                f"可交易本金：{_value(capital.get('usable_cash'))} USD｜"
                f"预留：{_value(capital.get('cash_reserve_usd'))} USD｜"
                f"来源：{capital.get('source', '不可用')}"
            ),
            f"当前持仓：{position_summary}",
        ]
    )

    holding_decisions = [
        row for row in decisions if str(row.get("symbol", "")).upper() in positions
    ]
    if holding_decisions:
        lines.extend(["", "【持仓保护】"])
        for row in holding_decisions:
            symbol = str(row.get("symbol", ""))
            lines.append(
                f"{symbol}：止损 {_value(row.get('active_stop_price'))}｜"
                f"止盈 {_value(row.get('active_take_price'))}｜"
                f"状态 {row.get('protection_status', '不可用')}"
            )

    exchanges = sorted(
        {
            str(row.get("bar_data_exchange"))
            for row in scan_rows
            if row.get("bar_data_exchange")
        }
    )
    quote_exchanges = sorted(
        {
            str(row.get("quote_data_exchange"))
            for row in scan_rows
            if row.get("quote_data_exchange")
        }
    )
    strategy_bar_counts = ", ".join(
        f"{row.get('symbol')}={row.get('bar_count', '不可用')}" for row in scan_rows
    )
    bar_counts = f"QQQ={benchmark.get('bar_count', '不可用')}"
    if strategy_bar_counts:
        bar_counts = f"{bar_counts}, {strategy_bar_counts}"
    lines.extend(
        [
            "",
            "【数据诊断】",
            (
                f"Bar：{','.join(exchanges) or '不可用'} / "
                f"{_source_line(output, 'live_bar_source')}"
            ),
            (
                f"Quote：{','.join(quote_exchanges) or '不可用'} / "
                f"{_source_line(output, 'live_quote_source')} / "
                f"{_value(benchmark.get('quote_age_ms'), digits=1)} ms"
            ),
            f"Bar 数量：{bar_counts}",
        ]
    )
    if exit_code != 0:
        lines.append("异常：策略失败关闭；原始错误仅保留在本机脱敏日志")
    else:
        lines.append("异常：无")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--exit-code", required=True, type=int)
    parser.add_argument("--started-at-ms", required=True, type=int)
    parser.add_argument("--ended-at-ms", required=True, type=int)
    args = parser.parse_args(argv)
    output = Path(args.input).read_text(encoding="utf-8", errors="replace")
    print(
        format_live_report(
            output,
            exit_code=args.exit_code,
            started_at_ms=args.started_at_ms,
            ended_at_ms=args.ended_at_ms,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
