# SkyGuard V2 package root (scripts import v2.imd).
# Windows: load torch before numpy/MKL or c10.dll can fail to init.
try:
    import torch as _torch  # noqa: F401
except ImportError:
    pass
