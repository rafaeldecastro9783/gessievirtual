# Generated by Django 5.1.7 on 2025-06-05 15:44

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('bot', '0024_ordemservico'),
    ]

    operations = [
        migrations.AlterField(
            model_name='appointment',
            name='profissional',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='agendamentos_como_profissional', to='bot.clientuser'),
        ),
    ]
