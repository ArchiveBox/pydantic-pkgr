__package__ = "pydantic_pkgr"

import site
import shutil
import sysconfig
from pathlib import Path
from typing import Optional

from pydantic import model_validator, TypeAdapter

from .base_types import BinProviderName, PATHStr, BinName, InstallArgs
from .binprovider import BinProvider


class PipProvider(BinProvider):
    name: BinProviderName = "pip"
    INSTALLER_BIN: BinName = "pip"
    PATH: PATHStr = sysconfig.get_path("scripts")  # /opt/homebrew/bin

    @model_validator(mode="after")
    def load_PATH_from_pip_sitepackages(self):
        PATH = self.PATH

        paths = {
            *(
                str(Path(d).parent.parent.parent / "bin") for d in site.getsitepackages()
            ),  # /opt/homebrew/opt/python@3.11/Frameworks/Python.framework/Versions/3.11/bin
            str(Path(site.getusersitepackages()).parent.parent.parent / "bin"),  # /Users/squash/Library/Python/3.9/bin
            sysconfig.get_path("scripts"),  # /opt/homebrew/bin
        }

        if self.INSTALLER_BIN_ABSPATH and shutil.which(self.INSTALLER_BIN_ABSPATH):
            proc = self.exec(bin_name=self.INSTALLER_BIN_ABSPATH, cmd=["environment"])
            if proc.returncode == 0:
                PIPX_BIN_DIR = proc.stdout.strip().split("PIPX_BIN_DIR=")[-1].split("\n", 1)[0]
                paths.add(PIPX_BIN_DIR)

        for bin_dir in paths:
            if bin_dir not in PATH:
                PATH = ":".join([*PATH.split(":"), bin_dir])
        self.PATH = TypeAdapter(PATHStr).validate_python(PATH)
        return self

    def on_install(self, bin_name: str, packages: Optional[InstallArgs] = None, **context) -> str:
        packages = packages or self.on_get_packages(bin_name)
        if not self.INSTALLER_BIN_ABSPATH:
            raise Exception(
                f"{self.__class__.__name__} install method is not available on this host ({self.INSTALLER_BIN} not found in $PATH)"
            )

        # print(f'[*] {self.__class__.__name__}: Installing {bin_name}: {self.INSTALLER_BIN_ABSPATH} install {packages}')

        proc = self.exec(bin_name=self.INSTALLER_BIN_ABSPATH, cmd=["install", *packages])

        if proc.returncode != 0:
            print(proc.stdout.strip())
            print(proc.stderr.strip())
            raise Exception(f"{self.__class__.__name__}: install got returncode {proc.returncode} while installing {packages}: {packages}")

        return proc.stderr.strip() + "\n" + proc.stdout.strip()

    # def on_get_abspath(self, bin_name: BinName | HostBinPath, **context) -> HostBinPath | None:
    #     packages = self.on_get_packages(str(bin_name))
    #     if not self.INSTALLER_BIN_ABSPATH:
    #         raise Exception(f'{self.__class__.__name__} install method is not available on this host ({self.INSTALLER_BIN} not found in $PATH)')

    #     proc = self.exec(bin_name=self.INSTALLER_BIN_ABSPATH, cmd=['show', *packages])

    #     if proc.returncode != 0:
    #         print(proc.stdout.strip())
    #         print(proc.stderr.strip())
    #         raise Exception(f'{self.__class__.__name__}: got returncode {proc.returncode} while getting {bin_name} abspath')

    #     output_lines = proc.stdout.strip().split('\n')
    #     location = [line for line in output_lines if line.startswith('Location: ')][0].split(': ', 1)[-1]
    #     PATH = str(Path(location).parent.parent.parent / 'bin')
    #     abspath = shutil.which(str(bin_name), path=PATH)
    #     if abspath:
    #         return TypeAdapter(HostBinPath).validate_python(abspath)
    #     else:
    #         return None
