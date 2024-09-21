__package__ = 'pydantic_pkgr'

import os
import sys

from typing import Optional, Dict, Any

from pydantic import model_validator, TypeAdapter
from .binprovider import BinProvider, BinProviderName, PATHStr, BinName, InstallArgs, OPERATING_SYSTEM
# from .semver import SemVer

PYINFRA_INSTALLED = False
PYINFRA_IMPORT_ERROR = None
try:
    # from pyinfra import host
    from pyinfra import operations
    from pyinfra.api import Config, Inventory, State
    from pyinfra.api.connect import connect_all
    from pyinfra.api.operation import add_op
    from pyinfra.api.operations import run_ops
    from pyinfra.api.exceptions import PyinfraError

    PYINFRA_INSTALLED = True
except ImportError as err:
    PYINFRA_IMPORT_ERROR = err
    pass


def pyinfra_package_install(pkg_names: str, installer_module: str = "auto", installer_extra_kwargs: Optional[Dict[str, Any]] = None) -> str:
    if not PYINFRA_INSTALLED:
        raise RuntimeError("Pyinfra is not installed! To fix:\n    pip install pyinfra") from PYINFRA_IMPORT_ERROR

    config = Config()
    inventory = Inventory((["@local"], {}))
    state = State(inventory=inventory, config=config)

    connect_all(state)
    
    if installer_module == 'auto':
        is_macos = OPERATING_SYSTEM == "darwin"
        if is_macos:
            installer_module = operations.brew.packages
        else:
            installer_module = operations.server.packages
    else:
        assert installer_module.startswith('operations.')
        installer_module = eval(installer_module)
    
    result = add_op(
        state,
        installer_module,
        name=f"Install system packages: {pkg_names}",
        packages=pkg_names,
        **(installer_extra_kwargs or {}),
    )

    succeeded = False
    try:
        run_ops(state)
        succeeded = True
    except PyinfraError:
        pass
        
    result = result[state.inventory.hosts["@local"]]
    result_text = f'Installing {pkg_names} on {OPERATING_SYSTEM} using Pyinfra {installer_module} {["failed", "succeeded"][succeeded]}:\n{result.stdout}\n{result.stderr}'
    
    if succeeded:
        return result_text

    if "Permission denied" in result_text:
        raise PermissionError(
            f"Installing {pkg_names} failed! Need to be root to use package manager (retry with sudo, or install manually)"
        )
    raise Exception(f"Installing {pkg_names} failed! (retry with sudo, or install manually)\n{result_text}")
        


class PyinfraProvider(BinProvider):
    name: BinProviderName = "pyinfra"
    INSTALLER_BIN: BinName = "pyinfra"
    PATH: PATHStr = os.environ.get("PATH", "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin")

    pyinfra_installer_module: str = 'auto'   # e.g. operations.apt.packages, operations.server.packages, etc.
    pyinfra_installer_kwargs: Dict[str, Any] = {}

    @model_validator(mode="after")
    def load_PATH(self):
        if not self.INSTALLER_BIN_ABSPATH:
            # brew is not availabe on this host
            self.PATH: PATHStr = ""
            return self

        PATH = self.PATH
        brew_bin_dir = self.exec(bin_name=self.INSTALLER_BIN_ABSPATH, cmd=["--prefix"]).stdout.strip() + "/bin"
        if brew_bin_dir not in PATH:
            PATH = ":".join([brew_bin_dir, *PATH.split(":")])
        self.PATH = TypeAdapter(PATHStr).validate_python(PATH)
        return self

    def on_install(self, bin_name: str, packages: Optional[InstallArgs] = None, **context) -> str:
        packages = packages or self.on_get_packages(bin_name)

        return pyinfra_package_install(
            pkg_names=packages,
            installer_module=self.pyinfra_installer_module,
            installer_extra_kwargs=self.pyinfra_installer_kwargs,
        )

if __name__ == "__main__":
    ansible = PyinfraProvider()
    binary = ansible.install(sys.args[1])
    print(binary.abspath, binary.version)
