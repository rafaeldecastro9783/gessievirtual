from rest_framework import viewsets, status, generics
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError
from rest_framework.decorators import api_view, permission_classes, action
from rest_framework.views import APIView
from rest_framework.generics import ListAPIView
from rest_framework.filters import OrderingFilter
from django_filters.rest_framework import DjangoFilterBackend
from django.shortcuts import get_object_or_404
from django.contrib.auth.models import User

from .models import ClientConfig, ClientUser, Person, Appointment, Conversation, Message
from .serializers import (
    ClientConfigSerializer, ClientUserSerializer, PersonSerializer,
    AppointmentSerializer, ConversationSerializer, MessageSerializer
)
from .utils import enviar_mensagem_whatsapp
from .gessie_decisoes import gessie_agendar_consulta


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def listar_funcionarios(request):
    if hasattr(request.user, "clientuser"):
        client = request.user.clientuser.client
        funcionarios = ClientUser.objects.filter(client=client, ativo=True)
        data = [{"id": f.id, "nome": f.nome} for f in funcionarios]
        return Response(data)
    return Response([], status=403)


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


from rest_framework import generics, permissions
from rest_framework import generics, permissions
from rest_framework.response import Response
from django.shortcuts import get_object_or_404
from .models import Message, Conversation
from .serializers import MessageSerializer
import requests

class MessageListCreateView(generics.ListCreateAPIView):
    serializer_class = MessageSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        conversation_id = self.request.query_params.get("conversation")
        user = self.request.user
        if conversation_id and hasattr(user, 'clientuser'):
            return Message.objects.filter(
                conversation_id=conversation_id,
                person__client=user.clientuser.client
            ).order_by("data")
        return Message.objects.none()

    def perform_create(self, serializer):
        conversation_id = self.request.data.get("conversation")
        conversation = get_object_or_404(Conversation, id=conversation_id)
        last_msg = Message.objects.filter(conversation=conversation).last()
        person = last_msg.person if last_msg else None

        client_user = None
        if hasattr(self.request.user, "clientuser"):
            client_user = self.request.user.clientuser
            client_config = client_user.client

            # Enviar mensagem via Z-API
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

            # Dados que vieram do frontend
            nome = serializer.validated_data.get("nome")
            email = serializer.validated_data.get("email")
            telefone = serializer.validated_data.get("telefone")
            senha = serializer.validated_data.get("senha")

            # Criação do User
            user = User.objects.create_user(
                username=email,
                email=email,
                password=senha,
                first_name=nome
            )

            # Salvar o ClientUser vinculado ao User e Client
            serializer.save(user=user, client=client)


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
            appointment = serializer.save(client=client_user.client, client_user=client_user)
            if appointment.person:
                enviar_mensagem_whatsapp(client_user, appointment.person, appointment.data_hora)


class ConversationViewSet(viewsets.ModelViewSet):
    queryset = Conversation.objects.all().order_by('-created_at')
    serializer_class = ConversationSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if hasattr(user, "clientuser"):
            client = user.clientuser.client
            return Conversation.objects.filter(message__person__client=client).distinct().order_by('-created_at')
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
