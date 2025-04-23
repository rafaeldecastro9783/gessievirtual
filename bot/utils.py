# utils.py

import requests
from django.conf import settings
from bot.models import Appointment, Person, Message, ClientConfig, Conversation, ClientUser
from datetime import datetime, timedelta
from django.utils.timezone import now
import pytz
from dateutil import parser  # Adicione isso no topo



def enviar_mensagem_whatsapp(usuario, pessoa, data_hora, client_config, texto=None):
    if not texto:
        texto = f"Olá {usuario.nome}, você tem um novo agendamento com {pessoa.nome} no dia {data_hora.strftime('%d/%m/%Y %H:%M')}."

    payload = {
        "phone": usuario.telefone,
        "message": texto
    }
    headers = {
        "Authorization": f"Bearer {client_config.zapi_token}",
        "Content-Type": "application/json"
    }
    requests.post(client_config.zapi_url_text, json=payload, headers=headers)

def avisar_profissional(profissional_nome, data_hora, pessoa_nome, client_config):
    try:
        from bot.models import ClientUser

        profissional = ClientUser.objects.filter(
            nome__iexact=profissional_nome,
            client=client_config,
            ativo=True
        ).first()

        if not profissional or not profissional.telefone:
            print(f"⚠️ Profissional '{profissional_nome}' não encontrado ou sem telefone.")
            return

        texto = f"📅 Novo agendamento com {pessoa_nome} confirmado para {data_hora.strftime('%A, %d/%m às %H:%M')}."
        payload = {
            "phone": profissional.telefone,
            "message": texto
        }
        headers = {
            "Authorization": f"Bearer {client_config.zapi_token}",
            "Content-Type": "application/json"
        }

        response = requests.post(client_config.zapi_url_text, json=payload, headers=headers)
        print("📨 Aviso enviado ao profissional:", response.status_code)

    except Exception as e:
        print("❌ Erro ao tentar avisar profissional:", e)



def salvar_agendamento(arguments, client_config, phone):
    try:
        print("⚙️ Tentando salvar agendamento no banco de dados...")

        nome = arguments.get("nome")
        idade = arguments.get("idade")
        nome_profissional = arguments.get("profissional")

        person = Person.objects.filter(telefone=phone, client=client_config).first()
        if not person:
            person = Person.objects.create(
                nome=nome,
                telefone=phone,
                idade=idade,
                client=client_config,
                ativo=True
            )
        else:
            if nome and person.nome != nome:
                person.nome = nome
                person.save()

        profissional_obj = ClientUser.objects.filter(
            nome__iexact=nome_profissional,
            client=client_config,
            ativo=True
        ).first()

        if not profissional_obj:
            return None

        dia_semana = arguments.get("dia", "").lower()
        dias_semana = {
            "segunda": 0, "terça": 1, "quarta": 2, "quinta": 3,
            "sexta": 4, "sábado": 5, "domingo": 6
        }
        hoje = datetime.now()
        target_weekday = dias_semana.get(dia_semana, hoje.weekday())
        dias_ate_lah = (target_weekday - hoje.weekday()) % 7
        data_agendada = hoje + timedelta(days=dias_ate_lah)

        horarios_disponiveis = obter_horarios_disponiveis_por_data(profissional_obj, data_agendada.date())
        if not horarios_disponiveis:
            return None

        data_hora = horarios_disponiveis[0]

        agendamento = Appointment.objects.create(
            client=client_config,
            person=person,
            profissional=profissional_obj.nome,
            client_user=profissional_obj,
            data_hora=data_hora,
            observacoes=f"Tipo: {arguments.get('tipo_atendimento')} | Plano: {arguments.get('plano_ou_particular')}",
            confirmado=True
        )

        enviar_mensagem_whatsapp(usuario=client_config, pessoa=person, data_hora=data_hora, client_config=client_config)
        from bot.utils import avisar_profissional
        avisar_profissional(profissional_nome=profissional_obj.nome, data_hora=data_hora, pessoa_nome=person.nome, client_config=client_config)

        return agendamento

    except Exception as e:
        print("❌ Erro ao salvar agendamento:", e)
        return None
    

def obter_horarios_disponiveis_por_data(profissional, data_desejada):
    from bot.models import Disponibilidade, Appointment

    dia_semana = calendar.day_name[data_desejada.weekday()].lower()
    mapeamento_dias = {
        'monday': 'segunda',
        'tuesday': 'terça',
        'wednesday': 'quarta',
        'thursday': 'quinta',
        'friday': 'sexta',
        'saturday': 'sábado',
        'sunday': 'domingo'
    }
    dia_pt = mapeamento_dias[dia_semana]

    disponibilidade = Disponibilidade.objects.filter(profissional=profissional, dia=dia_pt).first()
    if not disponibilidade:
        return []

    horarios_disponiveis = disponibilidade.horarios

    agendamentos = Appointment.objects.filter(
        client_user=profissional,
        data_hora__date=data_desejada
    ).values_list('data_hora', flat=True)
    horarios_ocupados = [dt.replace(second=0, microsecond=0).time() for dt in agendamentos]

    horarios_livres = []
    for h in horarios_disponiveis:
        dt = datetime.combine(data_desejada, datetime.strptime(h, "%H:%M").time())
        if dt.time() not in horarios_ocupados and dt > datetime.now():
            horarios_livres.append(dt)

    return horarios_livres



def verificar_disponibilidade_consulta(arguments, client_config):
    try:
        turno = arguments.get("turno", "").lower()
        dia_semana = arguments.get("dia", "").lower()
        profissional_nome = arguments.get("profissional")

        profissional_obj = ClientUser.objects.filter(
            nome__iexact=profissional_nome,
            client=client_config,
            ativo=True
        ).first()

        if not profissional_obj:
            return {
                "disponivel": False,
                "erro": f"Profissional '{profissional_nome}' não encontrado"
            }

        dias_semana = {
            "segunda": 0, "terça": 1, "quarta": 2, "quinta": 3,
            "sexta": 4, "sábado": 5, "domingo": 6
        }
        hoje = datetime.now(pytz.timezone("America/Sao_Paulo"))
        target_weekday = dias_semana.get(dia_semana, hoje.weekday())
        dias_ate_lah = (target_weekday - hoje.weekday()) % 7
        data_agendada = hoje + timedelta(days=dias_ate_lah)

        horarios_disponiveis = obter_horarios_disponiveis_por_data(profissional_obj, data_agendada.date())
        if not horarios_disponiveis:
            return {
                "disponivel": False,
                "erro": "Sem horários disponíveis para esta data"
            }

        return {
            "disponivel": True,
            "data": horarios_disponiveis[0].isoformat(),
            "profissional": profissional_nome
        }

    except Exception as e:
        return {
            "disponivel": False,
            "erro": str(e)
        }


def is_professional(phone, client_config):
    from bot.models import ClientUser
    return ClientUser.objects.filter(telefone=phone, client=client_config).first()

def listar_compromissos_profissional(profissional, client_config):
    from bot.models import Appointment
    from datetime import datetime
    agendamentos = Appointment.objects.filter(
        client_user=profissional,
        client=client_config,
        data_hora__gte=datetime.now()
    ).order_by("data_hora")

    if not agendamentos.exists():
        return "📭 Nenhum compromisso agendado."

    texto = "📅 Seus próximos compromissos:\n"
    for a in agendamentos:
        texto += f"• {a.data_hora.strftime('%A, %d/%m %H:%M')} com {a.person.nome}\n"
    return texto


def listar_profissionais(client_config):
    """
    Lista os profissionais ativos e suas especialidades.
    Exemplo de retorno:
    [
        {"nome": "Alessandra Remígio", "especialidades": ["Psicoterapia", "TCC"]},
        {"nome": "Neumar Félix", "especialidades": ["Neuropsicologia"]}
    ]
    """
    from bot.models import ClientUser

    profissionais = ClientUser.objects.filter(client=client_config, ativo=True).prefetch_related("especialidades")

    return [
        {
            "nome": p.nome,
            "especialidades": [e.nome for e in p.especialidades.all()]
        }
        for p in profissionais
    ]
def formatar_lista_profissionais(profissionais):
    """
    Recebe a lista detalhada e devolve uma string pronta pro WhatsApp.
    """
    linhas = ["👩‍⚕️ Profissionais disponíveis:"]
    for i, p in enumerate(profissionais, 1):
        especialidades = ", ".join(p["especialidades"])
        linhas.append(f"{i}. {p['nome']} – {especialidades}")
    return "\n".join(linhas)


def registrar_mensagem(phone, mensagem, enviado_por, client_config, tipo="texto"):
    from bot.models import Person, Conversation, ClientUser, Message

    try:
        # Garante ou cria Person com base no telefone
        person, _ = Person.objects.get_or_create(
            telefone=phone,
            client=client_config,
            defaults={"nome": phone, "idade": "0"}
        )

        # Garante ou cria Conversation associada ao telefone
        conversation, _ = Conversation.objects.get_or_create(phone=phone)

        # Identifica ClientUser apenas se for mensagem do usuário do sistema
        client_user = None
        if enviado_por in ["gessie", "usuario"]:
            client_user = ClientUser.objects.filter(client=client_config).first()

        # Define quem está enviando (Gessie, ou número da pessoa)
        enviado_por_valor = enviado_por if enviado_por in ["gessie", "usuario"] else phone

        # Cria a mensagem no banco
        Message.objects.create(
            conversation=conversation,
            person=person,
            client_user=client_user if enviado_por == "usuario" else None,
            enviado_por=enviado_por_valor,
            mensagem=mensagem,
            tipo=tipo
        )

        # Tenta atualizar o nome automaticamente caso seja possível deduzir
        if enviado_por_valor == phone and person.nome == phone:
            msg_lower = mensagem.lower()
            if msg_lower.startswith("me chamo ") or msg_lower.startswith("sou "):
                nome_extraido = mensagem.replace("me chamo", "").replace("sou", "").strip().split(" ")[0]
                if nome_extraido.isalpha():
                    person.nome = nome_extraido.capitalize()
                    person.save()

    except Exception as e:
        print("⚠️ Erro ao registrar mensagem:", e)


def listar_agendamentos_futuros(person):
    agendamentos = Appointment.objects.filter(
        person=person,
        confirmado=True,
        data_hora__gte=now()
    ).order_by("data_hora")

    if not agendamentos.exists():
        return "Você não possui agendamentos futuros registrados."

    linhas = [
        f"📅 {a.data_hora.strftime('%A, %d/%m às %H:%M')} com {a.profissional}"
        for a in agendamentos
    ]

    return "Seus próximos agendamentos são:\n" + "\n".join(linhas)

def verificar_e_enviar_agendamentos_futuros(reply_text, phone, client_config):
    """
    Envia ao usuário os agendamentos futuros se for detectado interesse na resposta do assistant.
    """
    gatilhos = [
        "meus agendamentos",
        "meus compromissos",
        "tenho algo agendado",
        "próximos horários",
        "o que tenho marcado",
    ]

    if any(gatilho in reply_text.lower() for gatilho in gatilhos):
        try:
            person = Person.objects.filter(telefone=phone, client=client_config).first()
            if not person:
                print("⚠️ Pessoa não encontrada ao tentar listar agendamentos futuros.")
                return False

            mensagem = listar_agendamentos_futuros(person)

            payload = {
                "phone": phone,
                "message": mensagem,
            }

            headers = {
                "Content-Type": "application/json",
                "Client-Token": client_config.zapi_token,
            }

            requests.post(client_config.zapi_url_text, json=payload, headers=headers)
            registrar_mensagem(phone, mensagem, "gessie", client_config)

            return True

        except Exception as e:
            print("❌ Erro ao enviar agendamentos futuros:", e)

    return False

def formatar_data_em_portugues(data_iso):
    """
    Recebe uma string no formato ISO (ex: '2025-04-23T19:00:00')
    e retorna uma frase formatada em português com nome do dia e hora.
    Ex: 'quarta-feira, 23/04 às 19:00'
    """
    import locale
    from datetime import datetime

    try:
        locale.setlocale(locale.LC_TIME, 'pt_BR.UTF-8')
    except:
        locale.setlocale(locale.LC_TIME, 'pt_BR')

    data_obj = datetime.fromisoformat(data_iso)
    dia_semana = data_obj.strftime('%A')
    dia_formatado = data_obj.strftime('%d/%m')
    hora_formatada = data_obj.strftime('%H:%M')

    return f"{dia_semana}, {dia_formatado} às {hora_formatada}"

def obter_regra(client_config, chave, default=None):
    """
    Retorna o valor de uma regra personalizada do cliente,
    acessando de forma segura o campo `regras_json`.

    Exemplo:
        obter_regra(client_config, "encaminhamento_obrigatorio_planos", [])
    """
    try:
        regras = client_config.regras_json or {}
        return regras.get(chave, default)
    except Exception as e:
        print(f"⚠️ Erro ao obter regra '{chave}':", e)
        return default
