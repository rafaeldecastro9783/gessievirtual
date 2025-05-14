import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "whatsapp_chatgpt.settings")
django.setup()

from django.core.management.base import BaseCommand
from bot.models import Message, ClientConfig, ClientUser
from django.contrib.auth.models import User

from bot.models import Disponibilidade
import ast

for d in Disponibilidade.objects.all():
    if isinstance(d.horarios, str) and d.horarios.startswith('['):
        try:
            d.horarios = ast.literal_eval(d.horarios)
            d.save()
            print(f"Corrigido ID: {d.id}")
        except Exception as e:
            print(f"Erro no ID {d.id}: {e}")
