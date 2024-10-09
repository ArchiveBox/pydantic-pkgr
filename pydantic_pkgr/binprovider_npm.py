
#!/usr/bin/env python

__package__ = "pydantic_pkgr"

import os
import sys
import tempfile
from pathlib import Path
from typing import Optional, List

from pydantic import model_validator, TypeAdapter, computed_field

from .base_types import BinProviderName, PATHStr, BinName, InstallArgs, HostBinPath, bin_abspath
from .semver import SemVer
from .binprovider import BinProvider

# Cache these values globally because they never change at runtime
_CACHED_GLOBAL_NPM_PREFIX: str | None = None
_CACHED_LOCAL_NPM_PREFIX: str | None = None
_CACHED_HOME_DIR: Path = Path('~').expanduser().absolute()


class NpmProvider(BinProvider):
    name: BinProviderName = 'npm'
    INSTALLER_BIN: BinName = 'npm'

    PATH: PATHStr = ''
    
    npm_prefix: Optional[Path] = None                           # None = -g global, otherwise it's a path
    cache_dir: Path = Path(tempfile.gettempdir()) / 'pydantic-pkgr' / 'npm'
    
    npm_install_args: List[str] = ['--force', '--no-audit', '--no-fund', '--loglevel=error', f'--cache={cache_dir}']


    @computed_field
    @property
    def is_valid(self) -> bool:
        """False if npm_prefix is not created yet or if npm binary is not found in PATH"""
        if self.npm_prefix:
            npm_bin_dir = self.npm_prefix / 'node_modules' / '.bin'
            npm_bin_dir_exists = (os.path.isdir(npm_bin_dir) and os.access(npm_bin_dir, os.R_OK))
            if not npm_bin_dir_exists:
                return False
        
        return bool(self.INSTALLER_BIN_ABSPATH)
    
    @model_validator(mode='after')
    def detect_euid_to_use(self):
        """Detect the user (UID) to run as when executing npm (should be same as the user that owns the npm_prefix dir)"""
        if self.euid is None:
            # try dropping to the owner of the npm prefix dir if it exists
            if self.npm_prefix and os.path.isdir(self.npm_prefix):
                self.euid = os.stat(self.npm_prefix).st_uid

            # try dropping to the owner of the npm binary if it's not root
            installer_bin = self.INSTALLER_BIN_ABSPATH
            if installer_bin:
                self.euid = self.euid or os.stat(installer_bin).st_uid
                
            # fallback to the currently running user
            self.euid = self.euid or os.geteuid()
                    
        return self

    @model_validator(mode='after')
    def load_PATH_from_npm_prefix(self):
        global _CACHED_GLOBAL_NPM_PREFIX
        global _CACHED_LOCAL_NPM_PREFIX
        
        if not self.INSTALLER_BIN_ABSPATH:
            return TypeAdapter(PATHStr).validate_python('')
        
        PATH = self.PATH
        npm_bin_dirs = set()
        
        if self.npm_prefix:
            # restrict PATH to only use npm prefix
            npm_bin_dirs = {str(self.npm_prefix / 'node_modules/.bin')}
        else:
            # find all local and global npm PATHs
            npm_local_dir = _CACHED_LOCAL_NPM_PREFIX or self.exec(bin_name=self.INSTALLER_BIN_ABSPATH, cmd=['prefix'], quiet=True).stdout.strip()
            _CACHED_LOCAL_NPM_PREFIX = npm_local_dir

            # start at npm_local_dir and walk up to $HOME (or /), finding all npm bin dirs along the way
            search_dir = Path(npm_local_dir)
            stop_if_reached = [str(Path('/')), str(_CACHED_HOME_DIR)]
            num_hops, max_hops = 0, 6
            while num_hops < max_hops and str(search_dir) not in stop_if_reached:
                try:
                    npm_bin_dirs.add(list(search_dir.glob('node_modules/.bin'))[0])
                    break
                except (IndexError, OSError, Exception):
                    # could happen becuase we dont have permission to access the parent dir, or it's been moved, or many other weird edge cases...
                    pass
                search_dir = search_dir.parent
                num_hops += 1
            
            npm_global_dir = _CACHED_GLOBAL_NPM_PREFIX or self.exec(bin_name=self.INSTALLER_BIN_ABSPATH, cmd=['prefix', '-g'], quiet=True).stdout.strip() + '/bin'    # /opt/homebrew/bin
            _CACHED_GLOBAL_NPM_PREFIX = npm_global_dir
            npm_bin_dirs.add(npm_global_dir)
        
        for bin_dir in npm_bin_dirs:
            if str(bin_dir) not in PATH:
                PATH = ':'.join([*PATH.split(':'), str(bin_dir)])
        self.PATH = TypeAdapter(PATHStr).validate_python(PATH)
        return self

    def setup(self) -> None:
        """create npm install prefix and node_modules_dir if needed"""
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        try:
            os.system(f'chown {self.EUID} "{self.cache_dir}"')
            os.system(f'chmod 777 "{self.cache_dir}"')     # allow all users to share cache dir
        except Exception:
            pass
        
        if self.npm_prefix:
            (self.npm_prefix / 'node_modules/.bin').mkdir(parents=True, exist_ok=True)

    def on_install(self, bin_name: str, packages: Optional[InstallArgs]=None, **context) -> str:
        self.setup()
        
        packages = packages or self.on_get_packages(bin_name)
        if not self.INSTALLER_BIN_ABSPATH:
            raise Exception(f'{self.__class__.__name__} install method is not available on this host ({self.INSTALLER_BIN} not found in $PATH)')
        
        # print(f'[*] {self.__class__.__name__}: Installing {bin_name}: {self.INSTALLER_BIN_ABSPATH} install {packages}')
        
        install_args = [*self.npm_install_args]
        if self.npm_prefix:
            install_args.append(f'--prefix={self.npm_prefix}')
        else:
            install_args.append('--global')
        
        proc = self.exec(bin_name=self.INSTALLER_BIN_ABSPATH, cmd=["install", *install_args, *packages])
        
        if proc.returncode != 0:
            print(proc.stdout.strip())
            print(proc.stderr.strip())
            raise Exception(f'{self.__class__.__name__}: install got returncode {proc.returncode} while installing {packages}: {packages}')
        
        return proc.stderr.strip() + '\n' + proc.stdout.strip()
    
    def on_get_abspath(self, bin_name: BinName | HostBinPath, **context) -> HostBinPath | None:
        # print(self.__class__.__name__, 'on_get_abspath', bin_name)
        try:
            abspath = super().on_get_abspath(bin_name, **context)
            if abspath:
                return abspath
        except Exception:
            pass
        
        if not self.INSTALLER_BIN_ABSPATH:
            return None
        
        # fallback to using npm show to get alternate binary names based on the package
        try:
            package = (self.get_packages(str(bin_name)) or [str(bin_name)])[-1]  # assume last package in list is the main one
            output_lines = self.exec(bin_name=self.INSTALLER_BIN_ABSPATH, cmd=['show', package], timeout=5, quiet=True).stdout.strip().split('\n')
            bin_name = [line for line in output_lines if line.startswith('bin: ')][0].split('bin: ', 1)[-1].split(', ')[0]
            abspath = bin_abspath(bin_name, PATH=self.PATH)
            if abspath:
                return TypeAdapter(HostBinPath).validate_python(abspath)
        except Exception:
            pass        
        return None
    
    def on_get_version(self, bin_name: BinName, abspath: Optional[HostBinPath]=None, **context) -> SemVer | None:
        # print(f'[*] {self.__class__.__name__}: Getting version for {bin_name}...')
        try:
            version = super().on_get_version(bin_name, abspath, **context)
            if version:
                return version
        except ValueError:
            pass
        
        if not self.INSTALLER_BIN_ABSPATH:
            return None
        
        # fallback to using npm list to get the installed package version
        try:
            package = (self.get_packages(str(bin_name), **context) or [str(bin_name)])[-1]  # assume last package in list is the main one
            
            # remove the package version if it exists "@postslight/parser@^1.2.3" -> "@postlight/parser"
            if package[0] == '@':
                package = '@' + package[1:].split('@', 1)[0]
            else:
                package = package.split('@', 1)[0]
                
            # npm list --depth=0 "@postlight/parser"
            # (dont use 'npm info @postlight/parser version', it shows *any* availabe version, not installed version)
            output_line = self.exec(bin_name=self.INSTALLER_BIN_ABSPATH, cmd=[
                'list',
                f'--prefix={self.npm_prefix}' if self.npm_prefix else '--global',
                '--depth=0',
                package,
            ], timeout=5, quiet=True).stdout.strip()
            # /opt/homebrew/lib
            # └── @postlight/parser@2.2.3
            version_str = output_line.rsplit('@', 1)[-1].strip()
            return SemVer.parse(version_str)
        except Exception:
            pass
        return None

if __name__ == "__main__":
    # Usage:
    # ./binprovider_npm.py load @postlight/parser
    # ./binprovider_npm.py install @postlight/parser
    # ./binprovider_npm.py get_version @postlight/parser
    # ./binprovider_npm.py get_abspath @postlight/parser
    result = npm = NpmProvider()

    if len(sys.argv) > 1:
        result = func = getattr(npm, sys.argv[1])  # e.g. install

    if len(sys.argv) > 2:
        result = func(sys.argv[2])  # e.g. install ffmpeg

    print(result)
