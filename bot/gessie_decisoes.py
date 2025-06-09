from datetime import datetime, timedelta
import calendar
import requests
from django.utils.timezone import now as timezone_now
from bot.models import Person, ClientUser, Appointment
from bot.utils import (
    enviar_mensagem_whatsapp,
    registrar_mensagem,
    obter_regra,
    obter_horarios_disponiveis_por_data,
)

# 🔎 Busca o próximo horário disponível para um profissional
def encontrar_proximo_horario_disponivel(client_config, unidade_id=None, profissional_nome=None, data_desejada=None):
    print("🔍 Buscando próximo horário disponível...")

    from bot.models import ClientUser, Appointment
    from datetime import datetime
    from django.utils.timezone import now as timezone_now

    query = ClientUser.objects.filter(client=client_config, ativo=True)
    if unidade_id:
        query = query.filter(unidade_id=unidade_id)
    if profissional_nome:
        query = query.filter(nome__iexact=profissional_nome)

    profissional = query.first()
    if not profissional:
        print("❌ Profissional não encontrado.")
        return None

    if not data_desejada:
        data_desejada = timezone_now().date()

    horarios_possiveis = [
        datetime.combine(data_desejada, datetime.strptime(h, "%H:%M").time())
        for h in ["09:00", "10:00", "11:00", "14:00", "15:00", "16:00", "17:00"]
    ]

    agendamentos = Appointment.objects.filter(
        client_user=profissional,
        data_hora__date=data_desejada
    ).values_list('data_hora', flat=True)

    horarios_ocupados = [dt.replace(second=0, microsecond=0) for dt in agendamentos]
    agora = timezone_now()

    for horario in horarios_possiveis:
        if horario.replace(second=0, microsecond=0) not in horarios_ocupados and horario > agora:
            print(f"✅ Próximo horário disponível: {horario}")
            return horario

    print("❌ Nenhum horário disponível encontrado.")
    return None

# 🤖 Função tradicional para análise automática
def analisar_resposta_e_agendar(reply, phone, client_config):
    print("🤖 Analisando resposta para agendamento...")
    resposta_normalizada = reply.lower()

    # 1️⃣ Cancelamento explícito
    if any(p in resposta_normalizada for p in ["cancelar", "desmarcar", "remover", "quero cancelar", "desisti"]):
        pessoa = Person.objects.filter(telefone=phone, client=client_config).first()
        if pessoa:
            from .gessie_decisoes import gessie_cancelar_agendamento
            gessie_cancelar_agendamento(pessoa.nome, pessoa.telefone, client_config)
        return

    # 2️⃣ Agendamento só se a frase for bem clara
    gatilhos_confirmados = [
        "quero agendar", "marcar consulta", "agendar agora", "pode marcar",
        "sim, quero", "pode agendar", "quero marcar", "vamos agendar"
    ]
    if not any(g in resposta_normalizada for g in gatilhos_confirmados):
        print("🛑 Nenhuma intenção clara de agendamento detectada. Ignorando.")
        return

    pessoa, _ = Person.objects.get_or_create(
        telefone=phone,
        client=client_config,
        defaults={"nome": "Novo contato", "grau_interesse": "médio"}
    )

    profissional = ClientUser.objects.filter(client=client_config, ativo=True)
    if unidade_id:
        profissional = profissional.filter(unidade_id=unidade_id)
    profissional = profissional.first()

    data_hora = encontrar_proximo_horario_disponivel(profissional)
    if not data_hora or data_hora < timezone_now():
        print("⚠️ Nenhum horário disponível futuro encontrado.")
        return

    agendamento = Appointment.objects.create(
        client=client_config,
        person=pessoa,
        client_user=profissional,
        data_hora=data_hora,
        profissional=profissional.nome,
        confirmado=True
    )

    enviar_mensagem_whatsapp(profissional, pessoa, data_hora, client_config)
    print(f"✅ Agendamento criado para {data_hora.strftime('%d/%m/%Y %H:%M')}")
    # Envia para o profissional
    # Envia para o número da unidade (caso exista)
    if profissional.unidade and profissional.unidade.telefone:
        texto_unidade = (
            f"📋 Novo agendamento para a unidade *{profissional.unidade.nome}*:\n"
            f"👤 Paciente: {pessoa.nome}\n"
            f"🧑‍⚕️ Profissional: {profissional.nome}\n"
            f"🕒 Horário: {data_hora.strftime('%A, %d/%m às %H:%M')}"
        )

        payload = {
            "phone": profissional.unidade.telefone,
            "message": texto_unidade
        }
        headers = {
            "Content-Type": "application/json",
            "Client-Token": client_config.zapi_token
        }
        requests.post(client_config.zapi_url_text, json=payload, headers=headers)

        print(f"📲 Aviso enviado para unidade {profissional.unidade.nome} no número {profissional.unidade.telefone}")


# 🧠 Função para Function Calling
def gessie_agendar_consulta(
    nome: str,
    telefone: str,
    idade: int,
    tipo_atendimento: str,
    plano_saude: str,
    turno_preferido: str,
    data_preferida: str,
    profissional: str,
    client_config,
    unidade_id: int = None,
):
    print("📋 Iniciando agendamento via Function Calling...")
    try:
        pessoa, _ = Person.objects.get_or_create(
            telefone=telefone,
            defaults={"nome": nome, "client": client_config, "grau_interesse": "médio"}
        )

        tipo = tipo_atendimento.lower()
        plano = plano_saude.lower()
        planos_que_exigem = obter_regra(client_config, "encaminhamento_obrigatorio_planos", [])

        if plano != "particular" and plano in planos_que_exigem:
            registrar_mensagem(telefone, "⚠️ Encaminhamento médico e carteirinha obrigatórios para este plano.", "gessie", client_config)

        if "neuro" in tipo and obter_regra(client_config, "avaliacao_neuro_redirecionar", False):
            texto = (
                "🧠 Para esse tipo de atendimento via plano, preciso te encaminhar para uma de nossas atendentes. "
                "Entraremos em contato em breve!"
            )
            registrar_mensagem(telefone, texto, "gessie", client_config)
            return {"status": "encaminhado", "mensagem": texto}

        horarios_turno = {
            "manhã": ["09:00", "10:00", "11:00"],
            "tarde": ["14:00", "15:00", "16:00"],
            "noite": ["17:00", "18:00", "19:00"]
        }

        horarios_desejados = horarios_turno.get(turno_preferido.lower(), ["09:00", "10:00", "11:00", "14:00", "15:00", "16:00", "17:00"])

        try:
            data_obj = datetime.strptime(data_preferida, "%Y-%m-%d").date()
        except ValueError:
            return {"erro": "Formato de data inválido. Use YYYY-MM-DD."}

        # 🔍 Buscar profissional com filtro por unidade
        query = ClientUser.objects.filter(
            nome__iexact=profissional,
            client=client_config,
            ativo=True
        )
        if unidade_id:
            query = query.filter(unidade_id=unidade_id)

        profissional_obj = query.first()

        if not profissional_obj:
            return {"erro": f"Profissional '{profissional}' não encontrado ou inativo."}

        agendamentos = Appointment.objects.filter(
            client_user=profissional_obj,
            data_hora__date=data_obj
        ).values_list('data_hora', flat=True)

        horarios_ocupados = [dt.replace(second=0, microsecond=0) for dt in agendamentos]

        agora = timezone_now()
        horario_escolhido = None

        for h in horarios_desejados:
            dt = datetime.combine(data_obj, datetime.strptime(h, "%H:%M").time())
            if dt.replace(second=0, microsecond=0) not in horarios_ocupados and dt > agora:
                horario_escolhido = dt
                break

        if not horario_escolhido:
            return {"erro": f"Nenhum horário disponível para {profissional_obj.nome} nessa data e turno."}

        agendamento = Appointment.objects.create(
            client=client_config,
            person=pessoa,
            client_user=profissional_obj,
            data_hora=horario_escolhido,
            profissional=profissional_obj.nome,
            confirmado=True
        )

        enviar_mensagem_whatsapp(profissional_obj, pessoa, horario_escolhido, client_config)

        return {
            "status": "Agendado com sucesso",
            "data": horario_escolhido.strftime("%d/%m/%Y %H:%M"),
            "profissional": profissional_obj.nome
        }
        # Envia para o número da unidade (caso exista)
        if profissional.unidade and profissional.unidade.telefone:
            texto_unidade = (
                f"📋 Novo agendamento para a unidade *{profissional.unidade.nome}*:\n"
                f"👤 Paciente: {pessoa.nome}\n"
                f"🧑‍⚕️ Profissional: {profissional.nome}\n"
                f"🕒 Horário: {data_hora.strftime('%A, %d/%m às %H:%M')}"
            )

            payload = {
                "phone": profissional.unidade.telefone,
                "message": texto_unidade
            }
            headers = {
                "Content-Type": "application/json",
                "Client-Token": client_config.zapi_token
            }
            requests.post(client_config.zapi_url_text, json=payload, headers=headers)

            print(f"📲 Aviso enviado para unidade {profissional.unidade.nome} no número {profissional.unidade.telefone}")

    except Exception as e:
        print("❌ Erro ao agendar consulta:", e)
        return {"erro": "Erro interno ao tentar agendar a consulta."}

# 📋 Lista agendamentos futuros
def listar_agendamentos_futuros(pessoa):
    print("📋 Listando agendamentos futuros...")
    agendamentos = Appointment.objects.filter(
        person=pessoa,
        confirmado=True,
        data_hora__gte=timezone_now()
    ).order_by("data_hora")

    if not agendamentos.exists():
        return "❌ Você não possui agendamentos futuros registrados."

    linhas = [
        f"📅 {a.data_hora.strftime('%A, %d/%m às %H:%M')} com {a.profissional}"
        for a in agendamentos
    ]
    return "📋 *Seus próximos agendamentos:*\n" + "\n".join(linhas)

# 🔔 Decide se envia a lista de agendamentos
def verificar_e_enviar_agendamentos_futuros(resposta, phone, client_config):
    gatilhos = [
        "quais horários", "tenho marcado", "consultas marcadas",
        "meus agendamentos", "meus atendimentos", "meus horários",
        "agendado para mim", "o que tenho agendado"
    ]
    print("🔔 Verificando necessidade de listar agendamentos...")
    if any(g in resposta.lower() for g in gatilhos):
        pessoa = Person.objects.filter(telefone=phone, client=client_config).first()
        if pessoa:
            texto = listar_agendamentos_futuros(pessoa)
            payload = {"phone": phone, "message": texto}
            requests.post(client_config.zapi_url_text, headers={
                "Content-Type": "application/json",
                "Client-Token": client_config.zapi_token
            }, json=payload)
            registrar_mensagem(phone, texto, "gessie", client_config)
        return True
    return False

# ❌ Cancela agendamento
def gessie_cancelar_agendamento(nome, telefone, client_config):
    print("❌ Solicitando cancelamento de agendamento...")
    try:
        pessoa = Person.objects.filter(nome=nome, telefone=telefone, client=client_config).first()
        if not pessoa:
            return {"erro": "Pessoa não encontrada."}

        proximo = Appointment.objects.filter(
            person=pessoa,
            client=client_config,
            confirmado=True,
            data_hora__gte=timezone_now()
        ).order_by("data_hora").first()

        if not proximo:
            return {"erro": "Nenhum agendamento futuro encontrado."}

        horario = proximo.data_hora.strftime("%A, %d/%m às %H:%M")
        profissional = proximo.profissional

        proximo.delete()

        enviar_mensagem_whatsapp(
            pessoa, pessoa, timezone_now(), client_config,
            texto=f"Seu agendamento para {horario} com {profissional} foi cancelado com sucesso. Se precisar reagendar, é só me avisar!"
        )

        return {"status": "cancelado", "mensagem": f"Agendamento cancelado: {horario} com {profissional}"}

    except Exception as e:
        print("❌ Erro ao cancelar agendamento:", e)
        return {"erro": "Erro ao cancelar o agendamento."}
