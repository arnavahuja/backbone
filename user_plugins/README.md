# user_plugins

Drop your own plugins here. Every `*.py` file in this folder (not starting with `_`) is
imported at startup; with `BACKBONE_DEV_MODE=true` files are hot-reloaded when they change.
A file that fails to import is skipped and shown on the Dashboard's plugin health panel.

Start from a template:

    backbone new strategy my_strategy      # also: overlay, metric, chart, data_source,
                                           # cost_model, portfolio_constructor

See `docs/howto/` for step-by-step guides.
