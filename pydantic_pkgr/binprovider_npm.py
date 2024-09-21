
#!/usr/bin/env python
__package__ = "pydantic_pkgr"

import sys
from pathlib import Path
from typing import Optional, List

from pydantic import model_validator, TypeAdapter

from .base_types import BinProviderName, PATHStr, BinName, InstallArgs
from .binprovider import BinProvider


class NpmProvider(BinProvider):
    name: BinProviderName = 'npm'
    INSTALLER_BIN: BinName = 'npm'

    PATH: PATHStr = ''
    
    npm_install_prefix: Optional[Path] = None        # None = -g global, otherwise it's a path
    npm_install_args: List[str] = ['--force', '--no-save', '--no-audit', '--no-fund', '--loglevel=error']

    @model_validator(mode='after')
    def load_PATH_from_npm_prefix(self):
        if not self.INSTALLER_BIN_ABSPATH:
            return TypeAdapter(PATHStr).validate_python('')
        
        PATH = self.PATH
        npm_bin_dirs = set()
        
        if self.npm_install_prefix:
            npm_bin_dirs.add(self.npm_install_prefix / 'node_modules/.bin')

        search_dir = Path(self.exec(bin_name=self.INSTALLER_BIN_ABSPATH, cmd=['prefix']).stdout.strip())
        stop_if_reached = [str(Path('/')), str(Path('~').expanduser().absolute())]
        num_hops, max_hops = 0, 6
        while num_hops < max_hops and str(search_dir) not in stop_if_reached:
            try:
                npm_bin_dirs.add(list(search_dir.glob('node_modules/.bin'))[0])
                break
            except (IndexError, OSError, Exception):
                pass
            search_dir = search_dir.parent
            num_hops += 1
        
        npm_global_dir = self.exec(bin_name=self.INSTALLER_BIN_ABSPATH, cmd=['prefix', '-g']).stdout.strip() + '/bin'    # /opt/homebrew/bin
        npm_bin_dirs.add(npm_global_dir)
        
        for bin_dir in npm_bin_dirs:
            if str(bin_dir) not in PATH:
                PATH = ':'.join([*PATH.split(':'), str(bin_dir)])
        self.PATH = TypeAdapter(PATHStr).validate_python(PATH)
        return self

    def on_install(self, bin_name: str, packages: Optional[InstallArgs]=None, **context) -> str:
        packages = packages or self.on_get_packages(bin_name)
        if not self.INSTALLER_BIN_ABSPATH:
            raise Exception(f'{self.__class__.__name__} install method is not available on this host ({self.INSTALLER_BIN} not found in $PATH)')
        
        # print(f'[*] {self.__class__.__name__}: Installing {bin_name}: {self.INSTALLER_BIN_ABSPATH} install {packages}')
        
        install_args = [*self.npm_install_args]
        if self.npm_install_prefix:
            install_args.append(f'--prefix={self.npm_install_prefix}')
        else:
            install_args.append('--global')
        
        proc = self.exec(bin_name=self.INSTALLER_BIN_ABSPATH, cmd=["install", *install_args, *packages])
        
        if proc.returncode != 0:
            print(proc.stdout.strip())
            print(proc.stderr.strip())
            raise Exception(f'{self.__class__.__name__}: install got returncode {proc.returncode} while installing {packages}: {packages}')
        
        return proc.stderr.strip() + '\n' + proc.stdout.strip()
    
    # def on_get_abspath(self, bin_name: BinName | HostBinPath, **context) -> HostBinPath | None:
    #     packages = self.on_get_packages(str(bin_name))
    #     if not self.INSTALLER_BIN_ABSPATH:
    #         raise Exception(f'{self.__class__.__name__} install method is not available on this host ({self.INSTALLER_BIN} not found in $PATH)')
        
    #     proc = self.exec(bin_name=self.INSTALLER_BIN_ABSPATH, cmd=['ls', *packages])
        
    #     if proc.returncode != 0:
    #         print(proc.stdout.strip())
    #         print(proc.stderr.strip())
    #         raise Exception(f'{self.__class__.__name__}: got returncode {proc.returncode} while getting {bin_name} abspath')
        
    #     PATH = proc.stdout.strip().split('\n', 1)[0].split(' ', 1)[-1] + '/node_modules/.bin'
    #     abspath = shutil.which(str(bin_name), path=PATH)
    #     if abspath:
    #         return TypeAdapter(HostBinPath).validate_python(abspath)
    #     else:
    #         return None

if __name__ == "__main__":
    result = npm = NpmProvider()

    if len(sys.argv) > 1:
        result = func = getattr(npm, sys.argv[1])  # e.g. install

    if len(sys.argv) > 2:
        result = func(sys.argv[2])  # e.g. install ffmpeg

    print(result)
