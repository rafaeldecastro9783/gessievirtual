import os
import django

# Inicializa o ambiente Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'whatsapp_chatgpt.settings')
django.setup()

from bot.models import Message, Person, Conversation, ClientUser
from django.contrib.auth.models import User
from django.utils.timezone import now

print("🔍 Iniciando verificação de mensagens órfãs...")

# Pega um client_user como referência (pode ser ajustado para o desejado)
user = User.objects.first()
if not hasattr(user, 'clientuser'):
    print("⚠️ Este usuário não está vinculado a um ClientUser.")
else:
    client_user = user.clientuser
    client = client_user.client

    msgs_corrigidas = 0

    for msg in Message.objects.filter(conversation__isnull=True):
        telefone = None

        # Tenta extrair telefone a partir da pessoa vinculada
        if msg.person:
            telefone = msg.person.telefone
        elif "mensagem" in msg.mensagem:
            # Extração alternativa, se necessário
            telefone = msg.mensagem.split()[0]  # só um fallback básico

        if not telefone:
            print(f"⛔ Mensagem {msg.id} sem telefone detectável.")
            continue

        # Recupera ou cria Person
        person, _ = Person.objects.get_or_create(
            telefone=telefone,
            client=client,
            defaults={"nome": telefone, "idade": "0"}
        )

        # Recupera ou cria Conversation
        conversation, _ = Conversation.objects.get_or_create(
            phone=telefone,
            defaults={"thread_id": ""}
        )

        # Atribuições
        msg.person = person
        msg.conversation = conversation

        if msg.enviado_por == "usuario":
            msg.client_user = client_user

        msg.save()
        msgs_corrigidas += 1

    print(f"✅ Correção finalizada: {msgs_corrigidas} mensagens atualizadas.")

