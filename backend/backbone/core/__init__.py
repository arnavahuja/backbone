"""Core domain types, plugin interfaces and the plugin registry.

Plugin authors normally only import from here::

    from backbone.core import Strategy, StrategyParams, TargetFrame, register
"""

from backbone.core import columns
from backbone.core.errors import BackboneError
from backbone.core.interfaces import (
    ChartBuilder,
    ChartInput,
    ConstructionContext,
    Context,
    CostContext,
    CostModel,
    DataRequirements,
    DataSource,
    FillModel,
    Metric,
    MetricContext,
    Overlay,
    OverlayContext,
    PortfolioConstructor,
    SlippageModel,
    SourceEnvironment,
    Strategy,
    UniverseProvider,
)
from backbone.core.params import (
    ChartParams,
    ConstructorParams,
    CostParams,
    MetricParams,
    OverlayParams,
    PluginParams,
    SourceParams,
    StrategyParams,
    UniverseParams,
)
from backbone.core.registry import PluginKind, register, registry
from backbone.core.types import (
    AssetClass,
    Frequency,
    Instrument,
    MarketData,
    TargetFrame,
    TargetKind,
)

__all__ = [
    "AssetClass",
    "BackboneError",
    "ChartBuilder",
    "ChartInput",
    "ChartParams",
    "ConstructionContext",
    "ConstructorParams",
    "Context",
    "CostContext",
    "CostModel",
    "CostParams",
    "DataRequirements",
    "DataSource",
    "FillModel",
    "Frequency",
    "Instrument",
    "MarketData",
    "Metric",
    "MetricContext",
    "MetricParams",
    "Overlay",
    "OverlayContext",
    "OverlayParams",
    "PluginKind",
    "PluginParams",
    "PortfolioConstructor",
    "SlippageModel",
    "SourceEnvironment",
    "SourceParams",
    "Strategy",
    "StrategyParams",
    "TargetFrame",
    "TargetKind",
    "UniverseParams",
    "UniverseProvider",
    "columns",
    "register",
    "registry",
]
