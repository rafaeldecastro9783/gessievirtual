from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
)
from .api_views import (
    ClientConfigViewSet, ClientUserViewSet, UnidadeDeAtendimentoViewSet, PersonViewSet, OrdemServicoViewSet, horarios_disponiveis_profissional,
    AppointmentViewSet, ConversationViewSet, DisponibilidadeViewSet, EspecialidadeViewSet, ClientUserViewSet)
from .api_views import buscar_ou_criar_pessoa, listar_funcionarios, importar_contatos
from .api_views import GessieFunctionCallingView
from .api_views import MessageListCreateView
from .api_views import AuditoriaMensagensView # 👈 novo import
from . import api_views

# Inicializa o router com os endpoints da API
router = DefaultRouter()
router.register(r'clientes', ClientConfigViewSet, basename='clientconfig')
router.register(r'pessoas', PersonViewSet, basename='pessoa')
router.register(r'usuarios', ClientUserViewSet, basename='usuario')
router.register(r'agendamentos', AppointmentViewSet, basename='agendamento')
router.register(r'conversas', ConversationViewSet, basename='conversa')
router.register(r'especialidades', EspecialidadeViewSet, basename='especialidade')
router.register(r'disponibilidades', DisponibilidadeViewSet, basename='disponibilidade')
router.register(r'ordens-servico', OrdemServicoViewSet, basename='ordemservico')
router.register(r"unidades", UnidadeDeAtendimentoViewSet, basename='unidade')


# Todas as rotas
urlpatterns = [
    # JWT Auth
    path('token/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),

    # CRUDs
    path('', include(router.urls)),
    path("silenciar-gessie/", api_views.silenciar_gessie, name="silenciar-gessie"),
    path("funcionarios/", listar_funcionarios),
    path("mensagens/", MessageListCreateView.as_view(), name="mensagens"),
    path("buscar_ou_criar_pessoa/", buscar_ou_criar_pessoa),
    path("auditoria/mensagens/", AuditoriaMensagensView.as_view(), name="auditoria-mensagens"),
    path("gessie/function-calling/", GessieFunctionCallingView.as_view(), name="gessie_function_calling"),
    path("importar-contatos/", importar_contatos, name="importar-contatos"),
    path("profissional/<int:profissional_id>/horarios-disponiveis/", horarios_disponiveis_profissional),

]


