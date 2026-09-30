"""Backtest runner: resolves plugins, loads data, runs the engine, computes metrics."""

from __future__ import annotations

import functools
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
import structlog

from backbone.analytics.service import AnalyticsService
from backbone.core import columns as C
from backbone.core.calendar import PERIODS_PER_YEAR_KEY, TradingCalendar
from backbone.core.errors import CompatibilityError, ConfigError
from backbone.core.interfaces import (
    CostModel,
    FillModel,
    PortfolioConstructor,
    SlippageModel,
    Strategy,
    UniverseProvider,
)
from backbone.core.registry import PluginKind, registry
from backbone.core.results import BacktestResult
from backbone.core.run_config import BacktestConfig, PluginRef
from backbone.core.specs import MetricValue
from backbone.core.types import DataRequest, FloatArray, MarketData
from backbone.data.fundamentals import asof_join, derive_ratios
from backbone.data.service import DataService
from backbone.engine.base import Engine, RunOptions
from backbone.engine.event.engine import EventEngine
from backbone.engine.pipeline import NamedOverlay, Pipeline
from backbone.engine.vectorized import VectorizedEngine
from backbone.services.compatibility import CompatibilityChecker

log = structlog.get_logger(__name__)

ProgressFn = Callable[[float, str], None]
BENCHMARK_SEPARATOR = ":"


@functools.lru_cache(maxsize=1)
def git_commit() -> str | None:
    """Current git commit of the Backbone checkout (``None`` outside git)."""
    root = Path(__file__).resolve().parents[3]
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() or None


@dataclass
class PreparedRun:
    """Everything needed to execute a run."""

    config: BacktestConfig
    data: MarketData
    strategy: Strategy
    pipeline: Pipeline
    engine: Engine
    options: RunOptions
    plugin_versions: dict[str, str]
    data_refs: dict[str, Any]
    warnings: list[str] = field(default_factory=list)
    factors: pl.DataFrame | None = None


@dataclass(frozen=True)
class Components:
    """Plugin instances of a configuration."""

    strategy: Strategy
    pipeline: Pipeline
    engine: Engine
    universe: UniverseProvider
    versions: dict[str, str]


@dataclass(frozen=True)
class RunOutcome:
    """Result of a run plus provenance."""

    result: BacktestResult
    metrics: dict[str, MetricValue]
    plugin_versions: dict[str, str]
    data_refs: dict[str, Any]
    timings: dict[str, float]
    factors: pl.DataFrame | None = None


def _create(kind: PluginKind, ref: PluginRef, versions: dict[str, str]) -> Any:
    spec = registry(kind).get(ref.name)
    versions[f"{kind}:{spec.name}"] = spec.version
    return spec.create(ref.params)


def parse_benchmark(benchmark: str, default_source: str) -> tuple[str, str]:
    """Split ``"source:SYMBOL"`` (or ``"SYMBOL"``) into ``(source, symbol)``."""
    if BENCHMARK_SEPARATOR in benchmark:
        source, symbol = benchmark.split(BENCHMARK_SEPARATOR, 1)
        return source, symbol
    return default_source, benchmark


class BacktestRunner:
    """Orchestrates a backtest run.

    Args:
        data: Data service.
        analytics: Analytics service.
        checker: Compatibility checker.
        engine_factories: Optional override of engine construction by name.
    """

    def __init__(
        self,
        data: DataService,
        analytics: AnalyticsService | None = None,
        checker: CompatibilityChecker | None = None,
        engine_factories: dict[str, Callable[..., Engine]] | None = None,
    ) -> None:
        self.data = data
        self.analytics = analytics or AnalyticsService()
        self.checker = checker or CompatibilityChecker()
        self.engine_factories = engine_factories or {}

    # ---- engine construction

    def _engine(
        self,
        config: BacktestConfig,
        costs: list[CostModel],
        slippage: SlippageModel | None,
        fill: FillModel | None,
    ) -> Engine:
        name = config.execution.engine
        if name in self.engine_factories:
            return self.engine_factories[name](costs, slippage, fill)
        if name == "vectorized":
            return VectorizedEngine(costs, slippage)
        if name == "event":
            return EventEngine(costs, slippage, fill)
        raise ConfigError(f"Unknown engine '{name}'")

    # ---- data

    def _load_data(
        self, config: BacktestConfig, instruments: list[str], universe_code: str | None = None
    ) -> tuple[MarketData, str | None, dict[str, Any]]:
        spec = config.data
        refs: dict[str, Any] = {}
        bench_id: str | None = None
        wanted = list(instruments)
        bench_source = bench_symbol = None
        if config.benchmark:
            bench_source, bench_symbol = parse_benchmark(config.benchmark, spec.source)
            if bench_source == spec.source and bench_symbol not in wanted:
                wanted.append(bench_symbol)
        request = spec.to_request(wanted, universe=universe_code)
        data = self.data.fetch(request)
        refs["main"] = {"request": request.cache_key(), **_cache_ref(data)}
        if bench_symbol is not None:
            bench_id = bench_symbol
            if bench_source != spec.source:
                breq = spec.to_request([bench_symbol]).model_copy(
                    update={"source": bench_source, "dataset": "daily"}
                )
                bdata = self.data.fetch(breq)
                refs["benchmark"] = {"request": breq.cache_key(), **_cache_ref(bdata)}
                keep = data.timestamps
                bframe = bdata.frame.filter(
                    pl.col(C.TIMESTAMP)
                    .dt.date()
                    .is_in(pl.Series(keep.astype("datetime64[D]")).to_list())
                ).with_columns(
                    pl.col(C.TIMESTAMP)
                    .dt.date()
                    .cast(pl.Datetime("us"))
                    .dt.replace_time_zone("UTC")
                )
                data = data.concat(
                    MarketData(
                        bframe.select([c for c in bframe.columns if c in data.frame.columns]),
                        data.frequency,
                    )
                )
            if bench_id not in data.instruments:
                bench_id = None
        data = self._join_extra(config, data, bench_id, refs)
        return data, bench_id, refs

    def _join_extra(
        self,
        config: BacktestConfig,
        data: MarketData,
        bench_id: str | None,
        refs: dict[str, Any],
    ) -> MarketData:
        """As-of join extra datasets (e.g. fundamentals) onto the prices."""
        if not config.data.extra_datasets:
            return data
        spec = config.data
        instruments = [i for i in data.instruments if i != bench_id]
        for entry in spec.extra_datasets:
            source, _, dataset = entry.partition(BENCHMARK_SEPARATOR)
            if not dataset:
                raise ConfigError(f"Extra dataset '{entry}' must be 'source:dataset'")
            request = DataRequest(
                source=source,
                dataset=dataset,
                instruments=tuple(instruments),
                start=spec.start,
                end=spec.end,
                frequency=spec.frequency,
            )
            extra = self.data.fetch(request)
            refs[f"extra:{entry}"] = {"request": request.cache_key(), **_cache_ref(extra)}
            data = asof_join(data, extra)
        return derive_ratios(data)

    def _load_factors(self, config: BacktestConfig, refs: dict[str, Any]) -> pl.DataFrame | None:
        """Daily factor returns (``timestamp`` + factor columns) for attribution."""
        if not config.factors:
            return None
        source, _, dataset = config.factors.partition(BENCHMARK_SEPARATOR)
        request = DataRequest(
            source=source,
            dataset=dataset or "ff_factors",
            start=config.data.start,
            end=config.data.end,
        )
        factors = self.data.fetch(request)
        refs["factors"] = {"request": request.cache_key(), **_cache_ref(factors)}
        return factors.frame.drop(C.INSTRUMENT)

    def components(self, config: BacktestConfig) -> Components:
        """Instantiate every plugin of a configuration (no data loading)."""
        versions: dict[str, str] = {}
        strategy: Strategy = _create(PluginKind.STRATEGY, config.strategy, versions)
        constructor: PortfolioConstructor | None = (
            _create(PluginKind.PORTFOLIO_CONSTRUCTOR, config.constructor, versions)
            if config.constructor
            else None
        )
        overlays = tuple(
            NamedOverlay(ref.name, _create(PluginKind.OVERLAY, ref, versions))
            for ref in config.overlays
        )
        costs: list[CostModel] = [_create(PluginKind.COST_MODEL, r, versions) for r in config.costs]
        slippage: SlippageModel | None = (
            _create(PluginKind.SLIPPAGE_MODEL, config.slippage, versions)
            if config.slippage
            else None
        )
        fill: FillModel | None = (
            _create(PluginKind.FILL_MODEL, config.fill_model, versions)
            if config.fill_model
            else None
        )
        universe_ref = config.data.universe or PluginRef(name="static")
        universe: UniverseProvider = _create(PluginKind.UNIVERSE, universe_ref, versions)
        engine = self._engine(config, costs, slippage, fill)
        return Components(strategy, Pipeline(constructor, overlays), engine, universe, versions)

    # ---- preparation

    def prepare(self, config: BacktestConfig) -> PreparedRun:
        """Validate the config, instantiate plugins and load data.

        Raises:
            CompatibilityError: If the configuration is invalid.
        """
        report = self.checker.check(config)
        if not report.ok:
            raise CompatibilityError(
                "Invalid run configuration",
                details={"issues": [i.model_dump() for i in report.issues]},
            )
        warnings = [i.message for i in report.issues]
        comps = self.components(config)
        strategy, universe = comps.strategy, comps.universe
        candidates = universe.candidates(list(config.data.instruments))
        universe_code = universe.request_universe()

        data, bench_id, refs = self._load_data(config, candidates, universe_code)
        factors = self._load_factors(config, refs)
        data, locked = self._apply_split(config, data)
        if locked:
            warnings.append(f"Test period locked: data truncated at {locked}")
        calendar = TradingCalendar(config.execution.calendar)
        ppy = calendar.periods_per_year(data.frequency)
        data = data.with_metadata(**{PERIODS_PER_YEAR_KEY: ppy})
        if data.is_empty():
            raise ConfigError("No data in the selected date range")
        if bench_id:
            data = data.with_metadata(benchmark_id=bench_id)
        chain = self._load_chain(config, data, refs)
        data, strategy_synthetic = self._augment(comps, data, chain)
        if data.metadata.get("model_priced"):
            warnings.append("Option prices are model-priced (Black-Scholes), not market prices")

        if universe_code:  # the source decided the instruments (point-in-time universe)
            strat_instruments = tuple(i for i in data.instruments if i != bench_id)
        else:
            strat_instruments = tuple(i for i in data.instruments if i in set(candidates))
        strat_instruments = (*strat_instruments, *strategy_synthetic)
        needs_bench = strategy.data_requirements().needs_benchmark
        if needs_bench and bench_id and bench_id not in strat_instruments:
            strat_instruments = (*strat_instruments, bench_id)
        membership = self._membership(universe, data, strat_instruments)
        options = RunOptions(
            periods_per_year=ppy,
            benchmark_id=bench_id,
            strategy_instruments=tuple(sorted(strat_instruments)),
            membership=membership,
        )
        return PreparedRun(
            config,
            data,
            strategy,
            comps.pipeline,
            comps.engine,
            options,
            comps.versions,
            refs,
            warnings,
            factors,
        )

    def _load_chain(
        self, config: BacktestConfig, data: MarketData, refs: dict[str, Any]
    ) -> MarketData | None:
        """Option chains for the underlyings, if configured."""
        if not config.data.options_chain:
            return None
        source, _, dataset = config.data.options_chain.partition(BENCHMARK_SEPARATOR)
        request = DataRequest(
            source=source,
            dataset=dataset or "optionm_chain",
            instruments=data.instruments,
            start=config.data.start,
            end=config.data.end,
        )
        chain = self.data.fetch(request)
        refs["options_chain"] = {"request": request.cache_key(), **_cache_ref(chain)}
        return chain

    @staticmethod
    def _augment(
        comps: Components, data: MarketData, chain: MarketData | None
    ) -> tuple[MarketData, tuple[str, ...]]:
        """Add synthetic instruments (e.g. rolling options) that plugins provide.

        Any strategy, constructor or overlay may define
        ``synthetic_instruments(data, chain) -> MarketData | None``.
        """
        providers: list[Any] = [
            comps.strategy,
            comps.pipeline.constructor,
            *(o.overlay for o in comps.pipeline.overlays),
        ]
        strategy_ids: tuple[str, ...] = ()
        for provider in providers:
            build = getattr(provider, "synthetic_instruments", None)
            if not callable(build):
                continue
            extra = build(data, chain)
            if extra is None or extra.is_empty():
                continue
            model_priced = bool(extra.metadata.get("model_priced"))
            data = data.concat(extra)
            if model_priced:
                data = data.with_metadata(model_priced=True)
            if provider is comps.strategy:
                strategy_ids = (*strategy_ids, *extra.instruments)
        return data, strategy_ids

    @staticmethod
    def _apply_split(config: BacktestConfig, data: MarketData) -> tuple[MarketData, str | None]:
        split = config.split
        if split is None or split.test_unlocked or split.validation_end is None:
            return data, None
        cutoff = split.validation_end
        return data.between(None, cutoff), cutoff.isoformat()

    @staticmethod
    def _membership(
        universe: UniverseProvider, data: MarketData, strat_instruments: tuple[str, ...]
    ) -> FloatArray:
        sub = data.select_instruments(list(strat_instruments))
        mask_sub = universe.membership(sub)
        full = np.ones((len(data.timestamps), len(data.instruments)))
        rows = np.searchsorted(data.timestamps, sub.timestamps)
        for j, inst in enumerate(sub.instruments):
            col = data.instruments.index(inst)
            full[:, col] = 0.0
            full[rows, col] = mask_sub[:, j]
        return full

    # ---- run

    def run(
        self,
        config: BacktestConfig,
        *,
        progress: ProgressFn | None = None,
        cancelled: Callable[[], bool] | None = None,
        n_trials: int = 1,
        trial_sharpes: list[float] | None = None,
        compute_metrics: bool = True,
    ) -> RunOutcome:
        """Prepare and execute a run, then compute metrics."""
        t0 = time.perf_counter()
        prepared = self.prepare(config)
        t_prep = time.perf_counter()
        opts = prepared.options
        options = RunOptions(
            periods_per_year=opts.periods_per_year,
            benchmark_id=opts.benchmark_id,
            strategy_instruments=opts.strategy_instruments,
            membership=opts.membership,
            progress=progress,
            cancelled=cancelled,
        )
        result = prepared.engine.run(
            config, prepared.data, prepared.strategy, prepared.pipeline, options
        )
        result.metadata["warnings"] = prepared.warnings
        t_run = time.perf_counter()
        metrics = (
            self.analytics.compute(
                result,
                n_trials=n_trials,
                trial_sharpes=trial_sharpes or [],
                factors=prepared.factors,
            )
            if compute_metrics
            else {}
        )
        t_metrics = time.perf_counter()
        timings = {
            "prepare_seconds": round(t_prep - t0, 4),
            "engine_seconds": round(t_run - t_prep, 4),
            "metrics_seconds": round(t_metrics - t_run, 4),
            "total_seconds": round(t_metrics - t0, 4),
        }
        log.info("run_finished", strategy=config.strategy.name, **timings)
        return RunOutcome(
            result, metrics, prepared.plugin_versions, prepared.data_refs, timings, prepared.factors
        )


def _cache_ref(data: MarketData) -> dict[str, Any]:
    meta = data.metadata
    return {k: meta[k] for k in ("cache_key", "cache_version", "source") if k in meta}
