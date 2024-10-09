#!/usr/bin/env python

import os
import sys
import shutil
import unittest
import subprocess




from pathlib import Path

from pydantic_pkgr import (
    BinProvider, EnvProvider, Binary, SemVer, ProviderLookupDict, bin_version,
    PipProvider, NpmProvider, AptProvider, BrewProvider,
)


class TestSemVer(unittest.TestCase):

    def test_parsing(self):
        self.assertEqual(SemVer(None), None)
        self.assertEqual(SemVer(''), None)
        self.assertEqual(SemVer.parse(''), None)
        self.assertEqual(SemVer(1), (1, 0, 0))
        self.assertEqual(SemVer(1, 2), (1, 2, 0))
        self.assertEqual(SemVer('1.2+234234'), (1, 2, 234234))
        self.assertEqual(SemVer('1.2+beta'), (1, 2, 0))
        self.assertEqual(SemVer('1.2.4(1)+beta'), (1, 2, 4))
        self.assertEqual(SemVer('1.2+beta(3)'), (1, 2, 3))
        self.assertEqual(SemVer('1.2+6-be1ta(4)'), (1, 2, 6))
        self.assertEqual(SemVer('1.2 curl(8)beta-4'), (1, 2, 0))
        self.assertEqual(SemVer('1.2+curl(8)beta-4'), (1, 2, 8))
        self.assertEqual(SemVer((1, 2, 3)), (1, 2, 3))
        self.assertEqual(getattr(SemVer((1, 2, 3)), 'full_text'), '1.2.3')
        self.assertEqual(SemVer(('1', '2', '3')), (1, 2, 3))
        self.assertEqual(SemVer.parse('5.6.7'), (5, 6, 7))
        self.assertEqual(SemVer.parse('124.0.6367.208'), (124, 0, 6367))
        self.assertEqual(SemVer.parse('Google Chrome 124.1+234.234'), (124, 1, 234))
        self.assertEqual(SemVer.parse('Google Ch1rome 124.0.6367.208'), (124, 0, 6367))
        self.assertEqual(SemVer.parse('Google Chrome 124.0.6367.208+beta_234. 234.234.123\n123.456.324'), (124, 0, 6367))
        self.assertEqual(getattr(SemVer.parse('Google Chrome 124.0.6367.208+beta_234. 234.234.123\n123.456.324'), 'full_text'), 'Google Chrome 124.0.6367.208+beta_234. 234.234.123')
        self.assertEqual(SemVer.parse('Google Chrome'), None)


class TestBinProvider(unittest.TestCase):

    def test_python_env(self):
        provider = EnvProvider()

        python_bin = provider.load('python')
        self.assertEqual(python_bin, provider.load_or_install('python'))

        self.assertEqual(python_bin.loaded_version, SemVer('{}.{}.{}'.format(*sys.version_info[:3])))
        self.assertEqual(python_bin.loaded_abspath, Path(sys.executable).absolute())
        self.assertEqual(python_bin.loaded_respath, Path(sys.executable).resolve())
        self.assertTrue(python_bin.is_valid)
        self.assertTrue(python_bin.is_executable)
        self.assertFalse(python_bin.is_script)
        self.assertTrue(bool(str(python_bin)))  # easy way to make sure serializing doesnt throw an error
        self.assertEqual(str(python_bin.loaded_binprovider.INSTALLER_BINARY.abspath), str(shutil.which('which')))


    def test_bash_env(self):
        envprovider = EnvProvider()

        SYS_BASH_VERSION = subprocess.check_output('bash --version', shell=True, text=True).split('\n')[0]

        bash_bin = envprovider.load_or_install('bash')
        self.assertEqual(bash_bin.loaded_version, SemVer(SYS_BASH_VERSION))
        self.assertGreater(bash_bin.loaded_version, SemVer('3.0.0'))
        self.assertEqual(bash_bin.loaded_abspath, Path(shutil.which('bash')))
        self.assertTrue(bash_bin.is_valid)
        self.assertTrue(bash_bin.is_executable)
        self.assertFalse(bash_bin.is_script)
        self.assertTrue(bool(str(bash_bin)))  # easy way to make sure serializing doesnt throw an error

    def test_overrides(self):
        
        class TestRecord:
            called_abspath_custom = False
            called_version_custom = False
            called_packages_custom = False
            called_install_custom = False


        class CustomProvider(BinProvider):
            name: str = 'CustomProvider'

            abspath_handler: ProviderLookupDict = {
                '*': 'self.on_abspath_custom'
            }
            version_handler: ProviderLookupDict = {
                '*': 'self.on_version_custom'
            }
            packages_handler: ProviderLookupDict = {
                '*': 'self.on_packages_custom'
            }
            install_handler: ProviderLookupDict = {
                '*': 'does.not.exist'
            }

            @staticmethod
            def on_abspath_custom():
                TestRecord.called_abspath_custom = True
                return Path(shutil.which('python'))

            def on_version_custom(self, bin_name: str, **context):
                TestRecord.called_version_custom = True
                return bin_version(self.get_abspath(bin_name))

            @classmethod
            def on_packages_custom(self, bin_name: str, **context):
                TestRecord.called_packages_custom = True

            def on_install(self, bin_name: str, **context):
                raise NotImplementedError('whattt')

            def on_install_somebin(self, bin_name: str, **context):
                TestRecord.called_install_custom = True

        provider = CustomProvider(install_handler={'somebin': 'self.on_install_somebin'})

        self.assertFalse(TestRecord.called_abspath_custom)
        self.assertFalse(TestRecord.called_version_custom)
        self.assertFalse(TestRecord.called_packages_custom)
        self.assertFalse(TestRecord.called_install_custom)

        provider.get_abspath('doesnotexist')
        self.assertTrue(TestRecord.called_abspath_custom)

        provider.get_version('doesnotexist')
        self.assertTrue(TestRecord.called_version_custom)

        provider.get_packages('doesnotexist')
        self.assertTrue(TestRecord.called_packages_custom)

        exc = None
        try:
            provider.install('doesnotexist')
        except Exception as err:
            exc = err
        self.assertIsInstance(exc, NotImplementedError)
        self.assertFalse(TestRecord.called_install_custom)

        provider.install('somebin')
        self.assertTrue(TestRecord.called_install_custom)


class TestBinary(unittest.TestCase):

    def test_python_bin(self):
        envprovider = EnvProvider()

        python_bin = Binary(name='python', binproviders=[envprovider])

        self.assertIsNone(python_bin.loaded_binprovider)
        self.assertIsNone(python_bin.loaded_abspath)
        self.assertIsNone(python_bin.loaded_version)

        python_bin = python_bin.load()

        shallow_bin = envprovider.load_or_install('python')
        assert shallow_bin and python_bin.loaded_binprovider
        self.assertEqual(python_bin.loaded_binprovider, shallow_bin.loaded_binprovider)
        self.assertEqual(python_bin.loaded_abspath, shallow_bin.loaded_abspath)
        self.assertEqual(python_bin.loaded_version, shallow_bin.loaded_version)
        self.assertEqual(python_bin.loaded_sha256, shallow_bin.loaded_sha256)

        self.assertEqual(python_bin.loaded_version, SemVer('{}.{}.{}'.format(*sys.version_info[:3])))
        self.assertEqual(python_bin.loaded_abspath, Path(sys.executable).absolute())
        self.assertEqual(python_bin.loaded_respath, Path(sys.executable).resolve())
        self.assertTrue(python_bin.is_valid)
        self.assertTrue(python_bin.is_executable)
        self.assertFalse(python_bin.is_script)
        self.assertTrue(bool(str(python_bin)))  # easy way to make sure serializing doesnt throw an error


def flatten(xss):
    return [x for xs in xss for x in xs]

class InstallTest(unittest.TestCase):

    def install_with_binprovider(self, provider, binary):

        binary_bin = binary.load_or_install()
        provider_bin = provider.load_or_install(bin_name=binary.name)
        # print(binary_bin, binary_bin.bin_dir, binary_bin.loaded_abspath)
        # print('\n'.join(f'{provider}={path}' for provider, path in binary.loaded_abspaths.items()), '\n')
        # print()

        self.assertEqual(binary_bin.loaded_binprovider, provider_bin.loaded_binprovider)
        self.assertEqual(binary_bin.loaded_abspath, provider_bin.loaded_abspath)
        self.assertEqual(binary_bin.loaded_version, provider_bin.loaded_version)
        self.assertEqual(binary_bin.loaded_sha256, provider_bin.loaded_sha256)

        self.assertIn(binary_bin.loaded_abspath, flatten(binary_bin.loaded_abspaths.values()))
        self.assertIn(str(binary_bin.bin_dir), flatten(PATH.split(':') for PATH in binary_bin.loaded_bin_dirs.values()))

        PATH = provider.PATH
        bin_abspath = shutil.which(binary.name, path=PATH)
        assert bin_abspath, f'Could not find {binary.name} in PATH={PATH}'
        VERSION = SemVer.parse(subprocess.check_output(f'{bin_abspath} --version', shell=True, text=True))
        ABSPATH = Path(bin_abspath).absolute().resolve()

        self.assertEqual(binary_bin.loaded_version, VERSION)
        self.assertIn(binary_bin.loaded_abspath, provider.get_abspaths(binary_bin.name))
        self.assertEqual(binary_bin.loaded_respath, ABSPATH)
        self.assertTrue(binary_bin.is_valid)
        self.assertTrue(binary_bin.is_executable)
        self.assertFalse(binary_bin.is_script)
        self.assertTrue(bool(str(binary_bin)))  # easy way to make sure serializing doesnt throw an error
        # print(provider.PATH)
        # print()
        # print()
        # print(binary.bin_filename, binary.bin_dir, binary.loaded_abspaths)
        # print()
        # print()
        # print(provider.name, 'PATH=', provider.PATH, 'ABSPATHS=', provider.get_abspaths(bin_name=binary_bin.name))
        return provider_bin

    def test_env_provider(self):
        provider = EnvProvider()
        binary = Binary(name='wget', binproviders=[provider]).load()
        self.install_with_binprovider(provider, binary)

    def test_pip_provider(self):
        # pipprovider = PipProvider()
        pipprovider = PipProvider(pip_venv=os.environ.get('VIRTUAL_ENV', None))
        # print(provider.PATH)
        binary = Binary(name='yt-dlp', binproviders=[pipprovider])
        self.install_with_binprovider(pipprovider, binary)

    def test_npm_provider(self):
        npmprovider = NpmProvider()
        # print(provider.PATH)
        binary = Binary(name='tsx', binproviders=[npmprovider])
        self.install_with_binprovider(npmprovider, binary)

    def test_brew_provider(self):
        # print(provider.PATH)
        os.environ['HOMEBREW_NO_AUTO_UPDATE'] = 'True'
        os.environ['HOMEBREW_NO_INSTALL_CLEANUP'] = 'True'
        os.environ['HOMEBREW_NO_ENV_HINTS'] = 'True'

        is_on_windows = sys.platform.startswith('win') or os.name == 'nt'
        is_on_macos = 'darwin' in sys.platform
        is_on_linux = 'linux' in sys.platform
        has_brew = shutil.which('brew') is not None
        # has_apt = shutil.which('dpkg') is not None
        
        provider = BrewProvider()
        if has_brew:
            self.assertTrue(provider.PATH)
        else:
            self.assertFalse(provider.PATH)

        exception = None
        result = None
        try:
            binary = Binary(name='wget', binproviders=[provider])
            result = self.install_with_binprovider(provider, binary)
        except Exception as err:
            exception = err


        if is_on_macos or (is_on_linux and has_brew):
            self.assertTrue(has_brew)
            if exception:
                raise exception
            self.assertIsNone(exception)
            self.assertTrue(result)
        elif is_on_windows or (is_on_linux and not has_brew):
            self.assertFalse(has_brew)
            self.assertIsInstance(exception, Exception)
            self.assertFalse(result)
        else:
            raise exception


    def test_apt_provider(self):
        is_on_windows = sys.platform.startswith('win') or os.name == 'nt'
        is_on_macos = 'darwin' in sys.platform
        is_on_linux = 'linux' in sys.platform
        # has_brew = shutil.which('brew') is not None
        has_apt = shutil.which('apt-get') is not None


        exception = None
        result = None
        provider = AptProvider()
        if has_apt:
            self.assertTrue(provider.PATH)
        else:
            self.assertFalse(provider.PATH)
        try:
            # print(provider.PATH)
            binary = Binary(name='wget', binproviders=[provider])
            result = self.install_with_binprovider(provider, binary)
        except Exception as err:
            exception = err


        if is_on_linux:
            self.assertTrue(has_apt)
            if exception:
                raise exception
            self.assertIsNone(exception)
            self.assertTrue(result)
        elif is_on_windows or is_on_macos:
            self.assertFalse(has_apt)
            self.assertIsInstance(exception, Exception)
            self.assertFalse(result)
        else:
            raise exception


if __name__ == '__main__':
    unittest.main()
