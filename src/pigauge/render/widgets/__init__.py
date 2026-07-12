"""Widget registry: layout ``type`` strings to classes (golden rule 3).

The core never imports a concrete widget directly; GaugeScene selects
classes by name from layout YAML via :func:`create_widget`.
"""

from typing import Any

from pigauge.render.widgets.arc import ArcGauge
from pigauge.render.widgets.bar import BarGauge
from pigauge.render.widgets.base import Widget
from pigauge.render.widgets.needle import NeedleGauge
from pigauge.render.widgets.numeric import NumericReadout
from pigauge.render.widgets.sparkline import Sparkline
from pigauge.render.widgets.status import StatusIcon

WIDGET_REGISTRY: dict[str, type[Widget]] = {
    "numeric_readout": NumericReadout,
    "arc_gauge": ArcGauge,
    "needle_gauge": NeedleGauge,
    "bar_gauge": BarGauge,
    "sparkline": Sparkline,
    "status_icon": StatusIcon,
}

__all__ = [
    "WIDGET_REGISTRY",
    "ArcGauge",
    "BarGauge",
    "NeedleGauge",
    "NumericReadout",
    "Sparkline",
    "StatusIcon",
    "Widget",
    "create_widget",
]


def create_widget(config: dict[str, Any]) -> Widget:
    """Instantiate the widget class named by ``config['type']``."""
    widget_type = config.get("type")
    try:
        widget_class = WIDGET_REGISTRY[widget_type]
    except KeyError:
        raise ValueError(
            f"unknown widget type {widget_type!r} (known: {sorted(WIDGET_REGISTRY)})"
        ) from None
    return widget_class(config)
