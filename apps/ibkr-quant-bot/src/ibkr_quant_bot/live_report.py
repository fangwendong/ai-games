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
    for item in values:
        if isinstance(item, dict) and isinstance(item.get("tradable_capital"), dict):
            capital = item["tradable_capital"]
        elif isinstance(item, dict) and isinstance(item.get("benchmark_quote"), dict):
            benchmark = item["benchmark_quote"]
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
    lines = [
        f"{status_icon} V2 实盘轮询｜退出码 {exit_code}",
        "核心执行结论",
        (
            "- 本次策略执行本金："
            f"{_value(capital.get('usable_cash'))} USD；"
            f"已预留 {_value(capital.get('cash_reserve_usd'))} USD；"
            f"来源={capital.get('source', '不可用')}；状态={capital.get('status', '不可用')}"
        ),
        (
            f"- 执行耗时：{elapsed_ms} ms；结束时间："
            f"{ended.astimezone(NEW_YORK).strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]} ET / "
            f"{ended.astimezone(SHANGHAI).strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]} CST"
        ),
        (
            f"- QQQ：latest_trade_price={_value(benchmark.get('latest_trade_price'))}；"
            "基准标的，不产生交易信号。"
        ),
    ]

    for symbol, row in zip(("SOXL", "SOXS"), decisions, strict=False):
        lines.append(
            f"- {symbol}：latest_trade_price={_value(row.get('latest_trade_price'))}；"
            f"fast_ema={_value(row.get('fast_ema'), digits=6)}；"
            f"slow_ema={_value(row.get('slow_ema'), digits=6)}；"
            f"position_status={row.get('position_status', '不可用')}；"
            f"strategy_status={row.get('strategy_status', '不可用')}；"
            f"信号={_value(row.get('signal'))}（{row.get('action', '不可用')}）；"
            f"原因：{row.get('reason', '不可用')}。"
        )
    if not decisions:
        lines.append("- SOXL/SOXS：策略在生成决策前失败，指标不可用。")
    lines.append(f"- 订单最终结果：{_order_result(output, exit_code)}。")

    lines.append("风险与保护")
    for symbol, row in zip(("SOXL", "SOXS"), decisions, strict=False):
        lines.append(
            f"- {symbol}：stop_loss_pct={_value(row.get('stop_loss_pct'), digits=4)}；"
            f"take_profit_pct={_value(row.get('take_profit_pct'), digits=4)}；"
            f"calculated_stop_price={_value(row.get('calculated_stop_price'))}；"
            f"calculated_take_price={_value(row.get('calculated_take_price'))}；"
            f"active_stop_price={_value(row.get('active_stop_price'))}；"
            f"active_take_price={_value(row.get('active_take_price'))}；"
            f"protection_status={row.get('protection_status', '不可用')}。"
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
    bar_counts = ", ".join(
        f"{row.get('symbol')}={row.get('bar_count', '不可用')}" for row in scan_rows
    ) or "不可用"
    lines.extend(
        [
            "运行诊断",
            (
                f"- bar_data_exchange={','.join(exchanges) or '不可用'}；"
                f"live_bar_source={_source_line(output, 'live_bar_source')}。"
            ),
            (
                f"- quote_data_exchange={','.join(quote_exchanges) or '不可用'}；"
                f"live_quote_source={_source_line(output, 'live_quote_source')}；"
                f"quote_age_ms={_value(benchmark.get('quote_age_ms'), digits=1)}。"
            ),
            f"- bar 数量：{bar_counts}。",
        ]
    )
    if exit_code != 0:
        lines.append("- 异常：策略命令失败关闭；原始错误仅保留在本机临时日志，不在消息中暴露账户或订单细节。")
    else:
        lines.append("- 异常：无。")
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
