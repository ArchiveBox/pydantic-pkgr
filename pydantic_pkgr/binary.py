__package__ = 'pydantic_pkgr'

from typing import Any, Optional, Dict, List
from typing_extensions import Self

from pydantic import Field, model_validator, computed_field, field_validator, validate_call, field_serializer, ConfigDict, InstanceOf

from .semver import SemVer
from .shallowbinary import ShallowBinary
from .binprovider import BinProvider, EnvProvider
from .base_types import (
    BinName,
    bin_abspath,
    bin_abspaths,
    HostBinPath,
    BinProviderName,
    ProviderLookupDict,
    PATHStr,
    Sha256,
)

DEFAULT_PROVIDER = EnvProvider()


class Binary(ShallowBinary):
    model_config = ConfigDict(extra='allow', populate_by_name=True, validate_defaults=True, validate_assignment=True, from_attributes=True, revalidate_instances='always')

    name: BinName = ''
    description: str = ''

    binproviders_supported: List[InstanceOf[BinProvider]] = Field(default_factory=lambda : [DEFAULT_PROVIDER], alias='binproviders')
    provider_overrides: Dict[BinProviderName, ProviderLookupDict] = Field(default_factory=dict, alias='overrides')
    
    loaded_binprovider: Optional[InstanceOf[BinProvider]] = Field(default=None, alias='binprovider')
    loaded_abspath: Optional[HostBinPath] = Field(default=None, alias='abspath')
    loaded_version: Optional[SemVer] = Field(default=None, alias='version')
    loaded_sha256: Optional[Sha256] = Field(default=None, alias='sha256')
    
    # bin_filename:  see below
    # is_executable: see below
    # is_script
    # is_valid: see below


    @model_validator(mode='after')
    def validate(self):
        # assert self.name, 'Binary.name must not be empty'
        # self.description = self.description or self.name
        
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
            for abspath in bin_abspaths(self.name, PATH=binprovider.PATH):
                existing = all_bin_abspaths.get(binprovider.name, [])
                if abspath not in existing:
                    all_bin_abspaths[binprovider.name] = [
                        *existing,
                        abspath,
                    ]
        return all_bin_abspaths
    

    @computed_field
    @property
    def loaded_bin_dirs(self) -> Dict[BinProviderName, PATHStr]:
        return {
            provider_name: ':'.join([str(bin_abspath.parent) for bin_abspath in bin_abspaths])
            for provider_name, bin_abspaths in self.loaded_abspaths.items()
        }
    
    @computed_field
    @property
    def python_name(self) -> str:
        return self.name.replace('-', '_').replace('.', '_')

    @validate_call
    def install(self, binprovider_name: Optional[BinProviderName]=None, timeout: int=120) -> Self:
        assert self.name, f'No binary name was provided! {self}'

        providers_to_try = self.binproviders_supported
        if binprovider_name:
            providers_to_try = [p for p in providers_to_try if p.name == binprovider_name]
            
        if not providers_to_try:
            return self
        

        inner_exc = Exception('No providers were available')
        errors = {}
        for binprovider in providers_to_try:
            try:
                installed_bin = binprovider.install(self.name, overrides=self.provider_overrides.get(binprovider.name), timeout=timeout)
                if installed_bin is not None and installed_bin.loaded_abspath:
                    # print('INSTALLED', self.name, installed_bin)
                    return self.__class__(**{
                        **self.model_dump(),
                        **installed_bin.model_dump(exclude=('binproviders_supported',)),
                        'loaded_binprovider': binprovider,
                        'binproviders_supported': self.binproviders_supported,
                        'provider_overrides': self.provider_overrides,
                    })
            except Exception as err:
                # print(err)
                inner_exc = err
                errors[binprovider.name] = str(err)
        raise Exception(f'None of the configured providers ({", ".join(p.name for p in providers_to_try)}) were able to install binary: {self.name} ERRORS={errors}') from inner_exc

    @validate_call
    def load(self, cache=False, binprovider_name: Optional[BinProviderName]=None, timeout: int=15) -> Self:
        assert self.name, f'No binary name was provided! {self}'

        if self.is_valid:
            return self

        providers_to_try = self.binproviders_supported
        if binprovider_name:
            providers_to_try = [p for p in providers_to_try if p.name == binprovider_name]

        if not providers_to_try:
            return self

        inner_exc = Exception('No providers were available')
        errors = {}
        for binprovider in providers_to_try:
            try:
                installed_bin = binprovider.load(self.name, cache=cache, overrides=self.provider_overrides.get(binprovider.name), timeout=timeout)
                if installed_bin is not None and installed_bin.loaded_abspath:
                    # print('LOADED', binprovider, self.name, installed_bin)
                    return self.__class__(**{
                        **self.model_dump(),
                        **installed_bin.model_dump(exclude=('binproviders_supported',)),
                        'loaded_binprovider': binprovider,
                        'binproviders_supported': self.binproviders_supported,
                        'provider_overrides': self.provider_overrides,
                    })
                else:
                    continue
            except Exception as err:
                # print(err)
                inner_exc = err
                errors[binprovider.name] = str(err)
        raise Exception(f'None of the configured providers ({", ".join(p.name for p in providers_to_try)}) were able to load binary: {self.name} ERRORS={errors}') from inner_exc

    @validate_call
    def load_or_install(self, cache=False, binprovider_name: Optional[BinProviderName]=None, timeout: int=120) -> Self:
        assert self.name, f'No binary name was provided! {self}'

        if self.is_valid:
            return self

        providers_to_try = self.binproviders_supported
        if binprovider_name:
            providers_to_try = [p for p in providers_to_try if p.name == binprovider_name]

        if not providers_to_try:
            return self

        inner_exc = Exception('No providers were available')
        errors = {}
        for binprovider in providers_to_try:
            try:
                installed_bin = binprovider.load_or_install(self.name, overrides=self.provider_overrides.get(binprovider.name), cache=cache, timeout=timeout)
                if installed_bin is not None and installed_bin.loaded_abspath:
                    # print('LOADED_OR_INSTALLED', self.name, installed_bin)
                    return self.__class__(**{
                        **self.model_dump(),
                        **installed_bin.model_dump(exclude=('binproviders_supported',)),
                        'loaded_binprovider': binprovider,
                        'binproviders_supported': self.binproviders_supported,
                        'provider_overrides': self.provider_overrides,
                    })
                else:
                    continue
            except Exception as err:
                # print(err)
                inner_exc = err
                errors[binprovider.name] = str(err)
                continue
        raise Exception(f'None of the configured providers ({", ".join(p.name for p in providers_to_try)}) were able to find or install binary: {self.name} ERRORS={errors}') from inner_exc
        