# Generated by Django 5.1.7 on 2025-04-21 02:31

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('bot', '0012_clientuser_user'),
    ]

    operations = [
        migrations.AddField(
            model_name='appointment',
            name='criado_em',
            field=models.DateTimeField(null=True),
        ),
    ]
