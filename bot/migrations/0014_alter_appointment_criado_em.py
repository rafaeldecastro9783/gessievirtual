# Generated by Django 5.1.7 on 2025-04-21 02:33

import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('bot', '0013_appointment_criado_em'),
    ]

    operations = [
        migrations.AlterField(
            model_name='appointment',
            name='criado_em',
            field=models.DateTimeField(default=django.utils.timezone.now),
        ),
    ]
