<h1><a href="https://github.com/ArchiveBox/pydantic-pkgr"><code>pydantic-pkgr</code></a> &nbsp; &nbsp; &nbsp; &nbsp; 📦  <small><code>apt</code>&nbsp; <code>brew</code>&nbsp; <code>pip</code>&nbsp; <code>npm</code> &nbsp;₊₊₊</small><br/><sub>Simple Pydantic interfaces for package managers + installed binaries.</sub></h1>
<br/>

[![PyPI][pypi-badge]][pypi]
[![Python Version][version-badge]][pypi]
[![Django Version][django-badge]][pypi]
[![GitHub][licence-badge]][licence]
[![GitHub Last Commit][repo-badge]][repo]
<!--[![Downloads][downloads-badge]][pypi]-->

<br/>

**This is a [Python library](https://pypi.org/project/pydantic-pkgr/) for installing & managing packages locally with a variety of package managers.**  
It's designed for when `pip` dependencies aren't enough, and your app has to install local binaries at runtime.  


```shell
pip install pydantic-pkgr
```


> ✨ Built with [`pydantic`](https://pydantic-docs.helpmanual.io/) v2 for strong static typing guarantees and json import/export compatibility  
> 📦 Provides consistent cross-platform interfaces for dependency resolution & installation at runtime  
> 🌈 Integrates with [`django`](https://docs.djangoproject.com/en/5.0/) >= 4.0, [`django-ninja`](https://django-ninja.dev/), and OpenAPI + [`django-jsonform`](https://django-jsonform.readthedocs.io/) out-of-the-box  
> 🦄 Uses [`pyinfra`](https://github.com/pyinfra-dev/pyinfra) / [`ansible`](https://github.com/ansible/ansible) for the actual install operations whenever possible (with internal fallbacks)

<sub><i>Built by <a href="https://github.com/ArchiveBox">ArchiveBox</a> to install & auto-update our extractor dependencies at runtime (<code>chrome</code>, <code>wget</code>, <code>curl</code>, etc.) on `macOS`/`Linux`/`Docker`.</i></sub>

<br/>

> [!WARNING]
> This is `BETA` software, the API is mostly stable but there may be minor changes later on.


**Source Code**: [https://github.com/ArchiveBox/pydantic-pkgr/](https://github.com/ArchiveBox/pydantic-pkgr/)

**Documentation**: [https://github.com/ArchiveBox/pydantic-pkgr/blob/main/README.md](https://github.com/ArchiveBox/pydantic-pkgr/blob/main/README.md)

<br/>

```python
from pydantic_pkgr import *

apt, brew, pip, npm, env = AptProvider(), BrewProvider(), PipProvider(), NpmProvider(), EnvProvider()

dependencies = [
    Binary(name='curl',       providers=[env, apt, brew]),
    Binary(name='wget',       providers=[env, apt, brew]),
    Binary(name='yt-dlp',     providers=[env, pip, apt, brew]),
    Binary(name='playwright', providers=[env, pip, npm]),
    Binary(name='puppeteer',  providers=[env, npm]),
]
for binary in dependencies:
    binary = binary.load_or_install()

    print(binary.abspath, binary.version, binary.provider, binary.is_valid)
    # Path('/usr/bin/curl') SemVer('7.81.0') 'apt' True

    binary.exec(cmd=['--version'])   # curl 7.81.0 (x86_64-apple-darwin23.0) libcurl/7.81.0 ...
```

```python
from pydantic_pkgr import Binary, BinProvider, BrewProvider, EnvProvider

# you can also define binaries as classes, making them usable for type checking
class CurlBinary(Binary):
    name: str = 'curl'
    providers: list[BinProvider] = [BrewProvider(), EnvProvider()]

curl = CurlBinary().install()
assert isinstance(curl, CurlBinary)                              # CurlBinary is a unique type you can use in annotations now
print(curl.abspath, curl.version, curl.provider, curl.is_valid)  # Path('/opt/homebrew/bin/curl') SemVer('8.4.0') 'brew' True
curl.exec(cmd=['--version'])                                     # curl 8.4.0 (x86_64-apple-darwin23.0) libcurl/8.4.0 ...
```

```python
from pydantic_pkgr import Binary, EnvProvider, PipProvider

# We also provide direct package manager (aka BinProvider) APIs
apt = AptProvider()
apt.install('wget')
print(apt.PATH, apt.get_abspaths('wget'), apt.get_version('wget'))

# even if packages are installed by tools we don't control (e.g. pyinfra/ansible/puppet/etc.)
from pyinfra.operations import apt
apt.packages(name="Install ffmpeg", packages=['ffmpeg'], _sudo=True)

# our Binary API provides a nice type-checkable, validated, serializable handle
ffmpeg = Binary(name='ffmpeg').load()
print(ffmpeg)                       # name=ffmpeg abspath=/usr/bin/ffmpeg version=3.3.0 is_valid=True ...
print(ffmpeg.loaded_abspaths)       # show all the ffmpeg binaries found in $PATH (in case theres more than one available)
print(ffmpeg.model_dump_json())     # ... everything can also be dumped/loaded as json
print(ffmpeg.model_json_schema())   # ... all types provide OpenAPI-ready JSON schemas
```

### Supported Package Managers

**So far it supports `installing`/`finding installed`/~~`updating`/`removing`~~ packages on `Linux`/`macOS` with:**

- `apt` (Ubuntu/Debian/etc.)
- `brew` (macOS/Linux)
- `pip` (Linux/macOS/Windows)
- `npm` (Linux/macOS/Windows)
- `env` (looks for existing version of binary in user's `$PATH` at runtime)
- `vendor` (you can bundle vendored copies of packages you depend on within your source)

*Planned:* `docker`, `cargo`, `nix`, `apk`, `go get`, `gem`, `pkg`, *and more using `ansible`/[`pyinfra`](https://github.com/pyinfra-dev/pyinfra)...*

---


## Usage

```bash
pip install pydantic-pkgr
```

### [`BinProvider`](https://github.com/ArchiveBox/pydantic-pkgr/blob/main/pydantic_pkgr/binprovider.py#:~:text=class%20BinProvider)

**Implementations: `EnvProvider`, `AptProvider`, `BrewProvider`, `PipProvider`, `NpmProvider`**

This type represents a "provider of binaries", e.g. a package manager like `apt`/`pip`/`npm`, or `env` (which finds binaries in your `$PATH`).

`BinProvider`s implement the following interface:
- `load(bin_name: str)`, `install(bin_name: str)`, `load_or_install(bin_name: str)` `->` `Binary`
- `get_abspaths(bin_name: str) -> [Path('/absolute/path/to/bin'), Path('/other/paths/to/bin'), ...]`
- `get_abspath(bin_name: str) -> Path('/absolute/path/to/bin')`
- `get_version(bin_name: str) -> SemVer('1.0.0')`
- `get_subdeps(bin_name: str) -> InstallStr('somepackage some-extras')`
- `@PATH -> PATHStr('/usr/local/bin:/usr/bin:/bin:...')`

```python
import platform
from typing import List
from pydantic_pkgr import EnvProvider, PipProvider, AptProvider, BrewProvider

### Example: Finding an existing install of bash using the system $PATH environment
env = EnvProvider()
bash = env.load(bin_name='bash')
print(bash.abspath)                   # Path('/opt/homebrew/bin/bash')
print(bash.version)                   # SemVer('5.2.26')
bash.exec(['-c', 'echo hi'])          # hi

### Example: Installing curl using the apt package manager
apt = AptProvider()
curl = apt.install(bin_name='curl')
print(curl.abspath)                   # Path('/usr/bin/curl')
print(curl.version)                   # SemVer('8.4.0')
curl.exec(['--version'])              # curl 7.81.0 (x86_64-pc-linux-gnu) libcurl/7.81.0 ...

### Example: Finding/Installing django with pip (w/ customized binpath resolution behavior)
pip = PipProvider(
    abspath_provider={'*': lambda bin_name, **context: inspect.getfile(bin_name)},  # use python inspect to get path instead of os.which
)
django_bin = pip.load_or_install(bin_name='django')
print(django_bin.abspath)             # Path('/usr/lib/python3.10/site-packages/django/__init__.py')
print(django_bin.version)             # SemVer('5.0.2')
```

### [`Binary`](https://github.com/ArchiveBox/pydantic-pkgr/blob/main/pydantic_pkgr/binary.py#:~:text=class%20Binary)

This type represents a single binary dependency aka a package (e.g. `wget`, `curl`, `ffmpeg`, etc.).  
It can define one or more `BinProvider`s that it supports, along with overrides to customize the behavior for each.

`Binary`s implement the following interface:
- `load()`, `install()`, `load_or_install()` `->` `Binary`
- `provider: BinProviderName` (`BinProviderName == str`)
- `abspath: Path`
- `abspaths: List[Path]`
- `version: SemVer`

```python
from pydantic_pkgr import BinProvider, Binary, BinProviderName, BinName, ProviderLookupDict, SemVer

### Example: Create a re-usable class defining a binary and its providers
class YtdlpBinary(Binary):
    name: BinName = 'ytdlp'
    description: str = 'YT-DLP (Replacement for YouTube-DL) Media Downloader'

    providers_supported: List[BinProvider] = [EnvProvider(), PipProvider(), AptProvider(), BrewProvider()]
    
    # customize installed package names for specific package managers
    provider_overrides: Dict[BinProviderName, ProviderLookupDict] = {
        'pip': {'subdeps': lambda: 'yt-dlp[default,curl-cffi]'}},
        'apt': {'subdeps': lambda: 'yt-dlp ffmpeg'}},
        'brew': {'subdeps': 'some.other.module.get_brew_subdeps'}},  # also accepts dotted import path to function
    }

ytdlp = YtdlpBinary().load_or_install()
print(ytdlp.provider)                     # 'brew'
print(ytdlp.abspath)                      # Path('/opt/homebrew/bin/yt-dlp')
print(ytdlp.abspaths)                     # [Path('/opt/homebrew/bin/yt-dlp'), Path('/usr/local/bin/yt-dlp')]
print(ytdlp.version)                      # SemVer('2024.4.9')
print(ytdlp.is_valid)                     # True
```

```python
from pydantic_pkgr import BinProvider, Binary, BinProviderName, BinName, ProviderLookupDict, SemVer

#### Example: Create a binary that uses Podman if available, or Docker otherwise
class DockerBinary(Binary):
    name: BinName = 'docker'

    providers_supported: List[BinProvider] = [EnvProvider(), AptProvider()]
    
    provider_overrides: Dict[BinProviderName, ProviderLookupDict] = {
        'env': {
            # example: prefer podman if installed (falling back to docker)
            'abspath': lambda: os.which('podman') or os.which('docker') or os.which('docker-ce'),
        },
        'apt': {
            # example: vary installed package name based on your CPU architecture
            'subdeps': lambda: {
                'amd64': 'docker',
                'armv7l': 'docker-ce',
                'arm64': 'docker-ce',
            }.get(platform.machine(), 'docker'),
        },
    }

docker = DockerBinary().load_or_install()
print(docker.provider)                    # 'env'
print(docker.abspath)                     # Path('/usr/local/bin/podman')
print(docker.abspaths)                    # [Path('/usr/local/bin/podman'), Path('/opt/homebrew/bin/podman')]
print(docker.version)                     # SemVer('6.0.2')
print(docker.is_valid)                    # True

# You can also pass **kwargs to override properties at runtime,
# e.g. if you want to force the abspath to be at a specific path:
custom_docker = DockerBinary(abspath='~/custom/bin/podman').load()
print(custom_docker.name)                 # 'docker'
print(custom_docker.provider)             # 'env'
print(custom_docker.abspath)              # Path('/Users/example/custom/bin/podman')
print(custom_docker.version)              # SemVer('5.0.2')
print(custom_docker.is_valid)             # True
```

### [`SemVer`](https://github.com/ArchiveBox/pydantic-pkgr/blob/main/pydantic_pkgr/semver.py#:~:text=class%20SemVer)

```python
from pydantic_pkgr import SemVer

### Example: Use the SemVer type directly for parsing & verifying version strings
SemVer.parse('Google Chrome 124.0.6367.208+beta_234. 234.234.123')  # SemVer(124, 0, 6367')
SemVer.parse('2024.04.05)                                           # SemVer(2024, 4, 5)
SemVer.parse('1.9+beta')                                            # SemVer(1, 9, 0)
str(SemVer(1, 9, 0))                                                # '1.9.0'
```
<br/>

> These types are all meant to be used library-style to make writing your own apps easier.  
> e.g. you can use it to build things like: [`playwright install --with-deps`](https://playwright.dev/docs/browsers#install-system-dependencies))


<br/>

---

<br/>


## Django Usage

The pydantic ecosystem helps us get auto-generated, type-checked Django fields & forms that support `BinProvider` and `Binary`.

> [!TIP]
> For the full Django experience, we recommend installing these 3 excellent packages:
> - [`django-admin-data-views`](https://github.com/MrThearMan/django-admin-data-views)
> - [`django-pydantic-field`](https://github.com/surenkov/django-pydantic-field)
> - [`django-jsonform`](https://django-jsonform.readthedocs.io/)  
> `pip install pydantic-pkgr django-admin-data-views django-pydantic-field django-jsonform`

<br/>

### Django Model Usage: Store `BinProvider` and `Binary` entries in your model fields

```bash
pip install django-pydantic-field
```

*Fore more info see the [`django-pydantic-field`](https://github.com/surenkov/django-pydantic-field) docs...*


Usage in your `models.py`:
```python
from django.db import models
from django_pydantic_field import SchemaField

from pydantic_pkgr import BinProvider, EnvProvider, Binary, SemVer

env = EnvProvider()

class Dependency(models.Model):
    """Example model for storing information about a dependency"""
    name = models.CharField(max_length=63)
    binary: Binary = SchemaField()
    providers: list[BinProvider] = SchemaField(default=[env])
    min_version: SemVer = SchemaField(default=(0,0,1))

curl = Binary(name='curl', providers=[env]).load()  # find existing curl binary in $PATH

model = Dependency(                               # create a DB record with our new model to represent curl
    name='curl',
    binary=curl,                                  # store Binary/BinProvider/SemVer values directly in fields
    providers=[env],                              # no need for manual JSON serialization / schema checking
    min_version=SemVer('6.5.0'),
)
model.save()                                      
model = Dependency.objects.get(name='curl')       # everything is transparently serialized to/from the DB,
                                                  # and is ready to go immediately after querying:
print(model.binary.abspath)                       #   Path('/usr/local/bin/curl')
model.binary.exec(['--version'])                  #   curl 7.81.0 (x86_64-apple-darwin23.0) libcurl/7.81.0 ...
assert model.binary.abspath == curl.abspath == env.get_abspath('curl')
assert model.providers[0] == curl.provider == env
assert model.binary.provider == curl.provider == env
```
*For a full example see our provided [`django_example_project/`](https://github.com/ArchiveBox/pydantic-pkgr/tree/main/django_example_project)...*

<br/>

### Django Admin Usage: Show read-only list of Binaries in Admin UI

<img height="220" alt="Django Admin binaries list view" src="https://github.com/ArchiveBox/pydantic-pkgr/assets/511499/a9980217-f39e-434e-b266-20cd6feb17c3" align="top"><img height="220" alt="Django Admin binaries detail view" src="https://github.com/ArchiveBox/pydantic-pkgr/assets/511499/d4d9086e-c8f4-4b6e-8ee8-8c8a864715b0" align="top">

```bash
pip install pydantic-pkgr django-admin-data-views
```
*For more info see the [`django-admin-data-views`](https://github.com/MrThearMan/django-admin-data-views) docs...*

Then add this to your `settings.py`:
```python
INSTALLED_APPS = [
    # ...
    'admin_data_views'
    'pydantic_pkgr'
    # ...
]

# point these to a function that gets the list of all binaries / a single binary
PYDANTIC_PKGR_GET_ALL_BINARIES = 'pydantic_pkgr.views.get_all_binaries'
PYDANTIC_PKGR_GET_BINARY = 'pydantic_pkgr.views.get_binary'

ADMIN_DATA_VIEWS = {
    "NAME": "Environment",
    "URLS": [
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
        # Coming soon: binprovider_list_view + binprovider_detail_view ...
    ],
}
```
*For a full example see our provided [`django_example_project/`](https://github.com/ArchiveBox/pydantic-pkgr/tree/main/django_example_project)...*

<details>
<summary><i>Note: If you override the default site admin, you must register the views manually...</i></summary>
<br/><br/>
<b><code>admin.py</code>:</b>
<br/>
<pre><code>
class YourSiteAdmin(admin.AdminSite):
    """Your customized version of admin.AdminSite"""
    ...
<br/>
custom_admin = YourSiteAdmin()
custom_admin.register(get_user_model())
...
from pydantic_pkgr.admin import register_admin_views
register_admin_views(custom_admin)
</code></pre>
</details>

<br/>

### ~~Django Admin Usage: JSONFormWidget for editing `BinProvider` and `Binary` data~~

<img src="https://github.com/ArchiveBox/pydantic-pkgr/assets/511499/63705a57-4f62-4dbe-9f3a-0515323d8b5e" width="600px"/>

> [!IMPORTANT]
> This feature is coming soon but is blocked on a few issues being fixed first:  
> - https://github.com/surenkov/django-pydantic-field/issues/64
> - https://github.com/surenkov/django-pydantic-field/issues/65
> - https://github.com/surenkov/django-pydantic-field/issues/66

~~Install `django-jsonform` to get auto-generated Forms for editing BinProvider, Binary, etc. data~~
```bash
pip install django-pydantic-field django-jsonform
```
*For more info see the [`django-jsonform`](https://django-jsonform.readthedocs.io/) docs...*

`admin.py`:
```python
from django.contrib import admin
from django_jsonform.widgets import JSONFormWidget
from django_pydantic_field.v2.fields import PydanticSchemaField

class MyModelAdmin(admin.ModelAdmin):
    formfield_overrides = {PydanticSchemaField: {"widget": JSONFormWidget}}

admin.site.register(MyModel, MyModelAdmin)
```
*For a full example see our provided [`django_example_project/`](https://github.com/ArchiveBox/pydantic-pkgr/tree/main/django_example_project)...*

<br/>

---

<br/>


## Examples

### Advanced: Implement your own package manager behavior by subclassing BinProvider

```python
from subprocess import run, PIPE

from pydantic_pkgr import BinProvider, BinProviderName, BinName, SemVer

class CargoProvider(BinProvider):
    name: BinProviderName = 'cargo'
    
    def on_setup_paths(self):
        if '~/.cargo/bin' not in sys.path:
            sys.path.append('~/.cargo/bin')

    def on_install(self, bin_name: BinName, **context):
        subdeps = self.on_get_subdeps(bin_name)
        installer_process = run(['cargo', 'install', *subdeps.split(' ')], stdout=PIPE, stderr=PIPE)
        assert installer_process.returncode == 0

    def on_get_subdeps(self, bin_name: BinName, **context) -> InstallStr:
        # optionally remap bin_names to strings passed to installer 
        # e.g. 'yt-dlp' -> 'yt-dlp ffmpeg libcffi libaac'
        return bin_name

    def on_get_abspath(self, bin_name: BinName, **context) -> Path | None:
        self.on_setup_paths()
        return Path(os.which(bin_name))

    def on_get_version(self, bin_name: BinName, **context) -> SemVer | None:
        self.on_setup_paths()
        return SemVer(run([bin_name, '--version'], stdout=PIPE).stdout.decode())

cargo = CargoProvider()
rg = cargo.install(bin_name='ripgrep')
print(rg.provider)                      # 'cargo'
print(rg.version)                       # SemVer(14, 1, 0)
```


<br/>

---

<br/>

### TODO

- [x] Implement initial basic support for `apt`, `brew`, and `pip`
- [x] Provide editability and actions via Django Admin UI using [`django-pydantic-field`](https://github.com/surenkov/django-pydantic-field) and [`django-jsonform`](https://django-jsonform.readthedocs.io/en/latest/)
- [ ] Implement `update` and `remove` actions on BinProviders
- [ ] Add `preinstall` and `postinstall` hooks for things like adding `apt` sources and running cleanup scripts
- [ ] Implement more package managers (`cargo`, `gem`, `go get`, `ppm`, `nix`, `docker`, etc.)
- [ ] Add `Binary.min_version` that affects `.is_valid` based on whether it meets minimum `SemVer` threshold


### Other Packages We Like

- https://github.com/MrThearMan/django-signal-webhooks
- https://github.com/MrThearMan/django-admin-data-views
- https://github.com/lazybird/django-solo
- https://github.com/joshourisman/django-pydantic-settings
- https://github.com/surenkov/django-pydantic-field
- https://github.com/jordaneremieff/djantic

[coverage-badge]: https://coveralls.io/repos/github/ArchiveBox/pydantic-pkgr/badge.svg?branch=main
[status-badge]: https://img.shields.io/github/actions/workflow/status/ArchiveBox/pydantic-pkgr/test.yml?branch=main
[pypi-badge]: https://img.shields.io/pypi/v/pydantic-pkgr?v=1
[licence-badge]: https://img.shields.io/github/license/ArchiveBox/pydantic-pkgr?v=1
[repo-badge]: https://img.shields.io/github/last-commit/ArchiveBox/pydantic-pkgr?v=1
[issues-badge]: https://img.shields.io/github/issues-raw/ArchiveBox/pydantic-pkgr?v=1
[version-badge]: https://img.shields.io/pypi/pyversions/pydantic-pkgr?v=1
[downloads-badge]: https://img.shields.io/pypi/dm/pydantic-pkgr?v=1
[django-badge]: https://img.shields.io/pypi/djversions/pydantic-pkgr?v=1

[coverage]: https://coveralls.io/github/ArchiveBox/pydantic-pkgr?branch=main
[status]: https://github.com/ArchiveBox/pydantic-pkgr/actions/workflows/test.yml
[pypi]: https://pypi.org/project/pydantic-pkgr
[licence]: https://github.com/ArchiveBox/pydantic-pkgr/blob/main/LICENSE
[repo]: https://github.com/ArchiveBox/pydantic-pkgr/commits/main
[issues]: https://github.com/ArchiveBox/pydantic-pkgr/issues
