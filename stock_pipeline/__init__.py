# Stock Pipeline Package
# This file makes stock_pipeline a package and provides version access

try:
    from ._version import __version__
except ImportError:
    # Fallback if _version.py doesn't exist (development install)
    try:
        from setuptools_scm import get_version
        __version__ = get_version(root='..', relative_to=__file__)
    except (ImportError, LookupError):
        __version__ = "unknown"

__all__ = ["__version__"]