from typing import Callable

from django.conf import settings
from django.utils.module_loading import import_string


PYDANTIC_PKGR_GET_ALL_BINARIES  = getattr(settings, 'PYDANTIC_PKGR_GET_ALL_BINARIES', 'pydantic_pkgr.views.get_all_binaries')
PYDANTIC_PKGR_GET_BINARY        = getattr(settings, 'PYDANTIC_PKGR_GET_BINARY', 'pydantic_pkgr.views.get_binary')


if isinstance(PYDANTIC_PKGR_GET_ALL_BINARIES, str):
    get_all_pkgr_binaries = import_string(PYDANTIC_PKGR_GET_ALL_BINARIES)
elif isinstance(PYDANTIC_PKGR_GET_ALL_BINARIES, Callable):
    get_all_pkgr_binaries = PYDANTIC_PKGR_GET_ALL_BINARIES
else:
    raise ValueError('PYDANTIC_PKGR_GET_ALL_BINARIES must be a function or dotted import path to a function')

if isinstance(PYDANTIC_PKGR_GET_BINARY, str):
    get_pkgr_binary = import_string(PYDANTIC_PKGR_GET_BINARY)
elif isinstance(PYDANTIC_PKGR_GET_BINARY, Callable):
    get_pkgr_binary = PYDANTIC_PKGR_GET_BINARY
else:
    raise ValueError('PYDANTIC_PKGR_GET_BINARY must be a function or dotted import path to a function')


