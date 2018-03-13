"""Sets of related view callbacks."""

import inspect

def register(func, dictname):
    _module = inspect.getmodule(func)
    try:
        registry = getattr(_module, dictname)
    except AttributeError:
        registry = {}
        setattr(_module, dictname, registry)
    registry[func.__name__] = func

def callback(func):
    """Mark a function as a callback and store in callbacks dictionary."""
    register(func, 'callbacks')
    return func

def hook(func):
    """Mark a function as a hook and store in hooks dictionary."""
    register(func, 'hooks')
    return func
