from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
from bot.models import Conversation, ClientConfig, Person, Appointment, Message, ClientUser
import json, requests, openai, time, os, tempfile, subprocess, base64, threading
from .gessie_decisoes import analisar_resposta_e_agendar
from bot.utils import registrar_mensagem, obter_regra, verificar_e_enviar_agendamentos_futuros, enviar_audio_para_zapi_ou_wppapi
from bot.utils import listar_profissionais as listar_profissionais_detalhado, extrair_dia_e_turno_do_texto
from dotenv import load_dotenv
from pathlib import Path
from datetime import datetime
from pytz import timezone
from bot.api_condomob import consultar_boleto_condomob
import os
import locale
from django.utils.timezone import now
from bot.models import SilencioTemporario
from django.conf import settings

openai.api_key = settings.OPENAI_API_KEY

message_buffers = {}
buffer_lock = threading.Lock()
typing_status = {}

def listar_profissionais(client_config):
    profissionais = listar_profissionais_detalhado(client_config)
    return [p["nome"] for p in profissionais]

def process_buffered_message(phone):
    from bot.models import Person, ClientUser, Appointment, ClientConfig
    from .gessie_decisoes import analisar_resposta_e_agendar
    from bot.utils import (
        salvar_agendamento,
        enviar_mensagem_whatsapp,
        verificar_disponibilidade_consulta,
        listar_profissionais,
        is_professional,
        listar_compromissos_profissional,
        registrar_mensagem,
    )

    # Verifica se deve silenciar
    silenciado = SilencioTemporario.objects.filter(phone=phone, ate__gt=now()).exists()
    if silenciado:
        print(f"🔕 Gessie está silenciada para {phone}")
        return

    def formatar_data_em_portugues(data_iso):
        locale.setlocale(locale.LC_TIME, "pt_BR.UTF-8")
        data = datetime.fromisoformat(data_iso)
        return data.strftime("%A, %d de %B às %H:%M")

    with buffer_lock:
        entry = message_buffers.pop(phone, None)

    if not entry:
        return
    # Verificar se o cliente está ativo
    client_config = entry.get("client_config")
    if not client_config or not client_config.ativo:
        print(f"❌ Cliente conectado está inativo ou não encontrado. Apenas salvando mensagens.")
        combined_message = " ".join(entry["messages"]).strip()
        registrar_mensagem(phone, combined_message, "usuario", client_config)
        return

    thread_id = entry["thread_id"]
    is_audio = entry["is_audio"]
    combined_message = " ".join(entry["messages"]).strip()

    last_tool_call = entry.get("last_tool_call")
    if last_tool_call and any(k in combined_message.lower() for k in ["confirm", "sim", "pode agendar", "pode confirmar", "ok", "claro"]):
        if last_tool_call["name"] == "verificar_disponibilidade_consulta":
            args = last_tool_call["args"].copy()
            args["data_preferida"] = last_tool_call["data_confirmada"]

            # Corrigir telefone
            if not args.get("telefone"):
                args["telefone"] = phone

            # Se não tem turno informado, tenta puxar do texto
            if not args.get("turno_preferido"):
                from bot.utils import extrair_dia_e_turno_do_texto
                data_real, dia_semana, turno = extrair_dia_e_turno_do_texto(combined_message)
                if turno:
                    args["turno_preferido"] = turno

            print(f"✅ Args FINAL corrigido para salvar agendamento: {args}")

            agendamento = salvar_agendamento(args, client_config, phone)
            if agendamento:
                reply = (
                    f"✅ Agendamento confirmado com {agendamento.profissional} para "
                    f"{agendamento.data_hora.strftime('%A, %d/%m às %H:%M')}! Nos vemos na clínica 💙"
                )
            else:
                reply = "❌ Ocorreu um erro ao tentar confirmar o agendamento."

            registrar_mensagem(phone, reply, "gessie", client_config)
            payload = {"phone": phone, "message": reply}
            requests.post(client_config.zapi_url_text, headers={"Content-Type": "application/json", "Client-Token": client_config.zapi_token}, json=payload)
            return

    try:
        print("⏳ Verificando se há execução ativa em andamento...")
        runs = openai.beta.threads.runs.list(thread_id=thread_id)
        active_run = next((r for r in runs.data if r.status in ["queued", "in_progress"]), None)

        if active_run:
            print(f"⚠️ Run ativa detectada ({active_run.id}). Respondendo fallback...")
            fallback_reply = "⏳ Aguarde um momento enquanto verifico as informações. Já te respondo."
            registrar_mensagem(phone, fallback_reply, "gessie", client_config)
            payload = {
                "phone": phone,
                "message": fallback_reply
            }
            requests.post(
                client_config.zapi_url_text,
                headers={
                    "Content-Type": "application/json",
                    "Client-Token": client_config.zapi_token
                },
                json=payload
            )
            return  # ⚡️ Sai do process_buffered_message agora! Não precisa mais esperar!

        from pytz import timezone
        from datetime import datetime

        datenow = datetime.now(timezone("America/Maceio")).strftime("%d/%m/%Y às %H:%M")

        # Verifica se o thread é válido
        try:
            existing_messages = openai.beta.threads.messages.list(thread_id=thread_id).data
        except Exception as e:
            print(f"❌ Erro ao verificar mensagens do thread {thread_id}: {e}")
            return

        # Envia mensagem system com data/hora do atendimento se for o início
        if not existing_messages:
            try:
                openai.beta.threads.messages.create(
                    thread_id=thread_id,
                    role="user",
                    content=f"[contexto] Este atendimento foi iniciado em {datenow} (horário de Brasília)."
                )
                print(f"📌 Mensagem de início registrada no thread {thread_id}")
            except Exception as e:
                print(f"❌ Erro ao criar mensagem de início: {e}")
                return

        # Envia mensagem do usuário
        try:
            openai.beta.threads.messages.create(thread_id=thread_id, role="user", content=combined_message)
        except Exception as e:
            print(f"❌ Erro ao adicionar mensagem do usuário: {e}")
            return

        # Inicia a run
        try:
            run = openai.beta.threads.runs.create(thread_id=thread_id, assistant_id=client_config.assistant_id)
            print(f"💬 Nova run iniciada para {phone} em {datenow} | Thread: {thread_id}")
        except Exception as e:
            print(f"❌ Erro ao iniciar a run: {e}")
            return


        for _ in range(90):
            run_status = openai.beta.threads.runs.retrieve(thread_id=thread_id, run_id=run.id)
            if run_status.status in ["completed", "requires_action"]:
                print('run completa, chamar função')
                break
            time.sleep(1)
        else:
            return

        reply = "Desculpe, não consegui gerar uma resposta."

        if run_status.status == "requires_action":
            try:
                tool_calls = run_status.required_action.submit_tool_outputs.tool_calls
                tool_outputs = []

                for tool_call in tool_calls:
                    args = json.loads(tool_call.function.arguments)
                    result = {}

                    tipo = args.get("tipo_atendimento", "").lower()
                    plano = args.get("plano_saude", "").lower()

                    # APLICAR LÓGICA DE REDIRECIONAMENTO NEURO
                    if "neuro" in tipo and obter_regra(client_config, "avaliacao_neuro_redirecionar", False):
                        reply = (
                            "🧠 Para esse tipo de atendimento via plano, preciso te encaminhar para uma de nossas atendentes. "
                            "Em breve entraremos em contato com mais informações, tudo bem?"
                        )
                        registrar_mensagem(phone, reply, "gessie", client_config)
                        payload = {"phone": phone, "message": reply}
                        requests.post(client_config.zapi_url_text, headers={"Content-Type": "application/json", "Client-Token": client_config.zapi_token}, json=payload)
                        return

                    if tool_call.function.name == "verificar_disponibilidade_consulta":
                        result = verificar_disponibilidade_consulta(args, client_config)

                        if result.get("disponivel"):
                            # Importa no topo: from bot.utils import extrair_dia_e_turno_do_texto
                            dia_semana, turno = extrair_dia_e_turno_do_texto(combined_message)

                            entry["last_tool_call"] = {
                                "name": tool_call.function.name,
                                "args": {**args, "dia": dia_semana, "turno": turno},
                                "data_confirmada": result["data"]
                            }
                            message_buffers[phone] = entry  # ← Atualiza o buffer!

                            data_pt = formatar_data_em_portugues(result["data"])
                            reply = (
                                f"✅ Encontrei disponibilidade para {data_pt} com {result['profissional']}. "
                                "Posso confirmar o agendamento para você?"
                            )

                            planos_que_exigem = obter_regra(client_config, "encaminhamento_obrigatorio_planos", [])
                            if plano != "particular" and plano in planos_que_exigem:
                                reply += "\n📎 Para esse plano, será necessário o encaminhamento médico e a carteirinha."

                        else:
                            reply = "❌ Infelizmente, não encontrei vaga disponível nesse horário. Podemos tentar outro?"


                            # ENCAMINHAMENTO OBRIGATÓRIO
                            planos_que_exigem = obter_regra(client_config, "encaminhamento_obrigatorio_planos", [])
                            if plano != "particular" and plano in planos_que_exigem:
                                reply += "\n📎 Para esse plano, será necessário o encaminhamento médico e a carteirinha."
                   
                    elif tool_call.function.name == "consultar_boleto_condomob":
                        from bot.api_condomob import consultar_boleto_condomob

                        cpf = args.get("cpfCnpj")

                        if not cpf:
                            result = {"erro": "CPF não informado."}
                        else:
                            result_text = consultar_boleto_condomob(cpfCnpj=cpf, telefone=phone, client_config=client_config)
                            result = {"mensagem": result_text}

                        registrar_mensagem(phone, f"[FUNÇÃO]: {tool_call.function.name}\n{args}", "gessie", client_config)
                        print(phone, f"[FUNÇÃO]: {tool_call.function.name}\n{args}", "gessie", client_config)

                    elif tool_call.function.name == "func_listar_profissionais_com_disponibilidade":
                        from bot.utils import listar_profissionais
                        result = listar_profissionais(client_config, args.get("unidade_id"))

                    elif tool_call.function.name == "analisar_resposta_e_agendar":
                        from bot.gessie_decisoes import analisar_resposta_e_agendar

                        try:
                            print("📊 Chamando analisar_resposta_e_agendar com os seguintes dados:")
                            print(f"📞 Telefone: {args['telefone']}")
                            print(f"💬 Resposta: {args['resposta']}")

                            resultado = analisar_resposta_e_agendar(
                                resposta=args["resposta"],
                                telefone=args["telefone"],
                                client_config=client_config
                            )

                            result = {"status": "executado", "detalhes": resultado}

                        except Exception as e:
                            print(f"❌ Erro ao executar analisar_resposta_e_agendar: {e}")
                            result = {"status": "erro", "mensagem": str(e)}


                    elif tool_call.function.name == "listar_unidades_de_atendimento":
                        from bot.utils import listar_unidades_de_atendimento, formatar_lista_unidades
                        unidades = listar_unidades_de_atendimento(client_config)
                        texto = formatar_lista_unidades(unidades)
                        result = {"mensagem": texto}

                    elif tool_call.function.name == "gessie_agendar_consulta":
                        from bot.utils import avisar_profissional, enviar_mensagem_whatsapp
                        import locale

                        agendamento = salvar_agendamento(args, client_config, phone)
                        if agendamento:
                            # Envia mensagem para o paciente
                            enviar_mensagem_whatsapp(
                                client_user=agendamento.profissional,
                                person=agendamento.person,
                                data_hora=agendamento.data_hora,
                                client_config=client_config
                            )

                            # Avisa o profissional
                            avisar_profissional(
                                profissional_obj=agendamento.profissional,
                                data_hora=agendamento.data_hora,
                                pessoa_obj=agendamento.person,
                                client_config=client_config
                            )

                            # Define localidade para formato de data em português
                            try:
                                locale.setlocale(locale.LC_TIME, 'pt_BR.UTF-8')
                            except locale.Error:
                                locale.setlocale(locale.LC_TIME, '')  # fallback para o padrão do sistema

                            reply = (
                                f"✅ Agendamento confirmado com {agendamento.profissional.nome} para "
                                f"{agendamento.data_hora.strftime('%A, %d de %B às %H:%M')}."
                            )

                            # VALORES PARTICULARES
                            valores = obter_regra(client_config, "valores_particular", {})
                            if "casal" in tipo:
                                valor = valores.get("casal", {}).get("primeira", 300)
                                reply += f"\n💰 Valor da primeira sessão de casal: R$ {valor}"
                            elif "psico" in tipo:
                                valor = valores.get("psicoterapia", {}).get("primeira", 250)
                                reply += f"\n💰 Valor da primeira sessão: R$ {valor}"

                        else:
                            reply = "❌ Não foi possível confirmar o agendamento."

                    registrar_mensagem(phone, f"[FUNÇÃO]: {tool_call.function.name}\n{args}", "gessie", client_config)
                    print(phone, f"[FUNÇÃO]: {tool_call.function.name}\n{args}", "gessie", client_config)

                    tool_outputs.append({
                        "tool_call_id": tool_call.id,
                        "output": json.dumps(result)
                    })

                openai.beta.threads.runs.submit_tool_outputs(thread_id=thread_id, run_id=run.id, tool_outputs=tool_outputs)
                for _ in range(30):
                    updated_run = openai.beta.threads.runs.retrieve(thread_id=thread_id, run_id=run.id)
                    if updated_run.status == "completed":
                        print('run completa')
                        break
                    time.sleep(1)

            except Exception as e:
                print("❌ Erro ao processar função:", e)
                return

        try:
            messages = openai.beta.threads.messages.list(thread_id=thread_id)
            for msg in messages.data:
                if msg.role == "assistant" and msg.content:
                    reply = msg.content[0].text.value.strip()
                    break
        except Exception as e:
            print("❌ Erro ao buscar resposta:", e)

        if reply.lower().startswith("desculpe") and "não consegui" in reply.lower():
            if "profissionais" in combined_message.lower():
                nomes = listar_profissionais(client_config)
                reply = "Aqui estão os profissionais disponíveis na clínica: " + ", ".join(nomes)

        profissional = is_professional(phone, client_config)
        if profissional and any(p in combined_message.lower() for p in ["meus atendimentos", "meus compromissos", "meus agendamentos"]):
            reply = listar_compromissos_profissional(profissional, client_config)

        registrar_mensagem(phone, reply, "gessie", client_config)
        print(phone, reply, "gessie", client_config)

        if verificar_e_enviar_agendamentos_futuros(reply, phone, client_config):
            return

        analisar_resposta_e_agendar(reply, phone, client_config)

        try:
            if is_audio:
                speech_response = openai.audio.speech.create(model="tts-1-hd", voice="shimmer", input=reply)
                audio_bytes = speech_response.read()
                enviar_audio_para_zapi_ou_wppapi(audio_bytes, client_config, phone)
                registrar_mensagem(phone, "[ÁUDIO ENVIADO]", "gessie", client_config, tipo="áudio")
            else:
                payload = {"phone": phone, "message": reply}
                requests.post(client_config.zapi_url_text, headers={"Content-Type": "application/json", "Client-Token": client_config.zapi_token}, json=payload)
    
        except Exception as e:
            print("❌ Erro ao enviar mensagem:", e)

    except Exception as e:
        print("❌ Erro geral na process_buffered_message:", e)

@csrf_exempt
def identificar_autor(data):
    """
    Identifica quem enviou a mensagem:
    - "usuario" → se for o número conectado (fromMe)
    - "pessoa" → se for uma pessoa externa
    """
    if data.get("fromMe"):
        return "usuario"

    if data.get("isGroup"):
        participant = data.get("participantPhone")
        connected = data.get("connectedPhone")
        if participant and connected:
            # Verifica se a mensagem veio do próprio número no grupo
            if participant.endswith(connected):
                return "usuario"
            else:
                return "pessoa"
        else:
            return "pessoa"

    return "pessoa"

@csrf_exempt
def whatsapp_webhook(request):
    if request.method != "POST":
        return JsonResponse({"error": "Método não permitido"}, status=405)

    try:
        data = json.loads(request.body)
        print("📨 Payload recebido:", data)

        # Extrai e normaliza o número conectado
        connected_number = str(data.get("connectedPhone", "")).replace("+", "").strip()
        connected_number = ''.join(filter(str.isdigit, connected_number))
        client_config = ClientConfig.objects.filter(telefone__endswith=connected_number).first()

        if not client_config:
            print(f"❌ Nenhum ClientConfig encontrado para o número conectado: {connected_number}")
            return JsonResponse({"error": "ClientConfig não encontrado"}, status=400)

        # Extrai e normaliza o número de quem enviou a mensagem
        sender = str(data.get("phone", "")).replace("+", "").strip()
        sender = ''.join(filter(str.isdigit, sender))

        message_type = data.get("type")
        is_group = data.get("isGroup", False)
        is_audio = False

        # Trata presença (PAUSED, COMPOSING, AVAILABLE)
        if message_type == "PresenceChatCallback":
            status = data.get("status")
            with buffer_lock:
                typing_status[sender] = status
                if status in ["PAUSED", "AVAILABLE"] and sender in message_buffers:
                    print(f"⌛ Iniciando timer após pausa do usuário: {sender}")
                    if "timer" in message_buffers[sender]:
                        message_buffers[sender]["timer"].cancel()
                    timer = threading.Timer(5.0, process_buffered_message, args=(sender,))
                    message_buffers[sender]["timer"] = timer
                    timer.start()
            return JsonResponse({"status": "presence processado"})

        if message_type != "ReceivedCallback" or not sender:
            return JsonResponse({"status": "ignorado"})

        # 👤 Mensagens do próprio número conectado
        if data.get("fromMe"):
            message = data.get("text", {}).get("message")
            if message:
                registrar_mensagem(sender, message, "usuario", client_config)
                return JsonResponse({"status": "mensagem_salva fromMe"})
            return JsonResponse({"status": "ignorado fromMe"})

        # 👥 Mensagens de grupo
        if is_group:
            message = data.get("text", {}).get("message", "")
            participant = data.get("participantPhone")
            autor = participant or sender
            registrar_mensagem(sender, message, "pessoa", client_config)

            if "@gessie" not in message.lower():
                print("👥 Mensagem de grupo salva, mas Gessie não foi mencionada")
                return JsonResponse({"status": "grupo_salvo_sem_mencao"})
            print("👥 Gessie foi mencionada, seguindo com processamento")

        # 🎧 Áudio recebido
        elif "audio" in data:
            is_audio = True
            audio_url = data["audio"].get("audioUrl")
            if audio_url:
                response = requests.get(audio_url)
                with tempfile.NamedTemporaryFile(delete=False, suffix=".ogg") as temp_ogg:
                    temp_ogg.write(response.content)
                    temp_ogg_path = temp_ogg.name
                temp_wav_path = temp_ogg_path.replace(".ogg", ".wav")
                subprocess.run(["ffmpeg", "-i", temp_ogg_path, temp_wav_path], check=True)
                with open(temp_wav_path, "rb") as audio_file:
                    transcript = openai.audio.transcriptions.create(model="whisper-1", file=audio_file)
                    message = transcript.text
                    registrar_mensagem(sender, message, "pessoa", client_config, tipo="áudio")
                os.remove(temp_ogg_path)
                os.remove(temp_wav_path)
            else:
                message = "[Áudio não pôde ser processado]"

        # ✉️ Texto simples
        elif "text" in data and "message" in data["text"]:
            message = data["text"]["message"]
            registrar_mensagem(sender, message, "pessoa", client_config)

        else:
            return JsonResponse({"status": "ignorado (sem mensagem válida)"})

        # ❌ Cliente inativo: salva, mas não inicia run
        if not client_config.ativo:
            print(f"🚫 Cliente {connected_number} está inativo. Não será iniciado run.")
            return JsonResponse({"status": "mensagem salva sem run"})

        # 🧠 Gera ou reutiliza thread para o remetente
        thread_obj = Conversation.objects.filter(phone=sender).first()
        if thread_obj and thread_obj.thread_id:
            thread_id = thread_obj.thread_id
        else:
            thread = openai.beta.threads.create()
            thread_id = thread.id
            Conversation.objects.update_or_create(phone=sender, defaults={"thread_id": thread_id})

        # 🧠 Armazena a mensagem no buffer
        with buffer_lock:
            if sender not in message_buffers:
                message_buffers[sender] = {
                    "messages": [],
                    "is_audio": is_audio,
                    "thread_id": thread_id,
                    "client_config": client_config
                }

            message_buffers[sender]["messages"].append(message)

            if typing_status.get(sender) != "COMPOSING":
                if not SilencioTemporario.objects.filter(phone=sender, ate__gt=now()).exists():
                    if "timer" in message_buffers[sender]:
                        message_buffers[sender]["timer"].cancel()
                    timer = threading.Timer(5.0, process_buffered_message, args=(sender,))
                    message_buffers[sender]["timer"] = timer
                    timer.start()

        return JsonResponse({"status": "mensagem agrupada com sucesso"})

    except Exception as e:
        import traceback
        print("❌ Erro:", str(e))
        traceback.print_exc()
        return JsonResponse({"error": str(e)}, status=500)
