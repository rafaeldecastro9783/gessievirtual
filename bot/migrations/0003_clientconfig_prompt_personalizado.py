# Generated by Django 5.1.7 on 2025-04-18 23:57

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('bot', '0002_clientconfig_pendingmessage_clientuser_person_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='clientconfig',
            name='prompt_personalizado',
            field=models.TextField(default='Olá! Sou a Gessie, sua assistente virtual. Como posso te ajudar hoje?'),
            preserve_default=False,
        ),
    ]
