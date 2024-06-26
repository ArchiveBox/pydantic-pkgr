# Generated by Django 5.0.6 on 2024-05-21 02:39

import django.core.serializers.json
import django_pydantic_field.fields
import pydantic_pkgr.semver
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('project', '0001_initial'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='dependency',
            options={'verbose_name_plural': 'Dependencies'},
        ),
        migrations.AddField(
            model_name='dependency',
            name='min_version',
            field=django_pydantic_field.fields.PydanticSchemaField(config=None, default=[0, 0, 1], encoder=django.core.serializers.json.DjangoJSONEncoder, schema=pydantic_pkgr.semver.SemVer),
        ),
    ]
