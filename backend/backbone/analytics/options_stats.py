"""Option-position analytics shared by options metrics and charts (not a plugin module)."""

from __future__ import annotations

from typing import Any

import numpy as np

from backbone.core.results import BacktestResult
from backbone.core.types import FloatArray


def option_columns(res: BacktestResult) -> list[tuple[int, dict[str, Any]]]:
    """Columns of option instruments with their metadata."""
    meta: dict[str, dict[str, Any]] = res.metadata.get("instrument_meta", {})
    return [
        (j, meta[i])
        for j, i in enumerate(res.instruments)
        if meta.get(i, {}).get("asset_class") == "option"
    ]


def _held_and_returns(res: BacktestResult) -> tuple[FloatArray, FloatArray, FloatArray]:
    prev_eq = np.concatenate(([res.initial_capital], res.equity[:-1]))
    held = np.vstack([np.zeros((1, res.weights.shape[1])), res.weights[:-1]])
    with np.errstate(divide="ignore", invalid="ignore"):
        rets = np.nan_to_num(res.prices[1:] / res.prices[:-1] - 1.0)
    rets = np.vstack([np.zeros((1, rets.shape[1])), rets])
    return prev_eq, held, rets


def non_option_pnl(res: BacktestResult) -> FloatArray:
    """Per-bar P&L (currency) of non-option positions."""
    opt = {j for j, _ in option_columns(res)}
    rest = [j for j in range(len(res.instruments)) if j not in opt]
    prev_eq, held, rets = _held_and_returns(res)
    return (held[:, rest] * rets[:, rest]).sum(axis=1) * prev_eq


def option_pnl(res: BacktestResult) -> FloatArray:
    """Per-bar P&L (currency) of option legs before costs.

    Taken as the gross portfolio P&L minus the non-option P&L, so it includes the roll-bar
    returns the engine applied from the option ``ret`` series.
    """
    prev_eq = np.concatenate(([res.initial_capital], res.equity[:-1]))
    return res.gross_returns * prev_eq - non_option_pnl(res)
