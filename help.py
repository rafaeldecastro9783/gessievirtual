import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "whatsapp_chatgpt.settings")
django.setup()

from django.core.management.base import BaseCommand
from bot.models import Message, ClientConfig, ClientUser
from django.contrib.auth.models import User

class Command(BaseCommand):
    help = "Corrige mensagens do tipo 'usuario' sem ClientUser associado"

    def handle(self, *args, **options):
        corrigidas = 0

        for config in ClientConfig.objects.all():
            telefone = config.telefone

            client_user = ClientUser.objects.filter(telefone=telefone, client=config).first()
            if not client_user:
                self.stdout.write(f"🔧 Criando ClientUser Sistema para {telefone}")
                user = User.objects.create_user(
                    username=f"sistema_{config.id}",
                    password="senha_segura123",
                    first_name="Sistema"
                )
                client_user = ClientUser.objects.create(
                    user=user,
                    client=config,
                    nome="Sistema",
                    telefone=telefone,
                    email=f"sistema_{config.id}@softdotpro.com",
                )

            mensagens = Message.objects.filter(
                enviado_por="usuario",
                client_user__isnull=True,
                person__client=config
            )

            for msg in mensagens:
                msg.client_user = client_user
                msg.save()
                corrigidas += 1

        self.stdout.write(self.style.SUCCESS(f"✅ Mensagens corrigidas: {corrigidas}"))
