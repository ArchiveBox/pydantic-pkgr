
#!/usr/bin/env python
__package__ = "pydantic_pkgr"

import sys
import platform
from pathlib import Path
from typing import Optional

from pydantic import model_validator, TypeAdapter

from .base_types import BinProviderName, PATHStr, BinName, InstallArgs
from .binprovider import BinProvider


class BrewProvider(BinProvider):
    name: BinProviderName = "brew"
    INSTALLER_BIN: BinName = "brew"
    
    PATH: PATHStr = "/home/linuxbrew/.linuxbrew/bin:/opt/homebrew/bin:/usr/local/bin"

    @model_validator(mode="after")
    def load_PATH(self):
        if not self.INSTALLER_BIN_ABSPATH:
            # brew is not availabe on this host
            self.PATH: PATHStr = ""
            return self

        OS = platform.system().lower()
        DEFAULT_MACOS_DIR = Path('/opt/homebrew/bin') if platform.machine() == 'arm64' else Path('/usr/local/bin')
        DEFAULT_LINUX_DIR = Path('/home/linuxbrew/.linuxbrew/bin')
        
        PATHs = set()
        
        if OS == 'darwin' and DEFAULT_MACOS_DIR.exists():
            PATHs.add(str(DEFAULT_MACOS_DIR))
        if OS != 'darwin' and DEFAULT_LINUX_DIR.exists():
            PATHs.add(str(DEFAULT_LINUX_DIR))
        
        if not PATHs:
            # if we cant autodetect the paths, run brew --prefix to get the path manually (very slow)
            PATHs.add(self.exec(bin_name=self.INSTALLER_BIN_ABSPATH, cmd=["--prefix"]).stdout.strip() + "/bin")
        
        self.PATH = TypeAdapter(PATHStr).validate_python(':'.join(PATHs))
        return self

    def on_install(self, bin_name: str, packages: Optional[InstallArgs] = None, **context) -> str:
        packages = packages or self.on_get_packages(bin_name)

        if not self.INSTALLER_BIN_ABSPATH:
            raise Exception(f"{self.__class__.__name__}.INSTALLER_BIN is not available on this host: {self.INSTALLER_BIN}")

        # print(f'[*] {self.__class__.__name__}: Installing {bin_name}: {self.INSTALLER_BIN_ABSPATH} install {packages}')

        # Attempt 1: Try installing with Pyinfra
        from .binprovider_pyinfra import PYINFRA_INSTALLED, pyinfra_package_install

        if PYINFRA_INSTALLED:
            return pyinfra_package_install(bin_name, installer_module="operations.brew.packages")

        # Attempt 2: Try installing with Ansible
        from .binprovider_ansible import ANSIBLE_INSTALLED, ansible_package_install

        if ANSIBLE_INSTALLED:
            return ansible_package_install(bin_name, installer_module="community.general.homebrew")

        # Attempt 3: Fallback to installing manually by calling brew in shell
        self.exec(bin_name=self.INSTALLER_BIN_ABSPATH, cmd=["update"])
        proc = self.exec(bin_name=self.INSTALLER_BIN_ABSPATH, cmd=["install", *packages])
        if proc.returncode != 0:
            print(proc.stdout.strip())
            print(proc.stderr.strip())
            raise Exception(f"{self.__class__.__name__} install got returncode {proc.returncode} while installing {packages}: {packages}")

        return proc.stderr.strip() + "\n" + proc.stdout.strip()

    # def on_get_version(self, bin_name: BinName, abspath: Optional[HostBinPath]=None, **context) -> SemVer | None:
    #     # print(f'[*] {self.__class__.__name__}: Getting version for {bin_name}...')
    #     version_stdout_str = run(['brew', 'info', '--quiet', bin_name], stdout=PIPE, stderr=PIPE, text=True).stdout
    #     try:
    #         return SemVer.parse(version_stdout_str)
    #     except ValidationError:
    #         raise
    #         return None

if __name__ == "__main__":
    result = brew = BrewProvider()

    if len(sys.argv) > 1:
        result = func = getattr(brew, sys.argv[1])  # e.g. install

    if len(sys.argv) > 2:
        result = func(sys.argv[2])  # e.g. install ffmpeg

    print(result)
