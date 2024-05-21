import sys
import shutil
import unittest

from pathlib import Path

from pydantic_pkgr import BinProvider, EnvProvider, Binary, SemVer, ProviderLookupDict, bin_version


class TestSemVer(unittest.TestCase):

    def test_parsing(self):
        self.assertEqual(SemVer(None), None)
        self.assertEqual(SemVer(''), None)
        self.assertEqual(SemVer.parse(''), None)
        self.assertEqual(SemVer(1), (1, 0, 0))
        self.assertEqual(SemVer(1, 2), (1, 2, 0))
        self.assertEqual(SemVer('1.2+234234'), (1, 2, 234234))
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


    def test_bash_env(self):
        provider = EnvProvider()

        bash_bin = provider.load_or_install('bash')
        self.assertGreater(bash_bin.loaded_version, SemVer('4.2'))
        self.assertEqual(bash_bin.loaded_abspath, Path(shutil.which('bash')))
        self.assertTrue(bash_bin.is_valid)
        self.assertTrue(bash_bin.is_executable)
        self.assertFalse(bash_bin.is_script)
        self.assertTrue(bool(str(bash_bin)))  # easy way to make sure serializing doesnt throw an error

    def test_overrides(self):
        
        class TestRecord:
            called_abspath_custom = False
            called_version_custom = False
            called_subdeps_custom = False
            called_install_custom = False


        class CustomProvider(BinProvider):
            name: str = 'CustomProvider'

            abspath_provider: ProviderLookupDict = {
                '*': 'self.on_abspath_custom'
            }
            version_provider: ProviderLookupDict = {
                '*': 'self.on_version_custom'
            }
            subdeps_provider: ProviderLookupDict = {
                '*': 'self.on_subdeps_custom'
            }
            install_provider: ProviderLookupDict = {
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
            def on_subdeps_custom(self, bin_name: str, **context):
                TestRecord.called_subdeps_custom = True

            def on_install(self, bin_name: str, **context):
                raise NotImplementedError('whattt')

            def on_install_somebin(self, bin_name: str, **context):
                TestRecord.called_install_custom = True

        provider = CustomProvider(install_provider={'somebin': 'self.on_install_somebin'})

        self.assertFalse(TestRecord.called_abspath_custom)
        self.assertFalse(TestRecord.called_version_custom)
        self.assertFalse(TestRecord.called_subdeps_custom)
        self.assertFalse(TestRecord.called_install_custom)

        provider.get_abspath('doesnotexist')
        self.assertTrue(TestRecord.called_abspath_custom)

        provider.get_version('doesnotexist')
        self.assertTrue(TestRecord.called_version_custom)

        provider.get_subdeps('doesnotexist')
        self.assertTrue(TestRecord.called_subdeps_custom)

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
        provider = EnvProvider()

        python_bin = Binary(name='python', providers=[provider])

        self.assertIsNone(python_bin.loaded_provider)
        self.assertIsNone(python_bin.loaded_version)
        self.assertEqual(python_bin.loaded_abspath, Path(sys.executable).absolute())

        python_bin = python_bin.load()

        shallow_bin = provider.load_or_install('python')
        self.assertEqual(python_bin.loaded_provider, shallow_bin.loaded_provider)
        self.assertEqual(python_bin.loaded_abspath, shallow_bin.loaded_abspath)
        self.assertEqual(python_bin.loaded_version, shallow_bin.loaded_version)

        self.assertEqual(python_bin.loaded_version, SemVer('{}.{}.{}'.format(*sys.version_info[:3])))
        self.assertEqual(python_bin.loaded_abspath, Path(sys.executable).absolute())
        self.assertEqual(python_bin.loaded_respath, Path(sys.executable).resolve())
        self.assertTrue(python_bin.is_valid)
        self.assertTrue(python_bin.is_executable)
        self.assertFalse(python_bin.is_script)
        self.assertTrue(bool(str(python_bin)))  # easy way to make sure serializing doesnt throw an error


if __name__ == '__main__':
    unittest.main()
