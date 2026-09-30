"""Option pricing and rolling option positions (pure, vectorized where possible).

* Black-Scholes-Merton prices, Greeks and implied volatility.
* Chain helpers: pick contracts by delta, moneyness and days to expiry.
* Rolling option indices: the value of "hold a ``tenor``-day option at ``moneyness`` x spot,
  roll every ``roll_every`` bars", as a price series an engine can trade like any other
  instrument. Built either from a real chain or model-priced from a volatility series (then
  flagged ``model_priced``).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Final

import numpy as np
import polars as pl
from scipy.stats import norm

from backbone.core.types import FloatArray, OptionRight, TimeArray

DAYS_PER_YEAR: Final = 365.0
MIN_T: Final = 1.0 / DAYS_PER_YEAR / 24.0
MIN_VOL: Final = 1e-4
IV_MAX: Final = 5.0
IV_ITERATIONS: Final = 100
IV_TOL: Final = 1e-8
GREEKS: Final = ("delta", "gamma", "vega", "theta")


def _d1_d2(
    spot: FloatArray,
    strike: FloatArray,
    t: FloatArray,
    rate: FloatArray,
    vol: FloatArray,
    div: FloatArray,
) -> tuple[FloatArray, FloatArray]:
    t = np.maximum(t, MIN_T)
    vol = np.maximum(vol, MIN_VOL)
    sqrt_t = np.sqrt(t)
    with np.errstate(divide="ignore", invalid="ignore"):
        d1 = (np.log(spot / strike) + (rate - div + 0.5 * vol**2) * t) / (vol * sqrt_t)
    return d1, d1 - vol * sqrt_t


def bs_price(
    spot: FloatArray | float,
    strike: FloatArray | float,
    t: FloatArray | float,
    rate: FloatArray | float,
    vol: FloatArray | float,
    right: OptionRight,
    div: FloatArray | float = 0.0,
) -> FloatArray:
    """Black-Scholes-Merton price (``t`` in years). At or after expiry returns intrinsic value."""
    s, k, tt, r, v, q = (np.asarray(x, dtype=np.float64) for x in (spot, strike, t, rate, vol, div))
    d1, d2 = _d1_d2(s, k, tt, r, v, q)
    disc_q, disc_r = np.exp(-q * tt), np.exp(-r * tt)
    if right is OptionRight.CALL:
        price = s * disc_q * norm.cdf(d1) - k * disc_r * norm.cdf(d2)
        intrinsic = np.maximum(s - k, 0.0)
    else:
        price = k * disc_r * norm.cdf(-d2) - s * disc_q * norm.cdf(-d1)
        intrinsic = np.maximum(k - s, 0.0)
    return np.where(tt <= 0, intrinsic, price)


def bs_greeks(
    spot: FloatArray | float,
    strike: FloatArray | float,
    t: FloatArray | float,
    rate: FloatArray | float,
    vol: FloatArray | float,
    right: OptionRight,
    div: FloatArray | float = 0.0,
) -> dict[str, FloatArray]:
    """Delta, gamma, vega (per 1.00 vol) and theta (per year)."""
    s, k, tt, r, v, q = (np.asarray(x, dtype=np.float64) for x in (spot, strike, t, rate, vol, div))
    d1, d2 = _d1_d2(s, k, tt, r, v, q)
    tt = np.maximum(tt, MIN_T)
    v = np.maximum(v, MIN_VOL)
    disc_q, disc_r = np.exp(-q * tt), np.exp(-r * tt)
    pdf = norm.pdf(d1)
    gamma = disc_q * pdf / (s * v * np.sqrt(tt))
    vega = s * disc_q * pdf * np.sqrt(tt)
    common = -s * disc_q * pdf * v / (2 * np.sqrt(tt))
    if right is OptionRight.CALL:
        delta = disc_q * norm.cdf(d1)
        theta = common - r * k * disc_r * norm.cdf(d2) + q * s * disc_q * norm.cdf(d1)
    else:
        delta = disc_q * (norm.cdf(d1) - 1.0)
        theta = common + r * k * disc_r * norm.cdf(-d2) - q * s * disc_q * norm.cdf(-d1)
    return {"delta": delta, "gamma": gamma, "vega": vega, "theta": theta}


def implied_vol(
    price: float,
    spot: float,
    strike: float,
    t: float,
    rate: float,
    right: OptionRight,
    div: float = 0.0,
) -> float:
    """Implied volatility by bisection (``nan`` if the price is outside no-arbitrage bounds)."""
    lo, hi = MIN_VOL, IV_MAX
    f_lo = float(bs_price(spot, strike, t, rate, lo, right, div)) - price
    f_hi = float(bs_price(spot, strike, t, rate, hi, right, div)) - price
    if f_lo > 0 or f_hi < 0:
        return math.nan
    for _ in range(IV_ITERATIONS):
        mid = 0.5 * (lo + hi)
        f_mid = float(bs_price(spot, strike, t, rate, mid, right, div)) - price
        if abs(f_mid) < IV_TOL:
            return mid
        if f_mid > 0:
            hi = mid
        else:
            lo = mid
    return 0.5 * (lo + hi)


# --------------------------------------------------------------------------- chains


def select_by_delta(
    chain: pl.DataFrame, target_delta: float, right: OptionRight, min_dte: int, max_dte: int
) -> pl.DataFrame:
    """Per timestamp, the contract of ``right`` with DTE in range closest to ``target_delta``.

    ``chain`` needs ``timestamp, option_id, right, strike, expiry, delta`` columns.
    """
    return _select(
        chain, right, min_dte, max_dte, (pl.col("delta") - target_delta).abs().alias("_score")
    )


def select_by_moneyness(
    chain: pl.DataFrame, moneyness: float, right: OptionRight, min_dte: int, max_dte: int
) -> pl.DataFrame:
    """Per timestamp, the contract closest to ``strike / spot = moneyness`` (needs ``spot``)."""
    return _select(
        chain,
        right,
        min_dte,
        max_dte,
        (pl.col("strike") / pl.col("spot") - moneyness).abs().alias("_score"),
    )


def _select(
    chain: pl.DataFrame, right: OptionRight, min_dte: int, max_dte: int, score: pl.Expr
) -> pl.DataFrame:
    dte = (pl.col("expiry").cast(pl.Date) - pl.col("timestamp").dt.date()).dt.total_days()
    return (
        chain.with_columns(dte.alias("dte"), score)
        .filter((pl.col("right") == right.value) & pl.col("dte").is_between(min_dte, max_dte))
        .sort(["timestamp", "_score", "dte"])
        .group_by("timestamp", maintain_order=True)
        .first()
        .drop("_score")
    )


# --------------------------------------------------------------------------- rolling indices


@dataclass(frozen=True)
class RollingOption:
    """A rolling option position (one contract per unit of underlying at inception)."""

    right: OptionRight
    moneyness: float
    tenor_days: int
    roll_every: int

    @property
    def label(self) -> str:
        """Short instrument label, e.g. ``P95-30D``."""
        return f"{self.right.value[0].upper()}{round(self.moneyness * 100)}-{self.tenor_days}D"


@dataclass(frozen=True)
class OptionIndex:
    """A rolling option position aligned to the underlying's bars.

    Attributes:
        price: Price of the option currently held (per unit of underlying); jumps at rolls.
        ret: Return of the held position over each bar (on a roll bar: the expiring option's
            return; the new option is bought at that bar's close).
        delta, gamma, vega, theta: Greeks of the option currently held (per unit).
        strike: Strike of the option currently held.
        roll: 1.0 on roll bars.
    """

    price: FloatArray
    ret: FloatArray
    delta: FloatArray
    gamma: FloatArray
    vega: FloatArray
    theta: FloatArray
    strike: FloatArray
    roll: FloatArray


def rolling_option_index(
    timestamps: TimeArray,
    spot: FloatArray,
    vol: FloatArray,
    spec: RollingOption,
    rate: float = 0.0,
    div: float = 0.0,
) -> OptionIndex:
    """Model-priced rolling option (Black-Scholes with ``vol`` known at each bar).

    Every ``roll_every`` bars a new option is bought with strike ``moneyness x spot`` and
    expiry ``tenor_days`` calendar days later; the old one is sold at its model value
    (intrinsic value once expired).
    """
    n = len(timestamps)
    days = timestamps.astype("datetime64[D]").astype(np.int64).astype(np.float64)
    roll = np.zeros(n)
    roll_idx = np.arange(0, n, max(spec.roll_every, 1))
    roll[roll_idx] = 1.0
    seg = np.maximum.accumulate(np.where(roll > 0, np.arange(n), 0))
    fill = float(np.nanmedian(vol)) if np.isfinite(vol).any() else 0.2
    v = np.where(np.isfinite(vol), vol, fill)
    strike = spec.moneyness * spot[seg]
    t = np.maximum(days[seg] + spec.tenor_days - days, 0.0) / DAYS_PER_YEAR
    price = bs_price(spot, strike, t, rate, v, spec.right, div)
    greeks = bs_greeks(spot, strike, t, rate, v, spec.right, div)
    # value at bar t of the option held over bar t (the previous segment's on roll bars)
    prev_seg = np.concatenate(([0], seg[:-1]))
    held_t = np.maximum(days[prev_seg] + spec.tenor_days - days, 0.0) / DAYS_PER_YEAR
    held_value = bs_price(spot, spec.moneyness * spot[prev_seg], held_t, rate, v, spec.right, div)
    prev_price = np.concatenate(([np.nan], price[:-1]))
    with np.errstate(divide="ignore", invalid="ignore"):
        ret = np.where(prev_price > 0, held_value / prev_price - 1.0, 0.0)
    ret[0] = np.nan
    return OptionIndex(
        price=price,
        ret=ret,
        delta=greeks["delta"],
        gamma=greeks["gamma"],
        vega=greeks["vega"],
        theta=greeks["theta"],
        strike=strike,
        roll=roll,
    )


# --------------------------------------------------------------------------- instruments

REALIZED_VOL_WINDOW: Final = 21
IV_FIELD: Final = "iv"


def option_instrument_id(underlying: str, spec: RollingOption) -> str:
    """Id of a synthetic rolling option instrument, e.g. ``SPY:P95-30D``."""
    return f"{underlying}:{spec.label}"


def volatility_for(
    close: FloatArray, iv: FloatArray | None, periods_per_year: float, premium: float
) -> FloatArray:
    """Volatility known at each bar.

    Implied vol if supplied, else trailing realized vol times ``premium`` (a crude variance
    risk premium).
    """
    from backbone.core.numeric import pct_change, rolling_std

    realized = (
        rolling_std(pct_change(close, 1), REALIZED_VOL_WINDOW)
        * math.sqrt(periods_per_year)
        * premium
    )
    if iv is None:
        return realized
    return np.where(np.isfinite(iv), iv, realized)


def synthetic_option_frame(
    timestamps: TimeArray,
    underlying: str,
    close: FloatArray,
    vol: FloatArray,
    spec: RollingOption,
    rate: float = 0.0,
) -> tuple[pl.DataFrame, str]:
    """Canonical frame (``close``, ``ret``, Greeks, ``strike``, ``roll``) of a rolling option."""
    from backbone.core import columns as C
    from backbone.core.types import pl_times

    idx = rolling_option_index(timestamps, close, vol, spec, rate)
    inst = option_instrument_id(underlying, spec)
    frame = pl.DataFrame(
        {
            C.TIMESTAMP: pl_times(timestamps),
            C.INSTRUMENT: [inst] * len(timestamps),
            C.CLOSE: idx.price,
            C.RETURN: idx.ret,
            "delta": idx.delta,
            "gamma": idx.gamma,
            "vega": idx.vega,
            "theta": idx.theta,
            "strike": idx.strike,
            "roll": idx.roll,
        }
    ).filter(pl.col(C.CLOSE).is_finite())
    return frame, inst


CHAIN_DTE_TOLERANCE: Final = 0.4
"""Accept chain expiries within +/-40% of the target tenor."""


def chain_option_frame(
    timestamps: TimeArray,
    underlying: str,
    close: FloatArray,
    chain: pl.DataFrame,
    spec: RollingOption,
) -> tuple[pl.DataFrame, str] | None:
    """Rolling option built from a real chain (mid prices and chain Greeks).

    ``chain`` columns: ``timestamp, option_id, underlying, right, strike, expiry, mid`` and
    optionally ``delta, gamma, vega, theta``. At each roll bar the contract closest to the
    target moneyness with an expiry near the tenor is selected and held until the next roll.
    Returns ``None`` when the chain has no usable contracts.
    """
    from backbone.core import columns as C
    from backbone.core.types import np_times, pl_times

    sub = chain.filter((pl.col("underlying") == underlying) & (pl.col("right") == spec.right.value))
    if sub.height == 0:
        return None
    spot = pl.DataFrame({C.TIMESTAMP: pl_times(timestamps), "spot": close})
    sub = sub.join(spot, on=C.TIMESTAMP, how="inner")
    lo = int(spec.tenor_days * (1 - CHAIN_DTE_TOLERANCE))
    hi = int(spec.tenor_days * (1 + CHAIN_DTE_TOLERANCE))
    picks = select_by_moneyness(sub, spec.moneyness, spec.right, lo, hi)
    n = len(timestamps)
    roll_idx = np.arange(0, n, max(spec.roll_every, 1))
    pick_ts = np_times(picks.get_column(C.TIMESTAMP))
    pick_ids = picks.get_column("option_id").to_list()
    held: list[str | None] = [None] * n
    current: str | None = None
    for t in range(n):
        if t in set(roll_idx.tolist()) or current is None:
            k = int(np.searchsorted(pick_ts, timestamps[t], side="right")) - 1
            if k >= 0 and pick_ts[k] == timestamps[t]:
                current = str(pick_ids[k])
        held[t] = current
    prices = sub.select(
        C.TIMESTAMP, "option_id", "mid", "strike", *[g for g in GREEKS if g in sub.columns]
    ).unique(subset=[C.TIMESTAMP, "option_id"], keep="first")
    rows = pl.DataFrame(
        {C.TIMESTAMP: pl_times(timestamps), "option_id": held, "prev_id": [None, *held[:-1]]}
    )
    cur = rows.join(prices, on=[C.TIMESTAMP, "option_id"], how="left")
    prev = rows.join(
        prices.rename({"option_id": "prev_id", "mid": "prev_mid"}).select(
            C.TIMESTAMP, "prev_id", "prev_mid"
        ),
        on=[C.TIMESTAMP, "prev_id"],
        how="left",
    )
    mid = cur.get_column("mid").to_numpy().astype(np.float64)
    held_now = prev.get_column("prev_mid").to_numpy().astype(np.float64)
    # an expired contract missing from the chain is worth its intrinsic value
    terms = {
        str(r[0]): (float(r[1]), str(r[2]))
        for r in sub.select("option_id", "strike", "expiry").unique("option_id").iter_rows()
    }
    today = timestamps.astype("datetime64[D]")
    for t, pid in enumerate(rows.get_column("prev_id").to_list()):
        if np.isfinite(held_now[t]) or pid is None or pid not in terms:
            continue
        old_strike, exp = terms[pid]
        if np.datetime64(exp[:10]) <= today[t]:
            payoff = (
                close[t] - old_strike if spec.right is OptionRight.CALL else old_strike - close[t]
            )
            held_now[t] = max(payoff, 0.0)
    prev_mid = np.concatenate(([np.nan], mid[:-1]))
    with np.errstate(divide="ignore", invalid="ignore"):
        ret = np.where(prev_mid > 0, held_now / prev_mid - 1.0, np.nan)
    inst = option_instrument_id(underlying, spec)
    roll = np.zeros(n)
    roll[roll_idx] = 1.0
    frame = pl.DataFrame(
        {
            C.TIMESTAMP: pl_times(timestamps),
            C.INSTRUMENT: [inst] * n,
            C.CLOSE: mid,
            C.RETURN: ret,
            "strike": cur.get_column("strike").to_numpy(),
            "roll": roll,
            **{g: cur.get_column(g).to_numpy() for g in GREEKS if g in cur.columns},
        }
    ).filter(pl.col(C.CLOSE).is_finite())
    return (frame, inst) if frame.height else None


@dataclass(frozen=True)
class OptionLeg:
    """One leg of an option structure: ``sign`` +1 long / -1 short, ``ratio`` of notional."""

    spec: RollingOption
    sign: float
    ratio: float = 1.0


def build_option_data(
    data: Any,
    underlyings: list[str],
    specs: list[RollingOption],
    vol_premium: float,
    rate: float,
    chain: Any = None,
) -> Any:
    """Synthetic rolling option instruments for ``underlyings`` (``MarketData`` or ``None``).

    Uses the chain when it has contracts for an underlying, otherwise Black-Scholes with
    implied vol (an ``iv`` field) or trailing realized vol (``model_priced`` is then set).
    """
    from backbone.core import columns as C
    from backbone.core.calendar import periods_per_year_for
    from backbone.core.types import AssetClass, Instrument, MarketData

    frames: list[pl.DataFrame] = []
    meta: dict[str, Instrument] = {}
    model_priced = False
    ppy = periods_per_year_for(data)
    chain_frame = chain.frame if chain is not None else None
    if chain_frame is not None and "underlying" not in chain_frame.columns:
        chain_frame = None
    for und in underlyings:
        if und not in data.instruments:
            continue
        j = data.instruments.index(und)
        close = data.panel(C.CLOSE)[:, j]
        iv = data.panel(IV_FIELD)[:, j] if data.has_field(IV_FIELD) else None
        vol = volatility_for(close, iv, ppy, vol_premium)
        for spec in specs:
            built = (
                chain_option_frame(data.timestamps, und, close, chain_frame, spec)
                if chain_frame is not None
                else None
            )
            if built is None:
                built = synthetic_option_frame(data.timestamps, und, close, vol, spec, rate)
                model_priced = True
            frame, inst = built
            frames.append(frame)
            meta[inst] = Instrument(
                id=inst,
                symbol=inst,
                asset_class=AssetClass.OPTION,
                underlying=und,
                right=spec.right,
                strike=spec.moneyness,
                name=f"Rolling {spec.label} on {und}",
            )
    if not frames:
        return None
    merged = pl.concat(frames, how="diagonal_relaxed")
    return MarketData(merged, data.frequency, meta, metadata={"model_priced": model_priced})
