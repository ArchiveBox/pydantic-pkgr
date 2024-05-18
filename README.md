# `pydantic-pkgr`

[![GitHub][licence-badge]][licence]
[![GitHub Last Commit][repo-badge]][repo]
[![GitHub Issues][issues-badge]][issues]

[![PyPI][pypi-badge]][pypi]
[![Python Version][version-badge]][pypi]
[![Django Version][django-badge]][pypi]
[![Downloads][downloads-badge]][pypi]

```shell
pip install pydantic-pkgr
```

**This is a Python package that allows you to manage system dependencies with a variety of package managers.**

*This was built by [ArchiveBox](https://github.com/ArchiveBox) to auto-install and maintain dependencies like `chrome`, `wget`, `curl`, etc. across all our supported OS's.*

---

**Source Code**: [https://github.com/ArchiveBox/pydantic-pkgr/](https://github.com/ArchiveBox/pydantic-pkgr/)

**Documentation**: [https://github.com/ArchiveBox/pydantic-pkgr/blob/main/README.md](https://github.com/ArchiveBox/pydantic-pkgr/blob/main/README.md)

---

```python
from pydantic_pkgr import AptProvider

apt = AptProvider()
curl = apt.load_or_install(bin_name='curl')
print(curl.loaded_version)            # Path('/usr/bin/curl')
print(curl.loaded_version)            # SemVer('8.4.0')
curl.exec(['--version'])              # curl 7.81.0 (x86_64-pc-linux-gnu) libcurl/7.81.0 ...
```

> It's built with [`pydantic`](https://pydantic-docs.helpmanual.io/) v2 and supports [`django`](https://docs.djangoproject.com/en/5.0/) >= 4.0 out-of-the-box.

**So far it supports `installing`/`finding installed`/~~`updating`/`removing`~~ packages with:**

- `apt`
- `brew`
- `pip`
- `npm`
- `env` (looks for existing version of binary in user's `$PATH` at runtime)
- `vendor` (you can bundle vendored copies of packages you depend on within your source)

*Planned:*
- `docker pull`
- `cargo`
- `go get`
- `gem`
- `pkg`
- `nix`
- *and more using `ansible`/[`pyinfra`](https://github.com/pyinfra-dev/pyinfra)...*



---


## Usage

```bash
pip install pydantic-pkgr
```


```python
import platform
from typing import List


from pydantic_pkgr.binproviders import EnvProvider, PipProvider, AptProvider, BrewProvider


### Example: Finding an existing install of bash using the system $PATH environment
env = EnvProvider()
bash = env.load(bin_name='bash')
print(bash.loaded_abspath)            # Path('/opt/homebrew/bin/bash')
print(bash.loaded_version)            # SemVer('5.2.26')
bash.exec(['-c', 'echo hi'])          # hi

### Example: Installing curl using the apt package manager
apt = AptProvider()
curl = apt.install(bin_name='curl')
print(curl.loaded_version)            # Path('/usr/bin/curl')
print(curl.loaded_version)            # SemVer('8.4.0')
curl.exec(['--version'])              # curl 7.81.0 (x86_64-pc-linux-gnu) libcurl/7.81.0 ...

### Example: Finding/Installing django with pip (w/ customized binpath resolution behavior)
pip = PipProvider(
    abspath_provider={'*': lambda bin_name, **_: inspect.getfile(bin_name)},
)
django_bin = pip.load_or_install(bin_name='django')
print(django_bin.loaded_abspath)      # Path('/usr/lib/python3.10/site-packages/django/__init__.py')
print(django_bin.loaded_version)      # SemVer('5.0.2')



from pydantic_pkgr.types import BinProvider, Binary, BinProviderName, BinName, ProviderLookupDict, SemVer

### Example: Create a re-usable class defining a binary and its providers

class YtdlpBinary(Binary):
    name: BinName = 'ytdlp'
    description: str = 'YT-DLP (Replacement for YouTube-DL) Media Downloader'

    providers_supported: List[BinProvider] = [EnvProvider(), PipProvider(), AptProvider(), BrewProvider()]
    
    # customize installed package names for specific package managers
    provider_overrides: Dict[BinProviderName, ProviderLookupDict] = {
        'pip': {'subdeps': lambda: 'yt-dlp[default,curl-cffi]'}},
        'apt': {'subdeps': lambda: 'yt-dlp ffmpeg'}},
        'brew': {'subdeps': lambda: 'yt-dlp ffmpeg'}},
    }

ytdlp = YtdlpBinary().load_or_install()
print(ytdlp.loaded_provider)              # 'brew'
print(ytdlp.loaded_abspath)               # Path('/opt/homebrew/bin/yt-dlp')
print(ytdlp.loaded_version)               # SemVer('2024.4.9')
print(ytdlp.is_valid)                     # True



#### Example: Create a binary that uses Podman if available, or Docker otherwise

class DockerBinary(Binary):
    name: BinName = 'docker'

    providers_supported: List[BinProvider] = [EnvProvider(), AptProvider()]
    
    provider_overrides: Dict[BinProviderName, ProviderLookupDict] = {
        'env': {
            # prefer podman if installed (or fall back to docker)
            'abspath': lambda: os.which('podman') or os.which('docker') or os.which('docker-ce'),
        },
        'apt': {
            # install docker OR docker-ce (varies based on CPU architecture)
            'subdeps': lambda: {
                'amd64': 'docker',
                'armv7l': 'docker-ce',
                'arm64': 'docker-ce',
            }.get(platform.machine()) or 'docker',
        },
    }

docker = DockerBinary().load_or_install()
print(docker.loaded_provider)             # 'env'
print(docker.loaded_abspath)              # '/usr/local/bin/podman'
print(docker.loaded_version)              # Ž6.0.2'
print(docker.is_valid)                    # True


# You can also pass **kwargs to override properties at runtime,
# e.g. if you want to force the abspath to be at a specific path:
custom_docker = DockerBinary(loaded_abspath='~/custom/bin/podman').load()
print(custom_docker.name)                 # 'docker'
print(custom_docker.loaded_provider)      # 'env'
print(custom_docker.loaded_abspath)       # '/Users/example/custom/bin/podman'
print(custom_docker.loaded_version)       # '5.0.2'
print(custom_docker.is_valid)             # True


### Example: Implement your own package manager behavior by subclassing BinProvider

class CargoProvider(BinProvider):
    name: BinProviderName = 'cargo'
    
    def on_setup_paths(self):
        if '~/.cargo/bin' not in sys.path:
            sys.path.append('~/.cargo/bin')

    def on_install(self, bin_name: str, **context):
        subdeps = self.on_get_subdeps(bin_name)
        installer_process = run(['cargo', 'install', *subdeps.split(' ')], stdout=PIPE, stderr=PIPE)
        assert installer_process.returncode == 0

    def on_get_subdeps(self, bin_name: BinName, **context) -> InstallStr:
        # optionally remap bin_names to strings passed to installer 
        # e.g. 'yt-dlp' -> 'yt-dlp ffmpeg libcffi libaac'
        return bin_name

    def on_get_abspath(self, bin_name: str, **context) -> Path | None:
        self.on_setup_paths()
        return Path(os.which(bin_name))

    def on_get_version(self, bin_name: BinName, **context) -> SemVer | None:
        self.on_setup_paths()
        return SemVer(run([bin_name, '--version'], stdout=PIPE).stdout.decode())

cargo = CargoProvider()
cargo.install(bin_name='ripgrep')


### Example: Use the SemVer type directly for parsing & verifying version strings

SemVer.parse('Google Chrome 124.0.6367.208+beta_234. 234.234.123')  # SemVer('124.0.6367')
SemVer.parse('2024.04.05)                                           # SemVer(2024, 4, 5)
SemVer.parse('1.9+beta')                                            # SemVer(1, 9, 0)
```

---


## Django Usage

The pydantic ecosystem allows us to get auto-generated, type-checked form widgets 
for editing `BinProvider` and `Binary` data without too much effort.


> For the full experience, we recommend installing these 3 excellent packages:
> 
> - [`django-admin-data-views`](https://github.com/MrThearMan/django-admin-data-views)
> - [`django-pydantic-field`](https://github.com/surenkov/django-pydantic-field)
> - [`django-jsonform`](https://django-jsonform.readthedocs.io/)
> `pip install pydantic-pkgr django-admin-data-views django-pydantic-field django-jsonform`

<br/>

### Django Model Usage: Store `BinProvider` and `Binary` entries in your model fields

- [`django-pydantic-field`](https://github.com/surenkov/django-pydantic-field)



Usage in your `models.py`:
```python
from django.db import models
from django_pydantic_field import SchemaField

DEFAULT_PROVIDER = EnvProvider()

class MyModel(models.Model):
    ...

    # SchemaField supports storing a single BinProvider/Binary in a field...
    favorite_binprovider: BinProvider = SchemaField(default=DEFAULT_PROVIDER)

    # ... or inside a collection type like list[...] dict[...]
    optional_binaries: list[Binary] = SchemaField(default=[])

curl = Binary(name='curl', providers=[DEFAULT_PROVIDER]).load()

obj = MyModel(optional_binaries=[curl])
obj.save()

assert obj.favorite_binprovider == DEFAULT_PROVIDER
assert obj.optional_binaries[0].provider == DEFAULT_PROVIDER
```


### Django Admin Usage: Show read-only list of BinProviders and Binaries in Admin UI

Then add this to your `settings.py`:
```python
INSTALLED_APPS = [
    # ...

    'pydantic_pkgr'
    'admin_data_views'

    # ...
]

ADMIN_DATA_VIEWS = {
    "NAME": "Environment",
    "URLS": [
        {
            "route": "binproviders/",
            "view": "pydantic_pkgr.views.binproviders_list_view",
            "name": "binproviders",
            "items": {
                "route": "<str:key>/",
                "view": "pydantic_pkgr.views.binprovider_detail_view",
                "name": "binprovider",
            },
        },
        {
            "route": "binaries/",
            "view": "pydantic_pkgr.views.binaries_list_view",
            "name": "binaries",
            "items": {
                "route": "<str:key>/",
                "view": "pydantic_pkgr.views.binary_detail_view",
                "name": "binary",
            },
        },
    ],
}
```

<details>
<summary><i>Note: If you override the default site admin, you must register the views manually...</i></summary><br/>
<br/>
<b><code>admin.py</code>:</b>
<br/>
<pre><code>
from django.contrib import admin

class YourSiteAdmin(admin.AdminSite):
    """Your customized version of admin.AdminSite"""
    ...

custom_admin = YourSiteAdmin()
custom_admin.register(get_user_model())
...

# Register the django-admin-data-views manually on your custom site admin
from admin_data_views.admin import get_app_list, get_urls, admin_data_index_view, get_admin_data_urls

custom_admin.get_app_list           = get_app_list.__get__(custom_admin, YourSiteAdmin)
custom_admin.get_admin_data_urls    = get_admin_data_urls.__get__(custom_admin, YourSiteAdmin)
custom_admin.admin_data_index_view  = admin_data_index_view.__get__(custom_admin, YourSiteAdmin)
custom_admin.get_urls               = get_urls(custom_admin.get_urls).__get__(custom_admin, YourSiteAdmin)

</code></pre>
</details>


### Django Admin Usage: JSONFormWidget for editing `BinProvider` and `Binary` data

Install `django-jsonform` to get auto-generated Forms for editing BinProvider, Binary, etc. data
```bash
pip install django-jsonform
```

`admin.py`:
```python
from django.contrib import admin
from django_jsonform.widgets import JSONFormWidget
from django_pydantic_field.v2.fields import PydanticSchemaField

class MyModelAdmin(admin.ModelAdmin):
    formfield_overrides = {PydanticSchemaField: {"widget": JSONFormWidget}}

admin.site.register(MyModel, MyModelAdmin)
```
<br/>

---

<br/>

### TODO

- [] Add `preinstall` and `postinstall` hooks for things like adding `apt` sources and running cleanup scripts
- [] Provide editability and actions via Django Admin UI using [`django-pydantic-field`](https://github.com/surenkov/django-pydantic-field) and [`django-jsonform`](https://django-jsonform.readthedocs.io/en/latest/)
- [] Write more documentation

[coverage-badge]: https://coveralls.io/repos/github/ArchiveBox/pydantic-pkgr/badge.svg?branch=main
[status-badge]: https://img.shields.io/github/actions/workflow/status/ArchiveBox/pydantic-pkgr/test.yml?branch=main
[pypi-badge]: https://img.shields.io/pypi/v/archivebox
[licence-badge]: https://img.shields.io/github/license/ArchiveBox/pydantic-pkgr
[repo-badge]: https://img.shields.io/github/last-commit/ArchiveBox/pydantic-pkgr
[issues-badge]: https://img.shields.io/github/issues-raw/ArchiveBox/pydantic-pkgr
[version-badge]: https://img.shields.io/pypi/pyversions/archivebox
[downloads-badge]: https://img.shields.io/pypi/dm/archivebox
[django-badge]: https://img.shields.io/pypi/djversions/archivebox

[coverage]: https://coveralls.io/github/ArchiveBox/pydantic-pkgr?branch=main
[status]: https://github.com/ArchiveBox/pydantic-pkgr/actions/workflows/test.yml
[pypi]: https://pypi.org/project/pydantic-pkgr
[licence]: https://github.com/ArchiveBox/pydantic-pkgr/blob/main/LICENSE
[repo]: https://github.com/ArchiveBox/pydantic-pkgr/commits/main
[issues]: https://github.com/ArchiveBox/pydantic-pkgr/issues
