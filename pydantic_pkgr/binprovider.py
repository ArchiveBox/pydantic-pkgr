__package__ = "pydantic_pkgr"

import os
import sys
import pwd
import shutil
import hashlib
import operator
import platform
import subprocess

from typing import Callable, Iterable, Any, Optional, List, Dict, ClassVar, cast
from typing_extensions import Self
from pathlib import Path

from pydantic_core import ValidationError
from pydantic import BaseModel, Field, TypeAdapter, validate_call, ConfigDict, InstanceOf, computed_field, model_validator

from .semver import SemVer
from .base_types import (
    BinName,
    BinDirPath,
    HostBinPath,
    BinProviderName,
    ProviderLookupDict,
    PATHStr,
    InstallArgs,
    ProviderHandlerRef,
    ProviderHandler,
    HandlerType,
    Sha256,
    bin_name,
    path_is_executable,
    path_is_script,
    bin_abspath,
    bin_abspaths,
    func_takes_args_or_kwargs,
)

################## GLOBALS ##########################################

OPERATING_SYSTEM = platform.system().lower()
DEFAULT_PATH = "/home/linuxbrew/.linuxbrew/bin:/opt/homebrew/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
DEFAULT_ENV_PATH = os.environ.get("PATH", DEFAULT_PATH)
PYTHON_BIN_DIR = str(Path(sys.executable).parent)

if PYTHON_BIN_DIR not in DEFAULT_ENV_PATH:
    DEFAULT_ENV_PATH = PYTHON_BIN_DIR + ":" + DEFAULT_ENV_PATH


################## VALIDATORS #######################################


# class Host(BaseModel):
#     machine: str
#     system: str
#     platform: str
#     in_docker: bool
#     in_qemu: bool
#     python: str


class ShallowBinary(BaseModel):
    """
    Shallow version of Binary used as a return type for BinProvider methods (e.g. load_or_install()).
    (doesn't implement full Binary interface, but can be used to populate a full loaded Binary instance)
    """

    model_config = ConfigDict(extra="allow", populate_by_name=True, validate_defaults=True, validate_assignment=False, from_attributes=True)

    name: BinName = ""
    description: str = ""

    binproviders_supported: List[InstanceOf["BinProvider"]] = Field(default_factory=list, alias="binproviders")
    provider_overrides: Dict[BinProviderName, "ProviderLookupDict"] = Field(default_factory=dict, alias="overrides")

    loaded_binprovider: InstanceOf["BinProvider"] = Field(alias="binprovider")
    loaded_abspath: HostBinPath = Field(alias="abspath")
    loaded_version: SemVer = Field(alias="version")
    loaded_sha256: Sha256 = Field(alias="sha256")

    def __getattr__(self, item):
        """Allow accessing fields as attributes by both field name and alias name"""
        for field, meta in self.model_fields.items():
            if meta.alias == item:
                return getattr(self, field)
        return super().__getattr__(item)

    @model_validator(mode="after")
    def validate(self):
        self.description = self.description or self.name
        return self

    @computed_field  # type: ignore[misc]  # see mypy issue #1362
    @property
    def bin_filename(self) -> BinName:
        if self.is_script:
            # e.g. '.../Python.framework/Versions/3.11/lib/python3.11/sqlite3/__init__.py' -> sqlite
            name = self.name
        elif self.loaded_abspath:
            # e.g. '/opt/homebrew/bin/wget' -> wget
            name = bin_name(self.loaded_abspath)
        else:
            # e.g. 'ytdlp' -> 'yt-dlp'
            name = bin_name(self.name)
        return name

    @computed_field  # type: ignore[misc]  # see mypy issue #1362
    @property
    def is_executable(self) -> bool:
        try:
            assert self.loaded_abspath and path_is_executable(self.loaded_abspath)
            return True
        except (ValidationError, AssertionError):
            return False

    @computed_field  # type: ignore[misc]  # see mypy issue #1362
    @property
    def is_script(self) -> bool:
        try:
            assert self.loaded_abspath and path_is_script(self.loaded_abspath)
            return True
        except (ValidationError, AssertionError):
            return False

    @computed_field  # type: ignore[misc]  # see mypy issue #1362
    @property
    def is_valid(self) -> bool:
        return bool(self.name and self.loaded_abspath and self.loaded_version and (self.is_executable or self.is_script))

    @computed_field
    @property
    def bin_dir(self) -> BinDirPath | None:
        if not self.loaded_abspath:
            return None
        return TypeAdapter(BinDirPath).validate_python(self.loaded_abspath.parent)

    @computed_field
    @property
    def loaded_respath(self) -> HostBinPath | None:
        return self.loaded_abspath and self.loaded_abspath.resolve()

    @validate_call
    def exec(
        self, bin_name: BinName | HostBinPath = None, cmd: Iterable[str | Path | int | float | bool] = (), cwd: str | Path = ".", quiet=False, **kwargs
    ) -> subprocess.CompletedProcess:
        bin_name = str(bin_name or self.loaded_abspath or self.name)
        if bin_name == self.name:
            assert self.loaded_abspath, "Binary must have a loaded_abspath, make sure to load_or_install() first"
            assert self.loaded_version, "Binary must have a loaded_version, make sure to load_or_install() first"
        assert os.path.isdir(cwd) and os.access(cwd, os.R_OK), f"cwd must be a valid, accessible directory: {cwd}"
        cmd = [str(bin_name), *(str(arg) for arg in cmd)]
        if not quiet:
            print('$', ' '.join(cmd), file=sys.stderr)
        return subprocess.run(cmd, capture_output=True, text=True, cwd=str(cwd), **kwargs)


class BinProvider(BaseModel):
    model_config = ConfigDict(extra='allow', populate_by_name=True, validate_defaults=True, validate_assignment=False, from_attributes=True, revalidate_instances='always')
    name: BinProviderName = ''

    PATH: PATHStr = Field(default=str(Path(sys.executable).parent))        # e.g.  '/opt/homebrew/bin:/opt/archivebox/bin'
    INSTALLER_BIN: BinName = 'env'
    
    euid: Optional[int] = None
    
    version_handler: ProviderLookupDict = Field(default={'*': 'self.on_get_version'}, exclude=True)
    abspath_handler: ProviderLookupDict = Field(default={'*': 'self.on_get_abspath'}, exclude=True)
    packages_handler: ProviderLookupDict = Field(default={'*': 'self.on_get_packages'}, exclude=True)
    install_handler: ProviderLookupDict = Field(default={'*': 'self.on_install'}, exclude=True)

    _abspath_cache: ClassVar = {}
    _version_cache: ClassVar = {}
    _install_cache: ClassVar = {}

    def __getattr__(self, item):
        """Allow accessing fields as attributes by both field name and alias name"""
        if item in ('__fields__', 'model_fields'):
            raise AttributeError(f"'{self.__class__.__name__}' object has no attribute '{item}'")
        
        for field, meta in self.model_fields.items():
            if meta.alias == item:
                return getattr(self, field)
        return super().__getattr__(item)
    
    # def __str__(self) -> str:
    #     return f'{self.name.title()}Provider[{self.INSTALLER_BIN_ABSPATH or self.INSTALLER_BIN})]'

    # def __repr__(self) -> str:
    #     return f'{self.name.title()}Provider[{self.INSTALLER_BIN_ABSPATH or self.INSTALLER_BIN})]'
    
    @property
    def EUID(self):
        """
        Detect the user (UID) to run as when executing this binprovider's INSTALLER_BIN
        e.g. homebrew should never be run as root, we can tell which user to run it as by looking at who owns its binary
        apt should always be run as root, pip should be run as the user that owns the venv, etc.
        """
        
        # use user-provided value if one is set
        if self.euid is not None:
            return self.euid

        # fallback to owner of installer binary
        try:
            installer_bin = self.INSTALLER_BIN_ABSPATH
            if installer_bin:
                return os.stat(installer_bin).st_uid
        except Exception:
            # INSTALLER_BIN_ABSPATH is not always availabe (e.g. at import time, or if it dynamically changes)
            pass

        # fallback to current user
        return os.geteuid()

    
    @computed_field
    @property
    def INSTALLER_BIN_ABSPATH(self) -> HostBinPath | None:
        """Actual absolute path of the underlying package manager (e.g. /usr/local/bin/npm)"""
        abspath = bin_abspath(self.INSTALLER_BIN, PATH=self.PATH) or bin_abspath(self.INSTALLER_BIN)  # find self.INSTALLER_BIN abspath using environment path
        if not abspath:
            # underlying package manager not found on this host, return None
            return None
        return TypeAdapter(HostBinPath).validate_python(abspath)
    
    @property
    def INSTALLER_BINARY(self) -> ShallowBinary | None:
        """Get the loaded binary for this binprovider's INSTALLER_BIN"""
        
        abspath = self.INSTALLER_BIN_ABSPATH
        if not abspath:
            return None
        
        try:
            # try loading it from the BinProvider's own PATH (e.g. ~/test/.venv/bin/pip)
            loaded_bin = self.load(bin_name=self.INSTALLER_BIN)
            if loaded_bin:
                return loaded_bin
        except Exception:
            pass
        
        env = EnvProvider()
        try:
            # try loading it from the env provider (e.g. /opt/homebrew/bin/pip)
            loaded_bin = env.load(bin_name=self.INSTALLER_BIN)
            if loaded_bin:
                return loaded_bin
        except Exception:
            pass
        
        fallback_version = cast(SemVer, SemVer.parse('999.999.999'))  # always return something, not all installers provide a version (e.g. which)
        version = self.get_version(bin_name=self.INSTALLER_BIN, abspath=abspath) or fallback_version
        sha256 = self.get_sha256(bin_name=self.INSTALLER_BIN, abspath=abspath) or hashlib.sha256(b'').hexdigest()
        
        return ShallowBinary(
            name=self.INSTALLER_BIN,
            abspath=abspath,
            binprovider=env,
            version=version,
            sha256=sha256,
        )
    
    @computed_field
    @property
    def is_valid(self) -> bool:
        return bool(self.INSTALLER_BIN_ABSPATH)

    # def installer_host(self) -> Host:
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

    @validate_call
    def exec(self, bin_name: BinName | HostBinPath, cmd: Iterable[str | Path | int | float | bool]=(), cwd: Path | str='.', quiet=False, **kwargs) -> subprocess.CompletedProcess:
        if shutil.which(str(bin_name)):
            bin_abspath = bin_name
        else:
            bin_abspath = self.get_abspath(str(bin_name))
        assert bin_abspath, f'BinProvider {self.name} cannot execute bin_name {bin_name} because it could not find its abspath. (Did {self.__class__.__name__}.load_or_install({bin_name}) fail?)'
        assert os.access(cwd, os.R_OK) and os.path.isdir(cwd), f'cwd must be a valid, accessible directory: {cwd}'
        cmd = [str(bin_abspath), *(str(arg) for arg in cmd)]
        if not quiet:
            print('$', ' '.join(cmd), file=sys.stderr)
            
        # https://stackoverflow.com/a/6037494/2156113
        # copy env and modify it to run the subprocess as the the designated user
        env = kwargs.get('env', {}) or os.environ.copy()
        pw_record = pwd.getpwuid(self.EUID)
        run_as_uid     = pw_record.pw_uid
        run_as_gid     = pw_record.pw_gid
        # update environment variables so that subprocesses dont try to write to /root home directory
        # for things like cache dirs, logs, etc. npm/pip/etc. often try to write to $HOME
        env['PWD']      = str(cwd)
        env['HOME']     = pw_record.pw_dir
        env['LOGNAME']  = pw_record.pw_name
        env['USER']     = pw_record.pw_name
        
        def drop_privileges():
            try:
                os.setuid(run_as_uid)
                os.setgid(run_as_gid)
            except Exception:
                pass
            
        return subprocess.run(cmd, capture_output=True, text=True, cwd=str(cwd), env=env, preexec_fn=drop_privileges, **kwargs)

    def get_default_handlers(self):
        return self.get_handlers_for_bin('*')

    def resolve_handler_func(self, handler_func: ProviderHandlerRef | None) -> ProviderHandler | None:
        if handler_func is None:
            return None

        # if handler_func is already a callable, return it directly
        if isinstance(handler_func, Callable):
            return TypeAdapter(ProviderHandler).validate_python(handler_func)

        # if handler_func is a dotted path to a function on self, swap it for the actual function
        if isinstance(handler_func, str) and handler_func.startswith('self.'):
            handler_func = getattr(self, handler_func.split('self.', 1)[-1])

        # if handler_func is a dot-formatted import string, import the function
        if isinstance(handler_func, str):
            try:
                from django.utils.module_loading import import_string
            except ImportError:
                from importlib import import_module
                import_string = import_module

            package_name, module_name, classname, path = handler_func.split('.', 3)   # -> abc, def, ghi.jkl

            # get .ghi.jkl nested attr present on module abc.def
            imported_module = import_string(f'{package_name}.{module_name}.{classname}')
            handler_func = operator.attrgetter(path)(imported_module)

            # # abc.def.ghi.jkl  -> 1, 2, 3
            # for idx in range(1, len(path)):
            #     parent_path = '.'.join(path[:-idx])  # abc.def.ghi
            #     try:
            #         parent_module = import_string(parent_path)
            #         handler_func = getattr(parent_module, path[-idx])
            #     except AttributeError, ImportError:
            #         continue

        assert handler_func, (
            f'{self.__class__.__name__} handler func for {bin_name} was not a function or dotted-import path: {handler_func}')

        return TypeAdapter(ProviderHandler).validate_python(handler_func)

    @validate_call
    def get_handlers_for_bin(self, bin_name: str) -> ProviderLookupDict:
        handlers_for_bin = {
            'abspath': self.abspath_handler.get(bin_name),
            'version': self.version_handler.get(bin_name),
            'packages': self.packages_handler.get(bin_name),
            'install': self.install_handler.get(bin_name),
        }
        only_set_handlers_for_bin = {k: v for k, v in handlers_for_bin.items() if v is not None}
        
        return only_set_handlers_for_bin

    def get_provider_with_overrides(self, bin_name: BinName, overrides: Optional[ProviderLookupDict]=None):
        if not overrides:
            return self
    
        # created an updated copy of the BinProvider with the overrides applied, then get the handlers on it.
        # important to do this so that any subsequent calls to handler functions down the call chain
        # still have access to the overrides, we don't have to have to pass them down as args all the way down the stack
        updated_binprovider: Self = self.model_copy()
        
        if 'version' in overrides:
            updated_binprovider.version_handler[bin_name] = overrides['version']
        if 'abspath' in overrides:
            updated_binprovider.abspath_handler[bin_name] = overrides['abspath']
        if 'packages' in overrides:
            updated_binprovider.packages_handler[bin_name] = overrides['packages']
        if 'install' in overrides:
            updated_binprovider.install_handler[bin_name] = overrides['install']
            
        return updated_binprovider

    @validate_call
    def get_handler_for_action(self, bin_name: BinName, handler_type: HandlerType, default_handler: Optional[ProviderHandlerRef]=None, overrides: Optional[ProviderLookupDict]=None) -> ProviderHandler:
        """
        Get the handler func for a given key + Dict of handler callbacks + fallback default handler.
        e.g. get_handler_for_action(bin_name='yt-dlp', 'install', default_handler=self.on_install, ...) -> Callable
        """
        
        updated_binprovider = self.get_provider_with_overrides(bin_name=bin_name, overrides=overrides)

        handler_func_ref = (
            (overrides or {}).get(handler_type)
            or updated_binprovider.get_handlers_for_bin(bin_name).get(handler_type)
            or updated_binprovider.get_default_handlers().get(handler_type)
            or default_handler
        )
        # print('getting handler for action', bin_name, handler_type, handler_func)

        handler_func = updated_binprovider.resolve_handler_func(handler_func_ref)

        assert handler_func, f'No {self.name} handler func was found for {bin_name} in: {self.__class__.__name__}.'

        return handler_func

    @validate_call
    def call_handler_for_action(self, bin_name: BinName, handler_type: HandlerType, default_handler: Optional[ProviderHandlerRef]=None, overrides: Optional[ProviderLookupDict]=None, timeout: int=120, **kwargs) -> Any:
        # create a new instance of Self, with the overrides applied to the handlers dicts
        
        handler_func: ProviderHandler = self.get_handler_for_action(
            bin_name=bin_name,
            handler_type=handler_type,
            default_handler=default_handler,
            overrides=overrides,
        )

        def timeout_handler(signum, frame):
            raise TimeoutError(f'{self.__class__.__name__} Timeout while running {handler_type} for Binary {bin_name}')

        # signal ONLY WORKS IN MAIN THREAD, not a viable solution for timeout enforcement! breaks in prod
        # signal.signal(signal.SIGALRM, handler=timeout_handler)
        # signal.alarm(timeout)
        try:
            if not func_takes_args_or_kwargs(handler_func):
                # if it's a pure argless lambdas, dont pass bin_path and other **kwargs
                handler_func_without_args = cast(Callable[[], Any], handler_func)
                return handler_func_without_args()

            handler_func = cast(Callable[..., Any], handler_func)
            return handler_func(bin_name, **kwargs)
        except TimeoutError:
            raise
        # finally:
        #     signal.alarm(0)

    def setup_PATH(self):
        for path in reversed(self.PATH.split(':')):
            if path not in sys.path:
                sys.path.insert(0, path)   # e.g. /opt/archivebox/bin:/bin:/usr/local/bin:...

    def on_get_abspath(self, bin_name: BinName | HostBinPath, **context) -> HostBinPath | None:
        # print(f'[*] {self.__class__.__name__}: Getting abspath for {bin_name}...')

        if not self.PATH:
            return None
        
        return bin_abspath(bin_name, PATH=self.PATH)
    
    def on_get_version(self, bin_name: BinName, abspath: Optional[HostBinPath]=None, **context) -> SemVer | None:
        
        abspath = abspath or self._abspath_cache.get(bin_name) or self.get_abspath(bin_name, quiet=True)
        if not abspath: return None

        # print(f'[*] {self.__class__.__name__}: Getting version for {bin_name}...')
        
        validation_err = None
        
        # Attempt 1: $ <bin_name> --version
        dash_dash_version_result = self.exec(bin_name=abspath, cmd=['--version'], timeout=10, quiet=True)
        dash_dash_version_out = dash_dash_version_result.stdout.strip()
        try:
            version = SemVer.parse(dash_dash_version_out)
            assert version, f"Could not parse version from $ {bin_name} --version: {dash_dash_version_result.stdout}\n{dash_dash_version_result.stderr}\n".strip()
            return version
        except (ValidationError, AssertionError) as err:
            validation_err = err
        
        # Attempt 2: $ <bin_name> -version
        dash_version_out = self.exec(bin_name=abspath, cmd=["-version"], timeout=10, quiet=True).stdout.strip()
        try:
            version = SemVer.parse(dash_version_out)
            assert version, f"Could not parse version from $ {bin_name} -version: {dash_version_out}".strip()
            return version
        except (ValidationError, AssertionError) as err:
            validation_err = validation_err or err
        
        # Attempt 3: $ <bin_name> -v
        dash_v_out = self.exec(bin_name=abspath, cmd=["-v"], timeout=10, quiet=True).stdout.strip()
        try:
            version = SemVer.parse(dash_v_out)
            assert version, f"Could not parse version from $ {bin_name} -v: {dash_v_out}".strip()
            return version
        except (ValidationError, AssertionError) as err:
            validation_err = validation_err or err
        
        raise ValueError(
            f"Unable to find {bin_name} version from {bin_name} --version, -version or -v output\n{dash_dash_version_out or dash_version_out or dash_v_out}".strip()
        ) from validation_err

    def on_get_packages(self, bin_name: BinName, **context) -> InstallArgs:
        # print(f'[*] {self.__class__.__name__}: Getting install command for {bin_name}')
        # ... install command calculation logic here
        return TypeAdapter(InstallArgs).validate_python([bin_name])


    def on_install(self, bin_name: BinName, packages: Optional[InstallArgs]=None, **context) -> str:
        packages = packages or self.get_packages(bin_name)
        if not self.INSTALLER_BIN_ABSPATH:
            raise Exception(f'{self.name} install method is not available on this host ({self.INSTALLER_BIN} not found in $PATH)')

        # print(f'[*] {self.__class__.__name__}: Installing {bin_name}: {self.INSTALLER_BIN_ABSPATH} {packages}')

        # ... install logic here

        return f'Installed {bin_name} successfully (no-op)'

    @validate_call
    def get_abspaths(self, bin_name: BinName) -> List[HostBinPath]:
        return bin_abspaths(bin_name, PATH=self.PATH)

    @validate_call
    def get_sha256(self, bin_name: BinName, abspath: Optional[HostBinPath]=None, overrides: Optional[ProviderLookupDict]=None) -> Sha256 | None:
        """Get the sha256 hash of the binary at the given abspath (or equivalent hash of the underlying package)"""
        
        provider = self.get_provider_with_overrides(bin_name=bin_name, overrides=overrides)
        
        abspath = abspath or provider.get_abspath(bin_name)
        if not abspath or not os.access(abspath, os.R_OK):
            return None
        
        if sys.version_info >= (3, 11):
            with open(abspath, "rb", buffering=0) as f:
                return TypeAdapter(Sha256).validate_python(hashlib.file_digest(f, 'sha256').hexdigest())
        
        hash_sha256 = hashlib.sha256()
        with open(abspath, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_sha256.update(chunk)
        return TypeAdapter(Sha256).validate_python(hash_sha256.hexdigest())

    @validate_call
    def get_abspath(self, bin_name: BinName, overrides: Optional[ProviderLookupDict]=None, quiet: bool=True, timeout: int=5) -> HostBinPath | None:
        provider = self.get_provider_with_overrides(bin_name=bin_name, overrides=overrides)
        
        provider.setup_PATH()
        abspath = None
        try:
            abspath = provider.call_handler_for_action(
                bin_name=bin_name,
                handler_type='abspath',
                default_handler=self.on_get_abspath,
                timeout=timeout,
            )
        except Exception:
            if not quiet:
                raise
        if not abspath:
            return None
        result = TypeAdapter(HostBinPath).validate_python(abspath)
        self._abspath_cache[bin_name] = result
        return result

    @validate_call
    def get_version(self, bin_name: BinName, abspath: Optional[HostBinPath]=None, overrides: Optional[ProviderLookupDict]=None, quiet: bool=True, timeout: int=10) -> SemVer | None:
        provider = self.get_provider_with_overrides(bin_name=bin_name, overrides=overrides)
        
        version = None
        try:
            version = provider.call_handler_for_action(
                bin_name=bin_name,
                default_handler=self.on_get_version,
                handler_type='version',
                abspath=abspath,
                timeout=timeout,
            )
        except Exception:
            if not quiet:
                raise
        
        if not version:
            return None
        
        if not isinstance(version, SemVer):
            version = SemVer.parse(version)

        self._version_cache[bin_name] = version
        return version

    @validate_call
    def get_packages(self, bin_name: BinName, overrides: Optional[ProviderLookupDict]=None, quiet: bool=True, timeout: int=5) -> InstallArgs:
        provider = self.get_provider_with_overrides(bin_name=bin_name, overrides=overrides)
        
        packages = None
        try:
            packages = provider.call_handler_for_action(
                bin_name=bin_name,
                handler_type='packages',
                default_handler=self.on_get_packages,
                timeout=timeout,
            )
        except Exception:
            if not quiet:
                raise

        if not packages:
            packages = [bin_name]
        result = TypeAdapter(InstallArgs).validate_python(packages)
        return result

    def setup(self) -> None:
        """Override this to do any setup steps needed before installing packaged (e.g. create a venv, init an npm prefix, etc.)"""
        pass

    @validate_call
    def install(self, bin_name: BinName, overrides: Optional[ProviderLookupDict]=None, quiet: bool=False, timeout: int=120) -> ShallowBinary | None:
        provider = self.get_provider_with_overrides(bin_name=bin_name, overrides=overrides)
        
        provider.setup()
        
        packages = provider.get_packages(bin_name, quiet=quiet)
        
        provider.setup_PATH()
        install_log = None
        try:
            install_log = provider.call_handler_for_action(
                bin_name=bin_name,
                handler_type='install',
                default_handler=self.on_install,
                packages=packages,
                timeout=timeout,
            )
        except Exception as err:
            install_log = f'{self.__class__.__name__} Failed to install {bin_name}, got {err.__class__.__name__}: {err}'
            if not quiet:
                raise

        installed_abspath = provider.get_abspath(bin_name, quiet=quiet)
        if not quiet:
            assert installed_abspath, f'{provider.__class__.__name__} Unable to find abspath for {bin_name} after installing. PATH={provider.PATH} LOG={install_log}'

        installed_version = provider.get_version(bin_name, abspath=installed_abspath, quiet=quiet)
        if not quiet:
            assert installed_version, f'{provider.__class__.__name__} Unable to find version for {bin_name} after installing. ABSPATH={installed_abspath} LOG={install_log}'
        
        sha256 = provider.get_sha256(bin_name, abspath=installed_abspath)
        if not quiet:
            assert sha256, f'{provider.__class__.__name__} Unable to get sha256 of binary {bin_name} after installing. ABSPATH={installed_abspath} LOG={install_log}'
        
        result = ShallowBinary(
            name=bin_name,
            binprovider=provider,
            abspath=installed_abspath,
            version=installed_version,
            sha256=sha256 or 'unknown',
            binproviders=[provider],
        ) if (installed_abspath and installed_version) else None
        self._install_cache[bin_name] = result
        return result

    @validate_call
    def load(self, bin_name: BinName, overrides: Optional[ProviderLookupDict]=None, cache: bool=False, quiet: bool=True, timeout: int=10) -> ShallowBinary | None:
        provider = self.get_provider_with_overrides(bin_name=bin_name, overrides=overrides)
        
        installed_abspath = None
        installed_version = None

        if cache:
            installed_bin = self._install_cache.get(bin_name)
            if installed_bin:
                return installed_bin
            installed_abspath = self._abspath_cache.get(bin_name)
            installed_version = self._version_cache.get(bin_name)


        installed_abspath = installed_abspath or provider.get_abspath(bin_name, quiet=quiet, timeout=timeout)
        if not installed_abspath:
            return None

        installed_version = installed_version or provider.get_version(bin_name, abspath=installed_abspath, quiet=quiet, timeout=timeout)
        if not installed_version:
            return None
        
        sha256 = provider.get_sha256(bin_name, abspath=installed_abspath)
        if not sha256:
            # not ideal to store invalid sha256 but it's better than nothing
            sha256 = 'unknown'
        

        return ShallowBinary(
            name=bin_name,
            binprovider=provider,
            abspath=installed_abspath,
            version=installed_version,
            sha256=sha256,
            binproviders=[provider],
        )

    @validate_call
    def load_or_install(self, bin_name: BinName, overrides: Optional[ProviderLookupDict]=None, cache: bool=False, quiet: bool=False, timeout: int=120) -> ShallowBinary | None:
        provider = self.get_provider_with_overrides(bin_name=bin_name, overrides=overrides)
        
        installed = provider.load(bin_name=bin_name, cache=cache, quiet=True, timeout=15)
        if not installed:
            installed = provider.install(bin_name=bin_name, quiet=quiet, timeout=timeout)
        return installed



class EnvProvider(BinProvider):
    name: BinProviderName = 'env'
    INSTALLER_BIN: BinName = 'which'
    PATH: PATHStr = DEFAULT_ENV_PATH     # add dir containing python to $PATH

    abspath_handler: ProviderLookupDict = {
        **BinProvider.model_fields['abspath_handler'].default,
        'python': 'self.get_python_abspath',
    }
    version_handler: ProviderLookupDict = {
        **BinProvider.model_fields['version_handler'].default,
        'python': 'self.get_python_version',
    }

    @staticmethod
    def get_python_abspath():
        return Path(sys.executable)

    @staticmethod
    def get_python_version():
        return '{}.{}.{}'.format(*sys.version_info[:3])

    def on_install(self, bin_name: BinName, packages: Optional[InstallArgs]=None, **context) -> str:
        """The env BinProvider is ready-only and does not install any packages, so this is a no-op"""
        return ''
