# Stock Pipeline Package
# This file makes stock_pipeline a package and provides version access

try:
    from setuptools_scm import get_version
    __version__ = get_version(root='..', relative_to=__file__)
except (ImportError, LookupError):
    # Fallback for when setuptools_scm is not available
    __version__ = "0.1.dev0"

__all__ = ["__version__"]