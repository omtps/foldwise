"""Glue between the main window (pinefiles.run_gui) and the ui_*.py modules.

run_gui keeps the window's state in local variables; the dialog modules reach them through `A`, a live view: reading
`A.cfg` or `A.status` calls a tiny getter that returns the variable's CURRENT value (so rebinding is seen too).
"""


class App:
    def __init__(self):
        object.__setattr__(self, "_getters", {})

    def _bind(self, getters):
        self._getters.update(getters)

    def binder(self, fn):
        """Wrap a ui_* function so it is called with this App as its first argument."""
        def call(*args, **kwargs):
            return fn(self, *args, **kwargs)
        call.__name__ = fn.__name__
        call.__doc__ = fn.__doc__
        return call

    def __getattr__(self, name):
        try:
            getter = self._getters[name]
        except KeyError:
            raise AttributeError(f"main window has no '{name}'") from None
        return getter()
