import os
import sys
import shutil
import operator

from typing import Callable, Any, Optional, Type, List, Dict, Annotated, ClassVar, Literal, cast, TYPE_CHECKING
from typing_extensions import Self
from collections import namedtuple
from pathlib import Path
from subprocess import run, PIPE, CompletedProcess

from pydantic_core import core_schema, ValidationError
from pydantic import BaseModel, Field, TypeAdapter, AfterValidator, validate_call, GetCoreSchemaHandler, ConfigDict, computed_field


def validate_bin_provider_name(name: str) -> str:
    assert 1 < len(name) < 16, 'BinProvider names must be between 1 and 16 characters long'
    assert name.replace('_', '').isalnum(), 'BinProvider names can only contain a-Z0-9 and underscores'
    assert name[0].isalpha(), 'BinProvider names must start with a letter'
    return name

BinProviderName = Annotated[str, AfterValidator(validate_bin_provider_name)]
# in practice this is essentially BinProviderName: Literal['env', 'pip', 'apt', 'brew', 'npm', 'vendor']
# but because users can create their own BinProviders we cant restrict it to a preset list of literal names


from .semver import SemVer


def func_takes_args_or_kwargs(lambda_func: Callable[..., Any]) -> bool:
    """returns True if a lambda func takes args/kwargs of any kind, otherwise false if it's pure/argless"""
    code = lambda_func.__code__
    has_args = code.co_argcount > 0
    has_varargs = code.co_flags & 0x04 != 0
    has_varkw = code.co_flags & 0x08 != 0
    return has_args or has_varargs or has_varkw


@validate_call
def bin_name(bin_path_or_name: str | Path) -> str:
    name = Path(bin_path_or_name).name
    assert 1 <= len(name) < 64, 'Binary names must be between 1 and 63 characters long'
    assert name.replace('-', '').replace('_', '').replace('.', '').isalnum(), (
        f'Binary name can only contain a-Z0-9-_.: {name}')
    assert name[0].isalpha(), 'Binary names must start with a letter'
    return name

BinName = Annotated[str, AfterValidator(bin_name)]

@validate_call
def path_is_file(path: Path | str) -> Path:
    path = Path(path) if isinstance(path, str) else path
    assert path.is_file(), f'Path is not a file: {path}'
    return path

HostExistsPath = Annotated[Path, AfterValidator(path_is_file)]

@validate_call
def path_is_executable(path: HostExistsPath) -> HostExistsPath:
    assert os.access(path, os.X_OK), f'Path is not executable (fix by running chmod +x {path})'
    return path

@validate_call
def path_is_script(path: HostExistsPath) -> HostExistsPath:
    SCRIPT_EXTENSIONS = ('.py', '.js', '.sh')
    assert path.suffix.lower() in SCRIPT_EXTENSIONS, 'Path is not a script (does not end in {})'.format(', '.join(SCRIPT_EXTENSIONS))
    return path

HostExecutablePath = Annotated[HostExistsPath, AfterValidator(path_is_executable)]

@validate_call
def path_is_abspath(path: Path) -> Path:
    path = path.expanduser().absolute()   # resolve ~/ -> /home/<username/ and ../../
    assert path.resolve()                 # make sure symlinks can be resolved, but dont return resolved link
    return path

HostAbsPath = Annotated[HostExistsPath, AfterValidator(path_is_abspath)]
HostBinPath = Annotated[HostExistsPath, AfterValidator(path_is_abspath)] # removed: AfterValidator(path_is_executable)
# not all bins need to be executable to be bins, some are scripts

@validate_call
def bin_abspath(bin_path_or_name: BinName | Path) -> HostBinPath | None:
    assert bin_path_or_name

    if str(bin_path_or_name).startswith('/'):
        # already a path, get its absolute form
        abspath = Path(bin_path_or_name).expanduser().absolute()
    else:
        # not a path yet, get path using shutil.which
        binpath = shutil.which(bin_path_or_name)
        if not binpath:
            return None
        abspath = Path(binpath).expanduser().absolute()

    try:
        return TypeAdapter(HostBinPath).validate_python(abspath)
    except ValidationError:
        return None


@validate_call
def bin_version(bin_path: HostBinPath, args=('--version',)) -> SemVer | None:
    return SemVer(run([str(bin_path), *args], stdout=PIPE, text=True).stdout.strip())


class ShallowBinary(BaseModel):
    """
    Shallow version of Binary used as a return type for BinProvider methods (e.g. load_or_install()).
    (doesn't implement full Binary interface, but can be used to populate a full loaded Binary instance)
    """
    model_config = ConfigDict(extra='ignore', populate_by_name=True, validate_defaults=True)


    name: BinName = ''

    providers_supported: List['BinProvider'] = Field(default=[], alias='providers')

    loaded_provider: BinProviderName = Field(default='env', alias='provider')
    loaded_abspath: HostBinPath = Field(alias='abspath')
    loaded_version: SemVer = Field(alias='version')

    @computed_field                                                                                           # type: ignore[misc]  # see mypy issue #1362
    @property
    def is_executable(self) -> bool:
        try:
            assert self.loaded_abspath and path_is_executable(self.loaded_abspath)
            return True
        except (ValidationError, AssertionError):
            return False

    @computed_field                                                                                           # type: ignore[misc]  # see mypy issue #1362
    @property
    def is_script(self) -> bool:
        try:
            assert self.loaded_abspath and path_is_script(self.loaded_abspath)
            return True
        except (ValidationError, AssertionError):
            return False

    @computed_field                                                                                           # type: ignore[misc]  # see mypy issue #1362
    @property
    def is_valid(self) -> bool:
        return bool(
            self.name
            and self.loaded_abspath
            and self.loaded_version
            and (self.is_executable or self.is_script)
        )

    @computed_field
    @property
    def loaded_respath(self) -> HostBinPath | None:
        return self.loaded_abspath and self.loaded_abspath.resolve()

    def exec(self, args) -> CompletedProcess:
        return run([self.abspath, *args], stdout=PIPE, stderr=PIPE, text=True)


def is_valid_install_string(pkgs_str: str) -> str:
    """Make sure a string is a valid install string for a package manager, e.g. 'yt-dlp ffmpeg'"""
    assert pkgs_str
    assert all(len(pkg) > 1 for pkg in pkgs_str.split(' '))
    return pkgs_str

def is_valid_python_dotted_import(import_str: str) -> str:
    assert import_str and import_str.replace('.', '').replace('_', '').isalnum()
    return import_str

InstallStr = Annotated[str, AfterValidator(is_valid_install_string)]

LazyImportStr = Annotated[str, AfterValidator(is_valid_python_dotted_import)]

ProviderHandler = Callable[..., Any] | Callable[[], Any]                               # must take no args [], or [bin_name: str, **kwargs]
#ProviderHandlerStr = Annotated[str, AfterValidator(lambda s: s.startswith('self.'))]
ProviderHandlerRef = LazyImportStr | ProviderHandler
ProviderLookupDict = Dict[str, LazyImportStr]
ProviderType = Literal['abspath', 'version', 'subdeps', 'install']


# class Host(BaseModel):
#     machine: str
#     system: str
#     platform: str
#     in_docker: bool
#     in_qemu: bool
#     python: str



class BinProvider(BaseModel):
    model_config = ConfigDict(extra='ignore', populate_by_name=True, validate_defaults=True)
    
    name: BinProviderName = ''
    
    abspath_provider: ProviderLookupDict = Field(default={'*': 'self.on_get_abspath'}, exclude=True)
    version_provider: ProviderLookupDict = Field(default={'*': 'self.on_get_version'}, exclude=True)
    subdeps_provider: ProviderLookupDict = Field(default={'*': 'self.on_get_subdeps'}, exclude=True)
    install_provider: ProviderLookupDict = Field(default={'*': 'self.on_install'}, exclude=True)

    _abspath_cache: ClassVar = {}
    _version_cache: ClassVar = {}
    _install_cache: ClassVar = {}

    # def provider_version(self) -> SemVer | None:
    #     """Version of the actual underlying package manager (e.g. pip v20.4.1)"""
    #     if self.name in ('env', 'vendor'):
    #         return SemVer('0.0.0')
    #     installer_binpath = Path(shutil.which(self.name)).resolve()
    #     return bin_version(installer_binpath)

    # def provider_host(self) -> Host:
    #     """Information about the host env, archictecture, and OS needed to select & build packages"""
    #     p = platform.uname()
    #     return Host(
    #         machine=p.machine,
    #         system=p.system,
    #         platform=platform.platform(),
    #         python=sys.implementation.name,
    #         in_docker=os.environ.get('IN_DOCKER', '').lower() == 'true',
    #         in_qemu=os.environ.get('IN_QEMU', '').lower() == 'true',
    #     )

    def get_default_providers(self):
        return self.get_providers_for_bin('*')

    def resolve_provider_func(self, provider_func: ProviderHandlerRef | None) -> ProviderHandler | None:
        if provider_func is None:
            return None

        # if provider_func is a dotted path to a function on self, swap it for the actual function
        if isinstance(provider_func, str) and provider_func.startswith('self.'):
            provider_func = getattr(self, provider_func.split('self.', 1)[-1])

        # if provider_func is a dot-formatted import string, import the function
        if isinstance(provider_func, str):
            try:
                from django.utils.module_loading import import_string
            except ImportError:
                from importlib import import_module
                import_string = import_module

            package_name, module_name, classname, path = provider_func.split('.', 3)   # -> abc, def, ghi.jkl

            # get .ghi.jkl nested attr present on module abc.def
            imported_module = import_string(f'{package_name}.{module_name}.{classname}')
            provider_func = operator.attrgetter(path)(imported_module)

            # # abc.def.ghi.jkl  -> 1, 2, 3
            # for idx in range(1, len(path)):
            #     parent_path = '.'.join(path[:-idx])  # abc.def.ghi
            #     try:
            #         parent_module = import_string(parent_path)
            #         provider_func = getattr(parent_module, path[-idx])
            #     except AttributeError, ImportError:
            #         continue

        assert provider_func, (
            f'{self.__class__.__name__} provider func for {bin_name} was not a function or dotted-import path: {provider_func}')

        return TypeAdapter(ProviderHandler).validate_python(provider_func)

    @validate_call
    def get_providers_for_bin(self, bin_name: str) -> ProviderLookupDict:
        providers_for_bin = {
            'abspath': self.abspath_provider.get(bin_name),
            'version': self.version_provider.get(bin_name),
            'subdeps': self.subdeps_provider.get(bin_name),
            'install': self.install_provider.get(bin_name),
        }
        only_set_providers_for_bin = {k: v for k, v in providers_for_bin.items() if v is not None}
        
        return only_set_providers_for_bin

    @validate_call
    def get_provider_for_action(self, bin_name: BinName, provider_type: ProviderType, default_provider: Optional[ProviderHandlerRef]=None, overrides: Optional[ProviderLookupDict]=None) -> ProviderHandler:
        """
        Get the provider func for a given key + Dict of provider callbacks + fallback default provider.
        e.g. get_provider_for_action(bin_name='yt-dlp', 'install', default_provider=self.on_install, ...) -> Callable
        """

        provider_func_ref = (
            (overrides or {}).get(provider_type)
            or self.get_providers_for_bin(bin_name).get(provider_type)
            or self.get_default_providers().get(provider_type)
            or default_provider
        )
        # print('getting provider for action', bin_name, provider_type, provider_func)

        provider_func = self.resolve_provider_func(provider_func_ref)

        assert provider_func, f'No {self.name} provider func was found for {bin_name} in: {self.__class__.__name__}.'

        return provider_func

    @validate_call
    def call_provider_for_action(self, bin_name: BinName, provider_type: ProviderType, default_provider: Optional[ProviderHandlerRef]=None, overrides: Optional[ProviderLookupDict]=None, **kwargs) -> Any:
        provider_func: ProviderHandler = self.get_provider_for_action(
            bin_name=bin_name,
            provider_type=provider_type,
            default_provider=default_provider,
            overrides=overrides,
        )
        if not func_takes_args_or_kwargs(provider_func):
            # if it's a pure argless lambdas, dont pass bin_path and other **kwargs
            provider_func_without_args = cast(Callable[[], Any], provider_func)
            return provider_func_without_args()

        provider_func = cast(Callable[..., Any], provider_func)
        return provider_func(bin_name, **kwargs)



    def on_get_abspath(self, bin_name: BinName, **context) -> HostBinPath | None:
        # print(f'[*] {self.__class__.__name__}: Getting abspath for {bin_name}...')
        try:
            return bin_abspath(bin_name)
        except ValidationError:
            return None

    def on_get_version(self, bin_name: BinName, abspath: Optional[HostBinPath]=None, **context) -> SemVer | None:
        abspath = abspath or self._abspath_cache.get(bin_name) or self.get_abspath(bin_name)
        if not abspath: return None

        # print(f'[*] {self.__class__.__name__}: Getting version for {bin_name}...')
        try:
            return bin_version(abspath)
        except ValidationError:
            return None

    def on_get_subdeps(self, bin_name: BinName, **context) -> InstallStr:
        # print(f'[*] {self.__class__.__name__}: Getting subdependencies for {bin_name}')
        # ... subdependency calculation logic here
        return TypeAdapter(InstallStr).validate_python(bin_name)


    def on_install(self, bin_name: BinName, subdeps: Optional[InstallStr]=None, **context):
        subdeps = subdeps or self.get_subdeps(bin_name)
        print(f'[*] {self.__class__.__name__}: Installing subdependencies for {bin_name} ({subdeps})')
        # ... install logic here
        assert True


    @validate_call
    def get_abspath(self, bin_name: BinName, overrides: Optional[ProviderLookupDict]=None) -> HostBinPath | None:
        abspath = self.call_provider_for_action(
            bin_name=bin_name,
            provider_type='abspath',
            default_provider=self.on_get_abspath,
            overrides=overrides,
        )
        if not abspath:
            return None
        result = TypeAdapter(HostBinPath).validate_python(abspath)
        self._abspath_cache[bin_name] = result
        return result

    @validate_call
    def get_version(self, bin_name: BinName, abspath: Optional[HostBinPath]=None, overrides: Optional[ProviderLookupDict]=None) -> SemVer | None:
        version = self.call_provider_for_action(
            bin_name=bin_name,
            provider_type='version',
            default_provider=self.on_get_version,
            overrides=overrides,
            abspath=abspath,
        )
        if not version:
            return None
        result = SemVer(version)
        self._version_cache[bin_name] = result
        return result

    @validate_call
    def get_subdeps(self, bin_name: BinName, overrides: Optional[ProviderLookupDict]=None) -> InstallStr:
        subdeps = self.call_provider_for_action(
            bin_name=bin_name,
            provider_type='subdeps',
            default_provider=self.on_get_subdeps,
            overrides=overrides,
        )
        if not subdeps:
            subdeps = bin_name
        result = TypeAdapter(InstallStr).validate_python(subdeps)
        return result

    @validate_call
    def install(self, bin_name: BinName, overrides: Optional[ProviderLookupDict]=None) -> ShallowBinary | None:
        subdeps = self.get_subdeps(bin_name, overrides=overrides)

        self.call_provider_for_action(
            bin_name=bin_name,
            provider_type='install',
            default_provider=self.on_install,
            overrides=overrides,
            subdeps=subdeps,
        )

        installed_abspath = self.get_abspath(bin_name)
        assert installed_abspath, f'Unable to find {bin_name} abspath after installing with {self.name}'

        installed_version = self.get_version(bin_name, abspath=installed_abspath)
        assert installed_version, f'Unable to find {bin_name} version after installing with {self.name}'
        
        result = ShallowBinary(
            name=bin_name,
            loaded_provider=self.name,
            loaded_abspath=installed_abspath,
            loaded_version=installed_version,
            providers_supported=[self],
        )
        self._install_cache[bin_name] = result
        return result

    @validate_call
    def load(self, bin_name: BinName, overrides: Optional[ProviderLookupDict]=None, cache: bool=False) -> ShallowBinary | None:
        installed_abspath = None
        installed_version = None

        if cache:
            installed_bin = self._install_cache.get(bin_name)
            if installed_bin:
                return installed_bin
            installed_abspath = self._abspath_cache.get(bin_name)
            installed_version = self._version_cache.get(bin_name)


        installed_abspath = installed_abspath or self.get_abspath(bin_name, overrides=overrides)
        if not installed_abspath:
            return None

        installed_version = installed_version or self.get_version(bin_name, abspath=installed_abspath, overrides=overrides)
        if not installed_version:
            return None

        return ShallowBinary(
            name=bin_name,
            loaded_provider=self.name,
            loaded_abspath=installed_abspath,
            loaded_version=installed_version,
            providers_supported=[self],
        )

    @validate_call
    def load_or_install(self, bin_name: BinName, overrides: Optional[ProviderLookupDict]=None, cache: bool=True) -> ShallowBinary | None:
        installed = self.load(bin_name, overrides=overrides, cache=cache)
        if not installed:
            installed = self.install(bin_name, overrides=overrides)
        return installed


class PipProvider(BinProvider):
    name: BinProviderName = 'pip'

    def on_install(self, bin_name: str, subdeps: Optional[InstallStr]=None, **context):
        subdeps = subdeps or self.on_get_subdeps(bin_name)
        print(f'[*] {self.__class__.__name__}: Installing subdependencies for {bin_name} ({subdeps})')
        
        proc = run(['pip', 'install', '--upgrade', *subdeps.split(' ')], stdout=PIPE, stderr=PIPE)
        
        if proc.returncode != 0:
            print(proc.stdout.strip().decode())
            print(proc.stderr.strip().decode())
            raise Exception(f'{self.__class__.__name__}: install got returncode {proc.returncode} while installing {subdeps}: {subdeps}')


class AptProvider(BinProvider):
    name: BinProviderName = 'apt'
    
    subdeps_provider: ProviderLookupDict = {
        **BinProvider.__fields__['subdeps_provider'].default,
        'yt-dlp': lambda: 'yt-dlp ffmpeg',
    }

    def on_install(self, bin_name: BinName, subdeps: Optional[InstallStr]=None, **context):
        subdeps = subdeps or self.on_get_subdeps(bin_name)
        print(f'[*] {self.__class__.__name__}: Installing subdependencies for {bin_name} ({subdeps})')
        
        try:
            # if pyinfra is installed, use it
            
            from pyinfra.operations import apt

            apt.update(
                name="Update apt repositories",
                _sudo=True,
                _sudo_user="pyinfra",
            )

            apt.packages(
                name=f"Ensure {bin_name} is installed",
                packages=subdeps.split(' '),
                update=True,
                _sudo=True,
            )
        except ImportError:
            run(['apt-get', 'update', '-qq'])
            proc = run(['apt-get', 'install', '-y', *subdeps.split(' ')], stdout=PIPE, stderr=PIPE)
        
            if proc.returncode != 0:
                print(proc.stdout.strip().decode())
                print(proc.stderr.strip().decode())
                raise Exception(f'{self.__class__.__name__} install got returncode {proc.returncode} while installing {subdeps}: {subdeps}')

class BrewProvider(BinProvider):
    name: BinProviderName = 'brew'

    def on_install(self, bin_name: str, subdeps: Optional[InstallStr]=None, **context):
        subdeps = subdeps or self.on_get_subdeps(bin_name)
        print(f'[*] {self.__class__.__name__}: Installing subdependencies for {bin_name} ({subdeps})')
        
        proc = run(['brew', 'install', *subdeps.split(' ')], stdout=PIPE, stderr=PIPE)
        
        if proc.returncode != 0:
            print(proc.stdout.strip().decode())
            print(proc.stderr.strip().decode())
            raise Exception(f'{self.__class__.__name__} install got returncode {proc.returncode} while installing {subdeps}: {subdeps}')


class EnvProvider(BinProvider):
    name: BinProviderName = 'env'

    abspath_provider: ProviderLookupDict = {
        **BinProvider.__fields__['abspath_provider'].default,
        'python': 'self.get_python_abspath',
    }
    version_provider: ProviderLookupDict = {
        **BinProvider.__fields__['version_provider'].default,
        'python': 'self.get_python_version',
    }

    @staticmethod
    def get_python_abspath():
        return Path(sys.executable)

    @staticmethod
    def get_python_version():
        return '{}.{}.{}'.format(*sys.version_info[:3])


    def on_install(self, bin_name: BinName, subdeps: Optional[InstallStr]=None, **context):
        """The env provider is ready-only and does not install any packages, so this is a no-op"""
        pass
