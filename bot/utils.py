# utils.py
import requests
import os
from django.conf import settings
from bot.models import Appointment, Person, Message, ClientConfig, Conversation, ClientUser, Disponibilidade
from datetime import datetime, timedelta
from django.utils.timezone import now
import pytz, calendar
from dateutil import parser  # Adicione isso no topo
import unicodedata
import re
import tempfile

def enviar_audio_para_zapi_ou_wppapi(audio_bytes, client_config, phone):
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".ogg") as tmp:
            tmp.write(audio_bytes)
            tmp_path = tmp.name

        with open(tmp_path, "rb") as f:
            files = {'file': ('resposta.ogg', f, 'audio/ogg')}
            data = {'phone': phone}
            response = requests.post(
                client_config.zapi_url_audio,
                headers={"Client-Token": client_config.zapi_token},
                files=files,
                data=data
            )

        print(f"📤 Envio do áudio finalizado: {response.status_code} - {response.text}")

    except Exception as e:
        print("❌ Erro ao enviar áudio para API:", e)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

def normalizar_nome(nome):
    return ''.join(c for c in unicodedata.normalize('NFD', nome) if unicodedata.category(c) != 'Mn').lower()

def buscar_profissional(nome_profissional, client_config):
    from bot.models import ClientUser

    profissionais = ClientUser.objects.filter(client=client_config, ativo=True)

    nome_normalizado = normalizar_nome(nome_profissional)

    for p in profissionais:
        if normalizar_nome(p.nome) == nome_normalizado:
            return p

    return None


def extrair_dia_e_turno_do_texto(texto):
    """
    Extrai data futura (nunca passada), turno ou horário a partir do texto do usuário.
    """
    texto = texto.lower()
    hoje = datetime.now(pytz.timezone('America/Sao_Paulo')).date()

    dias_semana = {
        "segunda": 0, "terça": 1, "terca": 1, "quarta": 2,
        "quinta": 3, "sexta": 4, "sábado": 5, "sabado": 5, "domingo": 6
    }
    turnos = {
        "manhã": "manhã", "manha": "manhã",
        "tarde": "tarde",
        "noite": "noite",
        "integral": "integral"
    }

    dia_semana_nome = None
    data_real = None
    turno_encontrado = ""

    # 1️⃣ Amanhã / Depois de Amanhã
    if "depois de amanhã" in texto:
        data_real = hoje + timedelta(days=2)
    elif "amanhã" in texto:
        data_real = hoje + timedelta(days=1)
    else:
        # 2️⃣ Dia da semana explícito
        for nome, numero in dias_semana.items():
            if nome in texto:
                hoje_numero = hoje.weekday()
                dias_ate = (numero - hoje_numero + 7) % 7
                dias_ate = dias_ate or 7  # Se hoje for o mesmo dia, pula pra semana seguinte
                data_real = hoje + timedelta(days=dias_ate)
                dia_semana_nome = nome
                break

    # 3️⃣ Procurar horário explícito (tipo "10:40" ou "10h40")
    padrao_horario = r'(\d{1,2}[:h]\d{2})'
    horario_match = re.search(padrao_horario, texto)
    if horario_match:
        horario_bruto = horario_match.group(1).replace('h', ':')
        turno_encontrado = horario_bruto  # Prioriza horário exato

    # 4️⃣ Procurar turno (manhã, tarde, noite)
    if not turno_encontrado:
        for palavra, turno in turnos.items():
            if palavra in texto:
                turno_encontrado = turno
                break

    # 5️⃣ Falha: se não achou nada
    if not data_real:
        return None, None, None

    return data_real, dia_semana_nome, turno_encontrado

def calcular_proxima_data_semana(dia_semana_str):
    dias_semana = {
        "segunda": 0, "terça": 1, "terca": 1, "quarta": 2,
        "quinta": 3, "sexta": 4, "sábado": 5, "sabado": 5, "domingo": 6
    }
    hoje = datetime.now(pytz.timezone('America/Sao_Paulo')).date()
    target_weekday = dias_semana.get(dia_semana_str.lower())

    if target_weekday is None:
        return None

    dias_ate_lah = (target_weekday - hoje.weekday() + 7) % 7
    dias_ate_lah = dias_ate_lah if dias_ate_lah != 0 else 7  # Se for hoje, pula pra próxima semana
    data_futura = hoje + timedelta(days=dias_ate_lah)
    return data_futura

def salvar_agendamento(arguments, client_config, phone):
    from bot.models import ClientUser, Disponibilidade, Appointment, Person
    from datetime import datetime, timedelta
    import pytz
    import unicodedata

    try:
        print("⚙️ Tentando salvar agendamento no banco de dados...")

        nome = arguments.get("nome")
        idade = arguments.get("idade")
        nome_profissional = arguments.get("profissional")
        turno_preferido = arguments.get("turno_preferido", "")
        data_preferida = arguments.get("data_preferida", None)
        unidade_id = arguments.get("unidade_id")  # NOVO

        print(f"Dados recebidos: nome={nome}, idade={idade}, profissional={nome_profissional}, data_preferida={data_preferida}, turno={turno_preferido}, unidade_id={unidade_id}")

        if not data_preferida:
            print("❌ Data preferida não fornecida.")
            return None

        if isinstance(data_preferida, str):
            try:
                data_agendada = datetime.fromisoformat(data_preferida).date()
            except Exception as e:
                print(f"❌ Erro ao converter data_preferida: {e}")
                return None
        else:
            data_agendada = data_preferida

        hoje = datetime.now(pytz.timezone('America/Sao_Paulo')).date()
        if data_agendada < hoje:
            print(f"⚠️ Data preferida estava no passado ({data_agendada}), ajustando para próxima semana...")
            dias_ate = (data_agendada.weekday() - hoje.weekday()) % 7
            if dias_ate == 0:
                dias_ate = 7
            data_agendada = hoje + timedelta(days=dias_ate)

        print(f"📅 Data real para agendamento: {data_agendada}")

        person = Person.objects.filter(telefone=phone, client=client_config).first()
        if not person:
            print(f"Pessoa nova: {phone}")
            person = Person.objects.create(nome=nome, telefone=phone, idade=idade, client=client_config, ativo=True)
        else:
            if nome and person.nome != nome:
                print(f"Atualizando nome da pessoa de {person.nome} para {nome}")
                person.nome = nome
                person.save()

        # Procurar profissional
        def normalizar(texto):
            return unicodedata.normalize('NFKD', texto).encode('ASCII', 'ignore').decode('utf-8').casefold()

        profissionais = ClientUser.objects.filter(client=client_config, ativo=True)
        if unidade_id:
            profissionais = profissionais.filter(unidade_id=unidade_id)  # NOVO

        profissional_obj = None
        for p in profissionais:
            if normalizar(p.nome) == normalizar(nome_profissional):
                profissional_obj = p
                break

        if not profissional_obj:
            print(f"❌ Profissional '{nome_profissional}' não encontrado.")
            return None

        print(f"Profissional encontrado: {profissional_obj.nome}")

        from bot.utils import obter_horarios_disponiveis_por_data
        horarios_disponiveis = obter_horarios_disponiveis_por_data(profissional_obj, data_agendada)

        if not horarios_disponiveis:
            print("❌ Nenhum horário disponível para esta data.")
            return None

        print(f"Horários disponíveis: {[h.strftime('%H:%M') for h in horarios_disponiveis]}")

        data_hora_agendamento = None
        if turno_preferido:
            try:
                horario_desejado_dt = datetime.strptime(turno_preferido, "%H:%M").time()
                for h in horarios_disponiveis:
                    if h.time() == horario_desejado_dt:
                        data_hora_agendamento = h
                        break
            except ValueError:
                if "manhã" in turno_preferido:
                    horarios_manha = [h for h in horarios_disponiveis if 6 <= h.time().hour <= 11]
                    if horarios_manha:
                        data_hora_agendamento = horarios_manha[0]
                elif "tarde" in turno_preferido:
                    horarios_tarde = [h for h in horarios_disponiveis if 12 <= h.time().hour <= 17]
                    if horarios_tarde:
                        data_hora_agendamento = horarios_tarde[0]
                elif "noite" in turno_preferido:
                    horarios_noite = [h for h in horarios_disponiveis if 18 <= h.time().hour <= 22]
                    if horarios_noite:
                        data_hora_agendamento = horarios_noite[0]

        if not data_hora_agendamento:
            data_hora_agendamento = horarios_disponiveis[0]

        # 🔐 VERIFICA SE HORÁRIO AINDA É VÁLIDO NO MESMO DIA
        agora = datetime.now(pytz.timezone('America/Sao_Paulo'))
        if data_hora_agendamento <= agora:
            print("⚠️ Horário sugerido já passou. Buscando outro disponível...")
            futuros = [h for h in horarios_disponiveis if h > agora]
            if not futuros:
                print("❌ Nenhum horário futuro disponível.")
                return None
            data_hora_agendamento = futuros[0]

        print(f"🕒 Agendamento marcado para: {data_hora_agendamento}")

        observacoes = f"Tipo: {arguments.get('tipo_atendimento')} | Plano: {arguments.get('plano_saude')}"

        agendamento = Appointment.objects.create(
            client=client_config,
            person=person,
            client_user=profissional_obj,
            profissional=profissional_obj,
            data_hora=data_hora_agendamento,
            observacoes=observacoes,
            confirmado=True,
        )

        from bot.utils import enviar_mensagem_whatsapp, avisar_profissional
        if client_config and client_config.zapi_token and client_config.zapi_url_text:
            enviar_mensagem_whatsapp(profissional=profissional_obj, person=person, data_hora=data_hora_agendamento, client_config=client_config)
            avisar_profissional(profissional_nome=profissional_obj.nome, data_hora=data_hora_agendamento, pessoa_nome=person.nome, client_config=client_config)

        if profissional_obj.unidades.exists():
            unidade = profissional_obj.unidades.first()
            if unidade.telefone:
                texto_unidade = (
                    f"📋 Novo agendamento para a unidade *{unidade.nome}*:\n"
                    f"👤 Paciente: {person.nome}\n"
                    f"🧑‍⚕️ Profissional: {profissional_obj.nome}\n"
                    f"🕒 Horário: {data_hora_agendamento.strftime('%A, %d/%m às %H:%M')}"
                )

                payload = {
                    "phone": unidade.telefone,
                    "message": texto_unidade
                }
                headers = {
                    "Content-Type": "application/json",
                    "Client-Token": client_config.zapi_token
                }
                requests.post(client_config.zapi_url_text, json=payload, headers=headers)

                print(f"📲 Aviso enviado para unidade {unidade.nome} no número {unidade.telefone}")

        print("✅ Agendamento salvo com sucesso!")
        return agendamento

    except Exception as e:
        print("❌ Erro ao salvar agendamento:", e)
        return None

def obter_horarios_disponiveis_por_data(profissional, data_desejada):
    from bot.models import Disponibilidade, Appointment
    from django.utils.timezone import make_aware, is_naive
    from datetime import datetime
    import pytz
    import calendar

    print('Entrou na função obter_horarios_disponiveis_por_data')

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

    disponibilidade = Disponibilidade.objects.filter(profissional=profissional, dia_semana=dia_pt).first()
    if not disponibilidade:
        print('⚠️ Nenhuma disponibilidade cadastrada para esse dia.')
        return []

    if not disponibilidade.horarios:
        print("⚠️ Lista de horários vazia para o profissional.")
        return []

    horarios_disponiveis = disponibilidade.horarios

    # Buscar agendamentos ocupados
    agendamentos = Appointment.objects.filter(
        client_user=profissional,
        data_hora__date=data_desejada
    ).values_list('data_hora', flat=True)

    horarios_ocupados = [dt.replace(second=0, microsecond=0).time() for dt in agendamentos]

    # Listar apenas horários livres
    horarios_livres = []
    agora = make_aware(datetime.now(), pytz.timezone("America/Sao_Paulo"))
    print(f"Horários disponíveis para {profissional.nome} no dia {data_desejada}: {horarios_disponiveis}")

    for h in horarios_disponiveis:
        dt_naive = datetime.combine(data_desejada, datetime.strptime(h, "%H:%M").time())
        dt = make_aware(dt_naive, pytz.timezone("America/Sao_Paulo")) if is_naive(dt_naive) else dt_naive

        if dt.time() not in horarios_ocupados and (dt > agora or data_desejada > agora.date()):
            horarios_livres.append(dt)


    return sorted(horarios_livres)

def verificar_disponibilidade_consulta(arguments, client_config, unidade_id=None):
    from bot.models import ClientUser, Disponibilidade, UnidadeDeAtendimento
    from datetime import datetime, timedelta
    from django.utils.timezone import make_aware, is_naive
    from datetime import datetime
    import pytz

    print('Entrou na função verificar_disponibilidade_consulta')

    try:
        unidades = arguments.get("unidade_id")
        turno = arguments.get("turno", "").lower()
        dia_semana = arguments.get("dia", "").lower()
        profissional_nome = arguments.get("profissional")

        profissional_obj = ClientUser.objects.filter(
            nome__iexact=profissional_nome,
            client=client_config,
            ativo=True
        )

        if unidade_id:
            profissional_obj = profissional_obj.filter(unidade_id=unidade_id)

        profissional_obj = profissional_obj.first()


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

        # 🎯 Filtrar por turno se possível
        horarios_turno = {
            "manhã": ["06:00", "07:00", "08:00", "09:00", "10:00", "11:00", "12:00"],
            "tarde": ["13:00", "14:00", "15:00", "16:00", "17:00"],
            "noite": ["18:00", "19:00", "20:00", "21:00"]
        }

        horarios_turno_desejado = horarios_turno.get(turno, [])
        horarios_filtrados = [h for h in horarios_disponiveis if h.strftime("%H:%M") in horarios_turno_desejado]

        if horarios_filtrados:
            horario_final = horarios_filtrados[0]
        else:
            # ⚡ Se não encontrar no turno, pegar o primeiro horário livre do dia
            horario_final = horarios_disponiveis[0]

        return {
            "disponivel": True,
            "data": horario_final.isoformat(),
            "profissional": profissional_nome
        }

    except Exception as e:
        print(f"❌ Erro em verificar_disponibilidade_consulta: {e}")
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
    print('entrou na função istar_compromissos_profissional')
    if not agendamentos.exists():
        return "📭 Nenhum compromisso agendado."

    texto = "📅 Seus próximos compromissos:\n"
    for a in agendamentos:
        texto += f"• {a.data_hora.strftime('%A, %d/%m %H:%M')} com {a.person.nome}\n"
    return texto


def listar_profissionais(client_config, unidade_id=None):
    from bot.models import ClientUser

    profissionais = ClientUser.objects.filter(client=client_config, ativo=True)
    if unidade_id:
        profissionais = profissionais.filter(unidades__id=unidade_id)

    return [
        {
            "nome": p.nome,
            "especialidades": [e.nome for e in p.especialidades.all()],
            "unidades": [u.nome for u in p.unidades.all()],
            "disponibilidade": [
                {
                    "dia": d.dia_semana,
                    "horarios": d.horarios
                } for d in p.disponibilidades.all()
            ]
        }
        for p in profissionais
    ]

def formatar_lista_profissionais(profissionais):
    """
    Formata a lista com nome, especialidades, unidades e disponibilidade.
    """
    linhas = ["👩‍⚕️ Profissionais disponíveis:"]
    for i, p in enumerate(profissionais, 1):
        especialidades = ", ".join(p["especialidades"]) or "Nenhuma"
        unidades = ", ".join(p["unidades"]) or "Não vinculado a nenhuma unidade"
        
        if p["disponibilidade"]:
            disponibilidade_formatada = "\n    ".join(
                f"{d['dia'].capitalize()}: {', '.join(d['horarios']) if d['horarios'] else 'Nenhum horário'}"
                for d in p["disponibilidade"]
            )
        else:
            disponibilidade_formatada = "Sem horários cadastrados"

        linhas.append(
            f"{i}. {p['nome']}\n"
            f"   🏥 Unidades: {unidades}\n"
            f"   💼 Especialidades: {especialidades}\n"
            f"   🕒 Disponibilidade:\n    {disponibilidade_formatada}"
        )
    return "\n\n".join(linhas)

def registrar_mensagem(phone, mensagem, enviado_por, client_config, tipo="texto"):
    from bot.models import Person, Conversation, ClientUser, Message, User
    from django.utils.timezone import now

    print('📥 Entrou na função registrar_mensagem')

    try:
        client_user = None
        conversation = None

        if enviado_por == "usuario" and phone == client_config.telefone:
            print("📨 Mensagem enviada pelo número conectado (fromMe)")

            last_conversa = Conversation.objects.filter(client=client_config).order_by('-updated_at').first()
            if not last_conversa:
                print("⚠️ Nenhuma conversa encontrada para identificar destinatário")
                return

            phone_destino = last_conversa.phone

            person, _ = Person.objects.get_or_create(
                telefone=phone_destino,
                client=client_config,
                defaults={"nome": phone_destino, "idade": "0"}
            )
            conversation, _ = Conversation.objects.get_or_create(
                phone=phone_destino,
                client=client_config
            )

            client_user = ClientUser.objects.filter(telefone=phone, client=client_config).first()
            if not client_user:
                user, _ = User.objects.get_or_create(
                    username=f"sistema_{client_config.id}",
                    defaults={
                        "password": "senha_segura123",
                        "first_name": "Sistema"
                    }
                )

                client_user, _ = ClientUser.objects.get_or_create(
                    user=user,
                    defaults={
                        "client": client_config,
                        "nome": "Sistema",
                        "telefone": phone,
                        "email": f"sistema_{client_config.id}@softdotpro.com"
                    }
                )
        else:
            # Mensagem recebida ou enviada para uma pessoa externa
            person, _ = Person.objects.get_or_create(
                telefone=phone,
                client=client_config,
                defaults={"nome": phone, "idade": "0"}
            )
            conversation, _ = Conversation.objects.get_or_create(
                phone=phone,
                client=client_config
            )

        Message.objects.create(
            conversation=conversation,
            person=person,
            enviado_por=enviado_por,
            mensagem=mensagem,
            client_user=client_user,
            tipo=tipo,
            data=now()
        )

        # Atualiza nome da pessoa se mensagem começar com "me chamo" ou "sou"
        if enviado_por == "pessoa" and person.nome == person.telefone:
            msg_lower = mensagem.lower()
            if msg_lower.startswith("me chamo ") or msg_lower.startswith("sou "):
                nome_extraido = mensagem.split(" ", 2)[-1].strip().split(" ")[0]
                if nome_extraido.isalpha():
                    person.nome = nome_extraido.capitalize()
                    person.save()

    except Exception as e:
        print("⚠️ Erro ao registrar mensagem:", e)


def listar_agendamentos_futuros(person):
    print('Listando agendamentos futuros...')
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
    print('Encontrando agendamentos futuros do cliente...')
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

def enviar_mensagem_whatsapp(profissional, person, data_hora, client_config, texto=None):
    print('Entrou na função enviar_mensagem_whatsapp')
    if not person.telefone:
        print("⚠️ Número de telefone do usuário não encontrado!")
        return
    if not texto:
        texto = f"Olá {person.telefone}, você tem um novo agendamento com {profissional.nome} no dia {data_hora.strftime('%d/%m/%Y %H:%M')}."

    payload = {
        "phone": person.telefone,
        "message": texto
    }
    headers={"Content-Type": "application/json", "Client-Token": client_config.zapi_token}
    response=requests.post(client_config.zapi_url_text, json=payload, headers=headers)
    if response.status_code != 200:
        print(f"⚠️ Falha ao enviar mensagem WhatsApp: {response.status_code} | {response.text}")
    else:
        print("✅ Mensagem enviada com sucesso via WhatsApp!")
        registrar_mensagem(
            phone = person.telefone,
            mensagem = texto, 
            enviado_por = 'gessie', 
            client_config = client_config, 
            tipo="texto")

def avisar_profissional(profissional_nome, data_hora, pessoa_nome, client_config):
    from bot.models import ClientUser
    import requests
    import unicodedata

    try:
        print("🚀 Entrou na função avisar_profissional")

        def normalizar(texto):
            return unicodedata.normalize('NFKD', texto).encode('ASCII', 'ignore').decode('utf-8').casefold()

        profissionais = ClientUser.objects.filter(client=client_config, ativo=True)
        profissional = None

        for p in profissionais:
            if normalizar(p.nome) == normalizar(profissional_nome):
                profissional = p
                break

        if not profissional or not profissional.telefone:
            print(f"⚠️ Profissional '{profissional_nome}' encontrado mas sem telefone válido.")
            return

        texto = (
            f"📅 *Novo agendamento confirmado!*\n\n"
            f"👤 Cliente: {pessoa_nome}\n"
            f"🗓️ Data: {data_hora.strftime('%A, %d/%m às %H:%M')}\n\n"
            "✅ Por favor, se organize para receber o atendimento."
        )

        payload = {"phone": profissional.telefone, "message": texto}
        headers={"Content-Type": "application/json", "Client-Token": client_config.zapi_token}
        print(f"🔔 Enviando aviso para {profissional.nome} ({profissional.telefone})...")
        response = requests.post(client_config.zapi_url_text, json=payload, headers=headers)

        if response.status_code == 200:
            print("✅ Aviso enviado com sucesso!")
        else:
            print(f"⚠️ Erro ao enviar aviso! Código: {response.status_code} | Resposta: {response.text}")

    except Exception as e:
        print("❌ Erro em avisar_profissional:", e)


def listar_unidades_de_atendimento(client_config):
    """
    Lista as unidades de atendimento do cliente com dados completos.
    Exemplo de retorno:
    [
        {
            "nome": "Clínica Central",
            "endereco": "Rua X, 123 - Centro",
            "telefone": "(11) 99999-0000",
            "email": "contato@clinica.com",
            "cnpj": "00.000.000/0001-00"
        },
        ...
    ]
    """
    from bot.models import UnidadeDeAtendimento

    unidades = UnidadeDeAtendimento.objects.filter(client=client_config)

    return [
        {
            "nome": u.nome,
            "endereco": u.endereco,
            "telefone": u.telefone or "Não informado",
            "email": u.email or "Não informado",
            "cnpj": u.cnpj or "Não informado"
        }
        for u in unidades
    ]

def formatar_lista_unidades(unidades):
    """
    Formata a lista de unidades para envio via WhatsApp.
    """
    linhas = ["🏥 Unidades de Atendimento:"]
    for i, u in enumerate(unidades, 1):
        linhas.append(
            f"{i}. {u['nome']}\n"
            f"   📍 Endereço: {u['endereco']}\n"
            f"   ☎️ Telefone: {u['telefone']}\n"
            f"   ✉️ E-mail: {u['email']}\n"
            f"   🧾 CNPJ: {u['cnpj']}"
        )
    return "\n\n".join(linhas)
