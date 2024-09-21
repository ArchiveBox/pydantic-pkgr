__package__ = 'pydantic_pkgr'


# Unfortunately it must be kept in the same file as BinProvider because of the circular type reference between them
from .binprovider import ShallowBinary      # noqa: F401
