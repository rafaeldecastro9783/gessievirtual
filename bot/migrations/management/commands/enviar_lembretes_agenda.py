from django.core.management.base import BaseCommand
from bot.models import Appointment
from bot.utils import enviar_mensagem_whatsapp
from datetime import datetime
import pytz

class Command(BaseCommand):
    help = "Envia lembretes para agendamentos do dia"

    def handle(self, *args, **kwargs):
        now = datetime.now(pytz.timezone("America/Sao_Paulo")).date()
        agendamentos = Appointment.objects.filter(data_hora__date=now, confirmado=True)

        for ag in agendamentos:
            try:
                texto = (
                    f"Olá {ag.person.nome}, lembrete: você tem um agendamento hoje com {ag.profissional} "
                    f"às {ag.data_hora.strftime('%H:%M')}."
                )
                enviar_mensagem_whatsapp(ag.person, ag.person, ag.data_hora, ag.client, texto=texto)
                print("✅ Lembrete enviado:", ag.person.nome)
            except Exception as e:
                print("❌ Erro ao enviar lembrete:", e)
