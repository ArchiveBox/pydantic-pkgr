__package__ = 'pydantic_pkgr'

import sys
import inspect
import importlib
from pathlib import Path


from typing import Any, Optional, Dict, List, Iterable
from typing_extensions import Self
from subprocess import run, PIPE, CompletedProcess


from pydantic_core import ValidationError

from pydantic import BaseModel, Field, model_validator, computed_field, field_validator, validate_call, field_serializer, ConfigDict

from .semver import SemVer
from .binprovider import (
    BinName,
    BinProviderName,
    BinDirPath,
    HostBinPath,
    ShallowBinary,
    BinProvider,
    EnvProvider,
    AptProvider,
    BrewProvider,
    PipProvider,
    ProviderLookupDict,
    bin_name,
    bin_abspath,
    bin_abspaths,
    path_is_script,
    path_is_executable,
)

DEFAULT_PROVIDER = EnvProvider()


class Binary(ShallowBinary):
    model_config = ConfigDict(extra='ignore', populate_by_name=True, validate_defaults=True)

    name: BinName = ''
    description: str = ''

    providers_supported: List[BinProvider] = Field(default=[DEFAULT_PROVIDER], alias='providers')
    provider_overrides: Dict[BinProviderName, ProviderLookupDict] = Field(default={}, alias='overrides')
    
    loaded_provider: Optional[BinProviderName] = Field(default=None, alias='provider')
    loaded_abspath: Optional[HostBinPath] = Field(default=None, alias='abspath')
    loaded_version: Optional[SemVer] = Field(default=None, alias='version')
    
    # bin_filename:  see below
    # is_executable: see below
    # is_script
    # is_valid: see below


    @model_validator(mode='after')
    def validate(self):
        # assert self.name, 'Binary.name must not be empty'
        self.description = self.description or self.name
        
        assert self.providers_supported, f'No providers were given for package {self.name}'

        # pull in any overrides from the binproviders
        for provider in self.providers_supported:
            overrides_by_provider = provider.get_providers_for_bin(self.name)
            if overrides_by_provider:
                self.provider_overrides[provider.name] = {
                    **overrides_by_provider,
                    **self.provider_overrides.get(provider.name, {}),
                }
        return self

    @field_validator('loaded_abspath', mode='before')
    def parse_abspath(cls, value: Any) -> Optional[HostBinPath]:
        return bin_abspath(value) if value else None

    @field_validator('loaded_version', mode='before')
    def parse_version(cls, value: Any) -> Optional[SemVer]:
        return SemVer(value) if value else None

    @field_serializer('provider_overrides', when_used='json')
    def serialize_overrides(self, provider_overrides: Dict[BinProviderName, ProviderLookupDict]) -> Dict[BinProviderName, Dict[str, str]]:
        return {
            provider_name: {
                key: str(val)
                for key, val in overrides.items()
            }
            for provider_name, overrides in provider_overrides.items()
        }

    @computed_field
    @property
    def loaded_abspaths(self) -> Dict[BinProviderName, List[HostBinPath]]:
        if not self.loaded_abspath:
            # binary has not been loaded yet
            return {}
        
        all_bin_abspaths = {self.loaded_provider: [self.loaded_abspath]} if self.loaded_provider  else {}
        for provider in self.providers_supported:
            if not provider.PATH:
                # print('skipping provider', provider.name, provider.PATH)
                continue
            for bin_abspath in bin_abspaths(self.name, PATH=provider.PATH):
                existing = all_bin_abspaths.get(provider.name, [])
                if bin_abspath not in existing:
                    all_bin_abspaths[provider.name] = [
                        *existing,
                        bin_abspath,
                    ]
        return all_bin_abspaths
    

    @computed_field
    @property
    def loaded_bin_dirs(self) -> Dict[BinProviderName, BinDirPath]:
        return {
            provider_name: ':'.join([str(bin_abspath.parent) for bin_abspath in bin_abspaths])
            for provider_name, bin_abspaths in self.loaded_abspaths.items()
        }

    @validate_call
    def install(self) -> Self:
        assert self.name, f'No binary name was provided! {self}'

        if not self.providers_supported:
            return self

        outer_exc = Exception(f'None of the configured providers [{", ".join(p.name for p in self.providers_supported)}] were able to install binary: {self.name}')
        inner_exc = Exception('No providers were available')
        for provider in self.providers_supported:
            try:
                installed_bin = provider.install(self.name, overrides=self.provider_overrides.get(provider.name))
                if installed_bin:
                    # print('INSTALLED', self.name, installed_bin)
                    return self.__class__.model_validate({**self.model_dump(), **installed_bin.model_dump(exclude=('providers_supported',))})
            except Exception as err:
                # print(err)
                inner_exc = err
        raise outer_exc from inner_exc

    @validate_call
    def load(self, cache=True) -> Self:
        assert self.name, f'No binary name was provided! {self}'

        if self.is_valid:
            return self

        if not self.providers_supported:
            return self

        outer_exc = Exception(f'None of the configured providers [{", ".join(p.name for p in self.providers_supported)}] were able to load binary: {self.name}')
        inner_exc = Exception('No providers were available')
        for provider in self.providers_supported:
            try:
                installed_bin = provider.load(self.name, cache=cache, overrides=self.provider_overrides.get(provider.name))
                if installed_bin:
                    # print('LOADED', provider, self.name, installed_bin)
                    return self.__class__.model_validate({**self.model_dump(), **installed_bin.model_dump(exclude=('providers_supported',))})
            except Exception as err:
                # print(err)
                inner_exc = err
        raise outer_exc from inner_exc

    @validate_call
    def load_or_install(self, cache=True) -> Self:
        assert self.name, f'No binary name was provided! {self}'

        if self.is_valid:
            return self

        if not self.providers_supported:
            return self

        outer_exc = Exception(f'None of the configured providers [{", ".join(p.name for p in self.providers_supported)}] were able to find or install binary: {self.name}')
        inner_exc = Exception('No providers were available')
        for provider in self.providers_supported:
            try:
                installed_bin = provider.load_or_install(self.name, overrides=self.provider_overrides.get(provider.name), cache=cache)
                if installed_bin:
                    # print('LOADED_OR_INSTALLED', self.name, installed_bin)
                    return self.__class__.model_validate({**self.model_dump(), **installed_bin.model_dump(exclude=('providers_supported',))})
            except Exception as err:
                # print(err)
                inner_exc = err
        raise outer_exc from inner_exc


class SystemPythonHelpers:
    @staticmethod
    def get_subdeps() -> str:
        return 'python3 python3-minimal python3-pip python3-virtualenv'

    @staticmethod
    def get_abspath() -> str:
        return sys.executable
    
    @staticmethod
    def get_version() -> str:
        return '{}.{}.{}'.format(*sys.version_info[:3])


class SqliteHelpers:
    @staticmethod
    def get_abspath() -> Path:
        import sqlite3
        importlib.reload(sqlite3)
        return Path(inspect.getfile(sqlite3))

    @staticmethod
    def get_version() -> SemVer:
        import sqlite3
        importlib.reload(sqlite3)
        version = sqlite3.version
        assert version
        return SemVer(version)

class DjangoHelpers:
    @staticmethod
    def get_django_abspath() -> str:
        import django
        return inspect.getfile(django)
    

    @staticmethod
    def get_django_version() -> str:
        import django
        return '{}.{}.{} {} ({})'.format(*django.VERSION)

class YtdlpHelpers:
    @staticmethod
    def get_ytdlp_subdeps() -> str:
        return 'yt-dlp ffmpeg'

    @staticmethod
    def get_ytdlp_version() -> str:
        import yt_dlp
        importlib.reload(yt_dlp)

        version = yt_dlp.version.__version__
        assert version
        return version

class PythonBinary(Binary):
    name: BinName = 'python'

    providers_supported: List[BinProvider] = [
        EnvProvider(
            subdeps_provider={'python': 'plugantic.binaries.SystemPythonHelpers.get_subdeps'},
            abspath_provider={'python': 'plugantic.binaries.SystemPythonHelpers.get_abspath'},
            version_provider={'python': 'plugantic.binaries.SystemPythonHelpers.get_version'},
        ),
    ]

class SqliteBinary(Binary):
    name: BinName = 'sqlite'
    providers_supported: List[BinProvider] = [
        EnvProvider(
            version_provider={'sqlite': 'plugantic.binaries.SqliteHelpers.get_version'},
            abspath_provider={'sqlite': 'plugantic.binaries.SqliteHelpers.get_abspath'},
        ),
    ]

class DjangoBinary(Binary):
    name: BinName = 'django'
    providers_supported: List[BinProvider] = [
        EnvProvider(
            abspath_provider={'django': 'plugantic.binaries.DjangoHelpers.get_django_abspath'},
            version_provider={'django': 'plugantic.binaries.DjangoHelpers.get_django_version'},
        ),
    ]





class YtdlpBinary(Binary):
    name: BinName = 'yt-dlp'
    providers_supported: List[BinProvider] = [
        # EnvProvider(),
        PipProvider(version_provider={'yt-dlp': 'plugantic.binaries.YtdlpHelpers.get_ytdlp_version'}),
        BrewProvider(subdeps_provider={'yt-dlp': 'plugantic.binaries.YtdlpHelpers.get_ytdlp_subdeps'}),
        # AptProvider(subdeps_provider={'yt-dlp': lambda: 'yt-dlp ffmpeg'}),
    ]


class WgetBinary(Binary):
    name: BinName = 'wget'
    providers_supported: List[BinProvider] = [EnvProvider(), AptProvider()]


# if __name__ == '__main__':
#     PYTHON_BINARY = PythonBinary()
#     SQLITE_BINARY = SqliteBinary()
#     DJANGO_BINARY = DjangoBinary()
#     WGET_BINARY = WgetBinary()
#     YTDLP_BINARY = YtdlpPBinary()

#     print('-------------------------------------DEFINING BINARIES---------------------------------')
#     print(PYTHON_BINARY)
#     print(SQLITE_BINARY)
#     print(DJANGO_BINARY)
#     print(WGET_BINARY)
#     print(YTDLP_BINARY)

# import json
# print(json.dumps(EnvProvider().model_dump_json(), indent=4))            # ... everything can also be dumped/loaded as json
# print(json.dumps(WgetBinary().model_json_schema(), indent=4))          # ... all types provide OpenAPI-ready JSON schemas
