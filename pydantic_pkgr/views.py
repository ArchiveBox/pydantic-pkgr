# pip install django-admin-data-views

from django.http import HttpRequest
from django.utils.html import format_html, mark_safe

from admin_data_views.typing import TableContext, ItemContext
from admin_data_views.utils import render_with_table_view, render_with_item_view, ItemLink

from django.conf import settings

from .binary import Binary


def get_all_binaries() -> list[Binary]:
    """Monkey patch this function implement getting the list of binaries to render"""
    return []


@render_with_table_view
def binaries_list_view(request: HttpRequest, **kwargs) -> TableContext:

    assert request.user.is_superuser, 'Must be a superuser to view configuration settings.'

    rows = {
        "Binary": [],
        "Found Version": [],
        "Provided By": [],
        "Found Abspath": [],
        "Related Configuration": [],
        "Overrides": [],
        "Description": [],
    }

    relevant_configs = {
        key: val
        for key, val in settings.CONFIG.items()
        if '_BINARY' in key or '_VERSION' in key
    }

    for binary in get_all_binaries():
        binary = binary.load_or_install()

        rows['Binary'].append(ItemLink(binary.name, key=binary.name))
        rows['Found Version'].append(binary.loaded_version)
        rows['Provided By'].append(binary.loaded_provider)
        rows['Found Abspath'].append(binary.loaded_abspath)
        rows['Related Configuration'].append(mark_safe(', '.join(
            f'<a href="/admin/environment/config/{config_key}/">{config_key}</a>'
            for config_key, config_value in relevant_configs.items()
                if binary.name.lower().replace('-', '').replace('_', '').replace('ytdlp', 'youtubedl') in config_key.lower()
                # or binary.name.lower().replace('-', '').replace('_', '') in str(config_value).lower()
        )))
        rows['Overrides'].append(str(binary.provider_overrides))
        rows['Description'].append(binary.description)

    return TableContext(
        title="Binaries",
        table=rows,
    )

@render_with_item_view
def binary_detail_view(request: HttpRequest, key: str, **kwargs) -> ItemContext:

    assert request.user.is_superuser, 'Must be a superuser to view configuration settings.'

    binary = None
    for loaded_binary in get_all_binaries():
        if loaded_binary.name == key:
            binary = loaded_binary


    assert binary, f'Could not find a binary matching the specified name: {key}'

    binary = binary.load_or_install()

    return ItemContext(
        slug=key,
        title=key,
        data=[
            {
                "name": binary.name,
                "description": binary.description,
                "fields": {
                    'binprovider': binary.loaded_provider,
                    'abspath': binary.loaded_abspath,
                    'version': binary.loaded_version,
                    'overrides': str(binary.provider_overrides),
                    'providers': str(binary.providers_supported),
                },
                "help_texts": {
                    # TODO
                },
            },
        ],
    )
