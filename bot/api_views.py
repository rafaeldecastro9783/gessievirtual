from rest_framework import viewsets, status, generics
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError
from rest_framework.decorators import api_view, permission_classes, action
from rest_framework.views import APIView
from rest_framework.generics import ListAPIView
from .models import Disponibilidade
from rest_framework.filters import OrderingFilter
from django_filters.rest_framework import DjangoFilterBackend
from django.shortcuts import get_object_or_404
from django.contrib.auth.models import User
from rest_framework.viewsets import ModelViewSet
from rest_framework.permissions import IsAuthenticated
from .models import ClientConfig, UnidadeDeAtendimento, OrdemServico, ClientUser, Person, Appointment, Conversation, Message, Especialidade
from .serializers import (
    ClientConfigSerializer, UnidadeDeAtendimentoSerializer, ClientUserSerializer, PersonSerializer, OrdemServicoSerializer,
    AppointmentSerializer, ConversationSerializer, MessageSerializer, DisponibilidadeSerializer, EspecialidadeSerializer
)
from .utils import enviar_mensagem_whatsapp, avisar_profissional
from datetime import datetime
from .gessie_decisoes import gessie_agendar_consulta
from django.utils.timezone import now
from datetime import timedelta
from bot.models import SilencioTemporario
from django.db.models import Max
import requests
from rest_framework import generics, permissions


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def listar_funcionarios(request):
    if hasattr(request.user, "clientuser"):
        client = request.user.clientuser.client
        funcionarios = ClientUser.objects.filter(client=client, ativo=True)
        data = [{"id": f.id, "nome": f.nome} for f in funcionarios]
        return Response(data)
    return Response([], status=403)

class DisponibilidadeViewSet(ModelViewSet):
    queryset = Disponibilidade.objects.all()
    serializer_class = DisponibilidadeSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        client_user_id = self.request.query_params.get("client_user_id")
        if client_user_id:
            return Disponibilidade.objects.filter(profissional_id=client_user_id)
        return Disponibilidade.objects.none()

    def create(self, request, *args, **kwargs):
        profissional = request.data.get("profissional")
        dia_semana = request.data.get("dia_semana")
        horarios = request.data.get("horarios", [])
        if isinstance(horarios, str):
            try:
                horarios = json.loads(horarios)
            except Exception:
                return Response({"erro": "Formato inválido para horários"}, status=400)

        if not profissional or not dia_semana or not horarios:
            return Response({"erro": "Campos obrigatórios ausentes"}, status=400)

        # Remove entradas duplicadas antes de salvar
        Disponibilidade.objects.filter(profissional_id=profissional, dia_semana=dia_semana).delete()

        instance = Disponibilidade.objects.create(
            profissional_id=profissional,
            dia_semana=dia_semana,
            horarios=horarios,
        )
        serializer = self.get_serializer(instance)
        return Response(serializer.data, status=201)


class AuditoriaMensagensView(ListAPIView):
    serializer_class = MessageSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_fields = ['person__telefone', 'conversation']
    ordering_fields = ['data']
    ordering = ['-data']

    def get_queryset(self):
        user = self.request.user
        if hasattr(user, 'clientuser'):
            client = user.clientuser.client
            return Message.objects.filter(person__client=client)
        return Message.objects.none()



class MessageListCreateView(generics.ListCreateAPIView):
    serializer_class = MessageSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        conversation_id = self.request.query_params.get("conversation")
        if conversation_id:
            return Message.objects.filter(conversation_id=conversation_id).order_by("data")
        return Message.objects.none()

    def perform_create(self, serializer):
        conversation_id = self.request.data.get("conversation")
        conversation = get_object_or_404(Conversation, id=conversation_id)

        # Busca o person com base nas mensagens anteriores da conversa
        person = Message.objects.filter(
            conversation=conversation,
            person__isnull=False
        ).order_by("-data").first()
        person = person.person if person else None

        client_user = None
        if hasattr(self.request.user, "clientuser"):
            client_user = self.request.user.clientuser
            client_config = client_user.client

            # Enviar via Z-API
            try:
                payload = {
                    "phone": conversation.phone,
                    "message": self.request.data.get("mensagem")
                }
                headers = {
                    "Content-Type": "application/json",
                    "Client-Token": client_config.zapi_token
                }
                requests.post(client_config.zapi_url_text, json=payload, headers=headers)
            except Exception as e:
                print("❌ Erro ao enviar para Z-API:", e)

        serializer.save(
            person=person,
            client_user=client_user,
            conversation=conversation,
            enviado_por="usuario"
        )

class ClientConfigViewSet(viewsets.ModelViewSet):
    serializer_class = ClientConfigSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        if hasattr(self.request.user, 'clientuser'):
            return ClientConfig.objects.filter(id=self.request.user.clientuser.client.id)
        return ClientConfig.objects.none()

    @action(detail=True, methods=['post'])
    def alterar_status(self, request, pk=None):
        """
        Endpoint para alterar o status do cliente (ativo/desativo)
        """
        client_config = self.get_object()
        novo_status = request.data.get('ativo', False)
        
        try:
            client_config.ativo = novo_status
            client_config.save()
            
            # Registrar a alteração no log
            print(f"⚙️ Status alterado para {novo_status} pelo usuário {request.user.username}")
            
            return Response({
                'status': 'success',
                'ativo': client_config.ativo,
                'mensagem': 'Status atualizado com sucesso'
            })
        except Exception as e:
            return Response({
                'status': 'error',
                'mensagem': str(e)
            }, status=status.HTTP_400_BAD_REQUEST)


class ClientUserViewSet(viewsets.ModelViewSet):
    queryset = ClientUser.objects.all()
    serializer_class = ClientUserSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if hasattr(user, 'clientuser'):
            client = user.clientuser.client
            return ClientUser.objects.filter(client=client)
        return ClientUser.objects.none()

    from django.contrib.auth.models import User

    def perform_create(self, serializer):
        if hasattr(self.request.user, 'clientuser'):
            client = self.request.user.clientuser.client
            serializer.save(user=self.request.user, client=client)

    def perform_update(self, serializer):
        serializer.save()

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['request'] = self.request
        return context


class PersonViewSet(viewsets.ModelViewSet):
    serializer_class = PersonSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        if hasattr(self.request.user, 'clientuser'):
            client = self.request.user.clientuser.client
            return Person.objects.filter(client=client)
        return Person.objects.none()

    def perform_create(self, serializer):
        if hasattr(self.request.user, 'clientuser'):
            client_user = self.request.user.clientuser
            serializer.save(client=client_user.client, responsavel=client_user)

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["request"] = self.request
        return context


class AppointmentViewSet(viewsets.ModelViewSet):
    serializer_class = AppointmentSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        if hasattr(self.request.user, 'clientuser'):
            client = self.request.user.clientuser.client
            return Appointment.objects.filter(client=client)
        return Appointment.objects.none()

    def perform_create(self, serializer):
        if hasattr(self.request.user, 'clientuser'):
            client_user = self.request.user.clientuser

            # Salva o agendamento com o client e o client_user logado (quem criou)
            appointment = serializer.save(client=client_user.client, client_user=client_user)

            profissional = appointment.profissional  # Já é um ClientUser, pois agora é FK

            # Verifica se há uma pessoa para notificar
            if appointment.person and profissional:
                enviar_mensagem_whatsapp(
                    client_user=profissional,
                    person=appointment.person,
                    data_hora=appointment.data_hora,
                    client_config=client_user.client
                )
                avisar_profissional(
                    profissional_nome=profissional.nome,
                    pessoa_nome=appointment.person.nome,
                    data_hora=appointment.data_hora,
                    client_config=client_user.client
                )


class ConversationViewSet(viewsets.ModelViewSet):
    serializer_class = ConversationSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        try:
            user = self.request.user
            print("🔎 Usuário autenticado:", user)
            if hasattr(user, "clientuser"):
                client = user.clientuser.client
                print("🔎 Cliente associado:", client)
                return Conversation.objects.filter(
                    message__person__client=client
                ).annotate(
                    ultima_mensagem=Max("message__data")
                ).order_by("-ultima_mensagem")
            return Conversation.objects.none()
        except Exception as e:
            print("❌ Erro em get_queryset do ConversationViewSet:", str(e))
            return Conversation.objects.none()

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["request"] = self.request
        return context

    @action(detail=True, methods=["post"])
    def assumir(self, request, pk=None):
        conversation = self.get_object()
        user = request.user

        if not hasattr(user, "clientuser"):
            return Response({"erro": "Usuário não vinculado a um cliente."}, status=403)

        client_user = user.clientuser
        last_message = conversation.message_set.last()

        if last_message:
            last_message.client_user = client_user
            last_message.save()

        return Response({"status": "assumido por", "usuario": client_user.nome})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def buscar_ou_criar_pessoa(request):
    telefone = request.data.get("telefone")
    nome = request.data.get("nome")
    client_id = request.data.get("client_id")

    if not telefone or not nome or not client_id:
        return Response({"erro": "Campos obrigatórios ausentes."}, status=status.HTTP_400_BAD_REQUEST)

    try:
        pessoa = Person.objects.filter(telefone=telefone, client_id=client_id).first()
        if not pessoa:
            pessoa = Person.objects.create(
                telefone=telefone,
                nome=nome,
                client_id=client_id,
                grau_interesse='médio',
                ativo=True
            )
        return Response({"person_id": pessoa.id})
    except Exception as e:
        return Response({"erro": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class GessieFunctionCallingView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        try:
            payload = request.data
            print("📩 Dados recebidos para function calling:", payload)

            phone = payload.get("telefone")
            client_config = ClientConfig.objects.filter(telefone=phone).first()
            if not client_config:
                return Response({"erro": "Cliente não encontrado"}, status=404)

            resultado = gessie_agendar_consulta(
                nome=payload.get("nome"),
                telefone=payload.get("telefone"),
                idade=payload.get("idade"),
                tipo_atendimento=payload.get("tipo_atendimento"),
                plano_saude=payload.get("plano_saude"),
                turno_preferido=payload.get("turno_preferido"),
                data_preferida=payload.get("data_preferida"),
                client_config=client_config,
            )

            return Response(resultado)
        except Exception as e:
            print("❌ Erro ao processar function calling:", str(e))
            return Response({"erro": str(e)}, status=500)


@api_view(["POST"])
def silenciar_gessie(request):
    phone = request.data.get("phone")
    minutos = int(request.data.get("minutos", 5))

    if not phone:
        return Response({"erro": "Telefone não fornecido."}, status=400)

    ate = now() + timedelta(minutes=minutos)
    SilencioTemporario.objects.update_or_create(phone=phone, defaults={"ate": ate})

    return Response({"mensagem": f"Gessie silenciada até {ate}."})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def importar_contatos(request):
    client_user = request.user.clientuser
    client_config = client_user.client
    token = client_config.zapi_token

    url_contatos = f"https://api.z-api.io/instances/3DFCEFFC436AD08545800A1EFCACDE10/token/3ADBF95CB1315102507AB92B/contacts?page=1&pageSize=200"
    url_foto = f"https://api.z-api.io/instances/3DFCEFFC436AD08545800A1EFCACDE10/token/3ADBF95CB1315102507AB92B/profile-picture"
    headers = {
        "Client-Token": token
    }

    try:
        response = requests.get(url_contatos, headers=headers)
        if response.status_code != 200:
            return Response({
                "erro": "Erro ao buscar contatos da Z-API",
                "status_code": response.status_code,
                "detalhes": response.text
            }, status=response.status_code)

        contatos = response.json()
        total_importados = 0

        for contato in contatos:
            telefone = contato.get("phone")
            nome = contato.get("name") or contato.get("short") or contato.get("notify") or telefone

            if not telefone:
                continue

            # Buscar foto de perfil atualizada
            try:
                foto_response = requests.get(f"{url_foto}?phone={telefone}", headers=headers)
                foto_url = None
                if foto_response.status_code == 200:
                    foto_data = foto_response.json()
                    if isinstance(foto_data, dict) and "link" in foto_data:
                        foto_url = foto_data["link"]
                    elif isinstance(foto_data, list) and foto_data and "link" in foto_data[0]:
                        foto_url = foto_data[0]["link"]
            except Exception as e:
                print(f"⚠️ Erro ao buscar foto do contato {telefone}: {e}")
                foto_url = None

            Person.objects.update_or_create(
                telefone=telefone,
                client=client_config,
                defaults={"nome": nome, "foto_url": foto_url}
            )
            total_importados += 1

        return Response({"status": "contatos importados com sucesso", "total": total_importados})

    except Exception as e:
        return Response({"erro": str(e)}, status=500)

# views.py
class EspecialidadeViewSet(viewsets.ModelViewSet):
    serializer_class = EspecialidadeSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        client_user = getattr(self.request.user, "clientuser", None)
        if client_user:
            return Especialidade.objects.filter(client=client_user.client)
        return Especialidade.objects.none()

    def perform_create(self, serializer):
        client = self.request.user.clientuser.client
        serializer.save(client=client)


class OrdemServicoViewSet(viewsets.ModelViewSet):
    serializer_class = OrdemServicoSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if hasattr(user, "clientuser"):
            return OrdemServico.objects.filter(client=user.clientuser.client)
        return OrdemServico.objects.none()

    def perform_create(self, serializer):
        client = self.request.user.clientuser.client
        serializer.save(client=client)



@api_view(["GET"])
@permission_classes([IsAuthenticated])
def horarios_disponiveis_profissional(request, profissional_id):
    """
    Retorna os horários disponíveis de um profissional agrupados por dia da semana.
    """
    disponibilidades = Disponibilidade.objects.filter(profissional_id=profissional_id)

    resultado = {}
    for d in disponibilidades:
        if d.dia_semana not in resultado:
            resultado[d.dia_semana] = []
        resultado[d.dia_semana].extend(d.horarios)

    return Response(resultado)

# views.py
class UnidadeDeAtendimentoViewSet(viewsets.ModelViewSet):
    serializer_class = UnidadeDeAtendimentoSerializer
    permission_classes = [IsAuthenticated]
    queryset = UnidadeDeAtendimento.objects.none()  # ⬅️ adiciona isto como fallback

    def get_queryset(self):
        user = self.request.user

        if hasattr(user, 'clientuser'):
            client = user.clientuser.client
            qs = UnidadeDeAtendimento.objects.filter(client=client)

            client_user_id = self.request.query_params.get("client_user_id")
            if client_user_id:
                try:
                    profissional = ClientUser.objects.get(id=client_user_id, client=client)
                    return profissional.unidades.all()
                except ClientUser.DoesNotExist:
                    return UnidadeDeAtendimento.objects.none()

            return qs

        return UnidadeDeAtendimento.objects.none()

    def perform_create(self, serializer):
        client = self.request.user.clientuser.client
        serializer.save(client=client)