# Generated by Django 5.1.7 on 2025-04-19 03:41

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('bot', '0006_alter_message_person'),
    ]

    operations = [
        migrations.AddField(
            model_name='person',
            name='responsavel',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='bot.clientuser'),
        ),
    ]
