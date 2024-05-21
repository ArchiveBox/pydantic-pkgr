from django.conf import settings
from django.utils.module_loading import import_string


PYDANTIC_PKGR_GET_ALL_BINARIES  = getattr(settings, 'PYDANTIC_PKGR_GET_ALL_BINARIES', 'pydantic_pkgr.views.get_all_binaries')
PYDANTIC_PKGR_GET_BINARY        = getattr(settings, 'PYDANTIC_PKGR_GET_BINARY', 'pydantic_pkgr.views.get_binary')


if isinstance(PYDANTIC_PKGR_GET_ALL_BINARIES, str):
    PYDANTIC_PKGR_GET_ALL_BINARIES = import_string(PYDANTIC_PKGR_GET_ALL_BINARIES)

if isinstance(PYDANTIC_PKGR_GET_BINARY, str):
    PYDANTIC_PKGR_GET_BINARY = import_string(PYDANTIC_PKGR_GET_BINARY)

