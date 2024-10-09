#!/usr/bin/env python

__package__ = "pydantic_pkgr"

import os
import sys
import site
import shutil
import sysconfig
import tempfile

from pathlib import Path
from typing import Optional, List, Set

from pydantic import model_validator, TypeAdapter, computed_field

from .base_types import BinProviderName, PATHStr, BinName, InstallArgs, HostBinPath, bin_abspath, bin_abspaths
from .semver import SemVer
from .binprovider import BinProvider, DEFAULT_ENV_PATH


ACTIVE_VENV = os.getenv('VIRTUAL_ENV', None)
_CACHED_GLOBAL_PIP_BIN_DIRS: Set[str] | None = None

class PipProvider(BinProvider):
    name: BinProviderName = "pip"
    INSTALLER_BIN: BinName = "pip"
    
    PATH: PATHStr = ''
    
    pip_venv: Optional[Path] = None                                                         # None = system site-packages (user or global), otherwise it's a path e.g. DATA_DIR/lib/pip/venv
    cache_dir: Path = Path(tempfile.gettempdir()) / 'pydantic-pkgr' / 'pip'
    
    pip_install_args: List[str] = ["--no-input", "--disable-pip-version-check", "--quiet", f'--cache-dir={cache_dir}']  # extra args for pip install ... e.g. --upgrade

    @computed_field
    @property
    def is_valid(self) -> bool:
        """False if pip_venv is not created yet or if pip binary is not found in PATH"""
        if self.pip_venv:
            venv_pip_path = self.pip_venv / "bin" / "python"
            venv_pip_binary_exists = (os.path.isfile(venv_pip_path) and os.access(venv_pip_path, os.X_OK))
            if not venv_pip_binary_exists:
                return False
        
        return bool(self.INSTALLER_BIN_ABSPATH)

    @computed_field
    @property
    def INSTALLER_BIN_ABSPATH(self) -> HostBinPath | None:
        """Actual absolute path of the underlying package manager (e.g. /usr/local/bin/npm)"""
        abspath = None

        if self.pip_venv:
            assert self.INSTALLER_BIN != 'pipx', "Cannot use pipx with pip_venv"
            
            # use venv pip
            venv_pip_path = self.pip_venv / "bin" / self.INSTALLER_BIN
            if os.path.isfile(venv_pip_path) and os.access(venv_pip_path, os.R_OK) and os.access(venv_pip_path, os.X_OK):
                abspath = str(venv_pip_path)
        else:
            # use system pip
            relpath = bin_abspath(self.INSTALLER_BIN, PATH=DEFAULT_ENV_PATH) or shutil.which(self.INSTALLER_BIN)
            abspath = relpath and Path(relpath).resolve()  # find self.INSTALLER_BIN abspath using environment path
        
        if not abspath:
            # underlying package manager not found on this host, return None
            return None
        return TypeAdapter(HostBinPath).validate_python(abspath)

    @model_validator(mode='after')
    def detect_euid_to_use(self):
        """Detect the user (UID) to run as when executing pip (should be same as the user that owns the pip_venv dir)"""
        
        if self.euid is None:
            # try dropping to the owner of the npm prefix dir if it exists
            if self.pip_venv and os.path.isdir(self.pip_venv):
                self.euid = os.stat(self.pip_venv).st_uid

            # try dropping to the owner of the npm binary if it's not root
            installer_bin = self.INSTALLER_BIN_ABSPATH
            if installer_bin:
                self.euid = self.euid or os.stat(installer_bin).st_uid
                
            # fallback to the currently running user
            self.euid = self.euid or os.geteuid()
                    
        return self

    @model_validator(mode="after")
    def load_PATH_from_pip_sitepackages(self):
        global _CACHED_GLOBAL_PIP_BIN_DIRS
        PATH = self.PATH

        pip_bin_dirs = set()
        
        if self.pip_venv:
            # restrict PATH to only use venv bin path
            pip_bin_dirs = {str(self.pip_venv / "bin")}
            
        elif self.INSTALLER_BIN == "pipx":
            # restrict PATH to only use global pipx bin path
            if self.INSTALLER_BIN_ABSPATH and shutil.which(self.INSTALLER_BIN_ABSPATH):
                proc = self.exec(bin_name=self.INSTALLER_BIN_ABSPATH, cmd=["environment"], quiet=True, timeout=5)     # run $ pipx environment
                if proc.returncode == 0:
                    PIPX_BIN_DIR = proc.stdout.strip().split("PIPX_BIN_DIR=")[-1].split("\n", 1)[0]
                    pip_bin_dirs = {PIPX_BIN_DIR}
        else:
            # autodetect global system python paths
            
            if _CACHED_GLOBAL_PIP_BIN_DIRS:
                pip_bin_dirs = _CACHED_GLOBAL_PIP_BIN_DIRS.copy()
            else:
                pip_bin_dirs = {
                    * (
                        str(Path(sitepackage_dir).parent.parent.parent / "bin")               # /opt/homebrew/opt/python@3.11/Frameworks/Python.framework/Versions/3.11/bin
                        for sitepackage_dir in site.getsitepackages()
                    ),
                    str(Path(site.getusersitepackages()).parent.parent.parent / "bin"),       # /Users/squash/Library/Python/3.9/bin
                    sysconfig.get_path("scripts"),                                            # /opt/homebrew/bin
                    str(Path(sys.executable).resolve().parent),                               # /opt/homebrew/Cellar/python@3.11/3.11.9/Frameworks/Python.framework/Versions/3.11/bin
                }
                
                # find every python installed in the system PATH and add their parent path, as that's where its corresponding pip will link global bins
                for abspath in bin_abspaths("python", PATH=DEFAULT_ENV_PATH):                 # ~/Library/Frameworks/Python.framework/Versions/3.10/bin
                    pip_bin_dirs.add(str(abspath.parent))
                for abspath in bin_abspaths("python3", PATH=DEFAULT_ENV_PATH):                # /usr/local/bin or anywhere else we see python3 in $PATH
                    pip_bin_dirs.add(str(abspath.parent))
                
                _CACHED_GLOBAL_PIP_BIN_DIRS = pip_bin_dirs.copy()
            
            # remove any active venv from PATH because we're trying to only get the global system python paths
            if ACTIVE_VENV:
                pip_bin_dirs.remove(f"{ACTIVE_VENV}/bin")

        for bin_dir in pip_bin_dirs:
            if bin_dir not in PATH:
                PATH = ":".join([*PATH.split(":"), bin_dir])
        self.PATH = TypeAdapter(PATHStr).validate_python(PATH)
        return self
    
    def setup(self):
        """create pip venv dir if needed"""
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        try:
            os.system(f'chown {self.EUID} "{self.cache_dir}"')
            os.system(f'chmod 777 "{self.cache_dir}"')     # allow all users to share cache dir
        except Exception:
            pass
        
        if self.pip_venv:
            self.pip_venv.parent.mkdir(parents=True, exist_ok=True)
            
            # create new venv in pip_venv if it doesnt exist
            venv_pip_path = self.pip_venv / "bin" / "python"
            venv_pip_binary_exists = (os.path.isfile(venv_pip_path) and os.access(venv_pip_path, os.X_OK))
            if not venv_pip_binary_exists:
                import venv
                
                venv.create(
                    str(self.pip_venv),
                    system_site_packages=False,
                    clear=True,
                    symlinks=True,
                    with_pip=True,
                    upgrade_deps=True,
                )
                assert os.path.isfile(venv_pip_path) and os.access(venv_pip_path, os.X_OK), f'could not find pip inside venv after creating it: {self.pip_venv}'
                self.exec(bin_name=venv_pip_path, cmd=["install", "--cache-dir={self.cache_dir}", "--upgrade", "pip", "setuptools"])   # setuptools is not installed by default after python >= 3.12

    def on_install(self, bin_name: str, packages: Optional[InstallArgs] = None, **context) -> str:
        if self.pip_venv:
            self.setup()
        
        packages = packages or self.on_get_packages(bin_name)
        
        if not self.INSTALLER_BIN_ABSPATH:
            raise Exception(
                f"{self.__class__.__name__} install method is not available on this host ({self.INSTALLER_BIN} not found in $PATH)"
            )

        # print(f'[*] {self.__class__.__name__}: Installing {bin_name}: {self.INSTALLER_BIN_ABSPATH} install {packages}')


        proc = self.exec(bin_name=self.INSTALLER_BIN_ABSPATH, cmd=["install", *self.pip_install_args, *packages])

        if proc.returncode != 0:
            print(proc.stdout.strip())
            print(proc.stderr.strip())
            raise Exception(f"{self.__class__.__name__}: install got returncode {proc.returncode} while installing {packages}: {packages}")

        return proc.stderr.strip() + "\n" + proc.stdout.strip()

    def on_get_abspath(self, bin_name: BinName | HostBinPath, **context) -> HostBinPath | None:
        try:
            abspath = super().on_get_abspath(bin_name, **context)
            if abspath:
                return abspath
        except Exception:
            pass
        
        if not self.INSTALLER_BIN_ABSPATH:
            return None
        
        # fallback to using pip show to get the site-packages bin path
        packages = self.on_get_packages(str(bin_name)) or [str(bin_name)]
        output_lines = self.exec(bin_name=self.INSTALLER_BIN_ABSPATH, cmd=['show', *packages], timeout=5, quiet=True).stdout.strip().split('\n')
        try:
            location = [line for line in output_lines if line.startswith('Location: ')][0].split('Location: ', 1)[-1]
        except IndexError:
            return None
        PATH = str(Path(location).parent.parent.parent / 'bin')
        abspath = bin_abspath(str(bin_name), PATH=PATH)
        if abspath:
            return TypeAdapter(HostBinPath).validate_python(abspath)
        else:
            return None
    
    def on_get_version(self, bin_name: BinName, abspath: Optional[HostBinPath]=None, **context) -> SemVer | None:
        # print(f'[*] {self.__class__.__name__}: Getting version for {bin_name}...')
        try:
            version =  super().on_get_version(bin_name, abspath, **context)
            if version:
                return version
        except ValueError:
            pass
        
        if not self.INSTALLER_BIN_ABSPATH:
            return None
        
        # fallback to using pip show to get the version
        package = (self.on_get_packages(str(bin_name)) or [str(bin_name)])[-1]   # assume last package in list is the main one
        output_lines = self.exec(bin_name=self.INSTALLER_BIN_ABSPATH, cmd=['show', package], timeout=5, quiet=True).stdout.strip().split('\n')
        try:
            version_str = [line for line in output_lines if line.startswith('Version: ')][0].split('Version: ', 1)[-1]
            return SemVer.parse(version_str)
        except Exception:
            return None


if __name__ == "__main__":
    # Usage:
    # ./binprovider_pip.py load yt-dlp
    # ./binprovider_pip.py install pip
    # ./binprovider_pip.py get_version pip
    # ./binprovider_pip.py get_abspath pip
    result = pip = PipProvider()

    if len(sys.argv) > 1:
        result = func = getattr(pip, sys.argv[1])  # e.g. install

    if len(sys.argv) > 2:
        result = func(sys.argv[2])  # e.g. install ffmpeg

    print(result)
