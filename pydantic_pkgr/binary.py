__package__ = 'pydantic_pkgr'

import sys
import inspect
import importlib
from pathlib import Path


from typing import Any, Optional, Dict, List, Iterable
from typing_extensions import Self
from subprocess import run, PIPE, CompletedProcess


from pydantic_core import ValidationError

from pydantic import BaseModel, Field, model_validator, computed_field, field_validator, validate_call, field_serializer, ConfigDict, InstanceOf

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

    binproviders_supported: List[InstanceOf[BinProvider]] = Field(default=[DEFAULT_PROVIDER], alias='binproviders')
    provider_overrides: Dict[BinProviderName, ProviderLookupDict] = Field(default={}, alias='overrides')
    
    loaded_binprovider: Optional[InstanceOf[BinProvider]] = Field(default=None, alias='binprovider')
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
        
        assert self.binproviders_supported, f'No providers were given for package {self.name}'

        # pull in any overrides from the binproviders
        for binprovider in self.binproviders_supported:
            overrides_by_handler = binprovider.get_handlers_for_bin(self.name)
            if overrides_by_handler:
                self.provider_overrides[binprovider.name] = {
                    **overrides_by_handler,
                    **self.provider_overrides.get(binprovider.name, {}),
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
            binprovider_name: {
                key: str(val)
                for key, val in overrides.items()
            }
            for binprovider_name, overrides in provider_overrides.items()
        }

    @computed_field
    @property
    def loaded_abspaths(self) -> Dict[BinProviderName, List[HostBinPath]]:
        if not self.loaded_abspath:
            # binary has not been loaded yet
            return {}
        
        all_bin_abspaths = {self.loaded_binprovider.name: [self.loaded_abspath]} if self.loaded_binprovider else {}
        for binprovider in self.binproviders_supported:
            if not binprovider.PATH:
                # print('skipping provider', binprovider.name, binprovider.PATH)
                continue
            for bin_abspath in bin_abspaths(self.name, PATH=binprovider.PATH):
                existing = all_bin_abspaths.get(binprovider.name, [])
                if bin_abspath not in existing:
                    all_bin_abspaths[binprovider.name] = [
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

        if not self.binproviders_supported:
            return self

        outer_exc = Exception(f'None of the configured providers [{", ".join(p.name for p in self.binproviders_supported)}] were able to install binary: {self.name}')
        inner_exc = Exception('No providers were available')
        for binprovider in self.binproviders_supported:
            try:
                installed_bin = binprovider.install(self.name, overrides=self.provider_overrides.get(binprovider.name))
                if installed_bin:
                    # print('INSTALLED', self.name, installed_bin)
                    return self.__class__.model_validate({
                        **self.model_dump(),
                        **installed_bin.model_dump(exclude=('binproviders_supported',)),
                        'loaded_binprovider': binprovider,
                        'binproviders_supported': self.binproviders_supported,
                    })
            except Exception as err:
                # print(err)
                inner_exc = err
        raise outer_exc from inner_exc

    @validate_call
    def load(self, cache=True) -> Self:
        assert self.name, f'No binary name was provided! {self}'

        if self.is_valid:
            return self

        if not self.binproviders_supported:
            return self

        outer_exc = Exception(f'None of the configured providers [{", ".join(p.name for p in self.binproviders_supported)}] were able to load binary: {self.name}')
        inner_exc = Exception('No providers were available')
        for binprovider in self.binproviders_supported:
            try:
                installed_bin = binprovider.load(self.name, cache=cache, overrides=self.provider_overrides.get(binprovider.name))
                if installed_bin:
                    # print('LOADED', binprovider, self.name, installed_bin)
                    return self.__class__.model_validate({
                        **self.model_dump(),
                        **installed_bin.model_dump(exclude=('binproviders_supported',)),
                        'loaded_binprovider': binprovider,
                        'binproviders_supported': self.binproviders_supported,
                    })
            except Exception as err:
                # print(err)
                inner_exc = err
        raise outer_exc from inner_exc

    @validate_call
    def load_or_install(self, cache=True) -> Self:
        assert self.name, f'No binary name was provided! {self}'

        if self.is_valid:
            return self

        if not self.binproviders_supported:
            return self

        outer_exc = Exception(f'None of the configured providers [{", ".join(p.name for p in self.binproviders_supported)}] were able to find or install binary: {self.name}')
        inner_exc = Exception('No providers were available')
        for binprovider in self.binproviders_supported:
            try:
                installed_bin = binprovider.load_or_install(self.name, overrides=self.provider_overrides.get(binprovider.name), cache=cache)
                if installed_bin:
                    # print('LOADED_OR_INSTALLED', self.name, installed_bin)
                    return self.__class__.model_validate({
                        **self.model_dump(),
                        **installed_bin.model_dump(exclude=('binproviders_supported',)),
                        'loaded_binprovider': binprovider,
                        'binproviders_supported': self.binproviders_supported,
                    })
            except Exception as err:
                # print(err)
                inner_exc = err
        raise outer_exc from inner_exc


class SystemPythonHelpers:
    @staticmethod
    def get_packages() -> str:
        return ['python3', 'python3-minimal', 'python3-pip', 'python3-virtualenv']

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
    def get_ytdlp_packages() -> str:
        return ['yt-dlp', 'ffmpeg']

    @staticmethod
    def get_ytdlp_version() -> str:
        import yt_dlp
        importlib.reload(yt_dlp)

        version = yt_dlp.version.__version__
        assert version
        return version

class PythonBinary(Binary):
    name: BinName = 'python'

    binproviders_supported: List[InstanceOf[BinProvider]] = [
        EnvProvider(
            packages_handler={'python': 'plugantic.binaries.SystemPythonHelpers.get_packages'},
            abspath_handler={'python': 'plugantic.binaries.SystemPythonHelpers.get_abspath'},
            version_handler={'python': 'plugantic.binaries.SystemPythonHelpers.get_version'},
        ),
    ]

class SqliteBinary(Binary):
    name: BinName = 'sqlite'
    binproviders_supported: List[InstanceOf[BinProvider]] = [
        EnvProvider(
            version_handler={'sqlite': 'plugantic.binaries.SqliteHelpers.get_version'},
            abspath_handler={'sqlite': 'plugantic.binaries.SqliteHelpers.get_abspath'},
        ),
    ]

class DjangoBinary(Binary):
    name: BinName = 'django'
    binproviders_supported: List[InstanceOf[BinProvider]] = [
        EnvProvider(
            abspath_handler={'django': 'plugantic.binaries.DjangoHelpers.get_django_abspath'},
            version_handler={'django': 'plugantic.binaries.DjangoHelpers.get_django_version'},
        ),
    ]





class YtdlpBinary(Binary):
    name: BinName = 'yt-dlp'
    binproviders_supported: List[InstanceOf[BinProvider]] = [
        # EnvProvider(),
        PipProvider(version_handler={'yt-dlp': 'plugantic.binaries.YtdlpHelpers.get_ytdlp_version'}),
        BrewProvider(packages_handler={'yt-dlp': 'plugantic.binaries.YtdlpHelpers.get_ytdlp_packages'}),
        # AptProvider(packages_handler={'yt-dlp': lambda: ['yt-dlp', 'ffmpeg']}),
    ]


class WgetBinary(Binary):
    name: BinName = 'wget'
    binproviders_supported: List[InstanceOf[BinProvider]] = [EnvProvider(), AptProvider()]


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
