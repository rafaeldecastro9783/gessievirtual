from django.contrib import admin
from .models import (
    Conversation,
    PendingMessage,
    ClientConfig,
    ClientUser,
    Person,
    Message,
    Appointment,
    Especialidade,
    Disponibilidade,
    OrdemServico
)
import json
from django.utils.html import format_html

@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ('phone', 'thread_id', 'created_at')
    search_fields = ('phone', 'thread_id')
    ordering = ('-created_at',)

@admin.register(PendingMessage)
class PendingMessageAdmin(admin.ModelAdmin):
    list_display = ('phone', 'content', 'timestamp', 'processed')
    list_filter = ('processed',)
    search_fields = ('phone', 'content')
    ordering = ('-timestamp',)

@admin.register(ClientConfig)
class ClientConfigAdmin(admin.ModelAdmin):
    list_display = ('nome', 'telefone', 'cnpj', 'ativo', 'visualizar_regras')
    search_fields = ('nome', 'telefone', 'cnpj')
    list_filter = ('ativo',)

    def visualizar_regras(self, obj):
        try:
            if obj.regras_json:
                regras = json.dumps(obj.regras_json, indent=2, ensure_ascii=False)
                return format_html('<pre style="white-space: pre-wrap;">{}</pre>', regras)
        except Exception as e:
            return f"Erro ao exibir: {e}"
        return "–"

@admin.register(Disponibilidade)
class DisponibilidadeAdmin(admin.ModelAdmin):
    list_display = ('profissional', 'dia_semana', 'listar_horarios')
    list_filter = ('profissional', 'dia_semana')
    search_fields = ('profissional__nome',)

    def listar_horarios(self, obj):
        return format_html("<br>".join(obj.horarios))
    listar_horarios.short_description = "Horários disponíveis"

class DisponibilidadeInline(admin.TabularInline):
    model = Disponibilidade
    extra = 1
    fields = ('dia_semana', 'horarios')
    verbose_name = "Disponibilidade"
    verbose_name_plural = "Disponibilidades"

@admin.register(ClientUser)
class ClientUserAdmin(admin.ModelAdmin):
    list_display = ('nome', 'email', 'telefone', 'client', 'ativo', 'listar_especialidades')
    search_fields = ('nome', 'email', 'telefone', 'especialidades__nome')
    list_filter = ('ativo', 'client')
    filter_horizontal = ('especialidades', 'unidades')  # ✅ aqui!
    inlines = [DisponibilidadeInline]

    def listar_especialidades(self, obj):
        return format_html("<br>".join([e.nome for e in obj.especialidades.all()]))

@admin.register(Especialidade)
class EspecialidadeAdmin(admin.ModelAdmin):
    list_display = ('nome',)
    search_fields = ('nome',)
    ordering = ('nome',)

@admin.register(Person)
class PersonAdmin(admin.ModelAdmin):
    list_display = ('nome', 'telefone', 'cpf', 'grau_interesse', 'ativo', 'client')
    search_fields = ('nome', 'telefone', 'cpf')
    list_filter = ('grau_interesse', 'ativo', 'client')

@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ('person', 'enviado_por', 'tipo', 'data')
    search_fields = ('person__nome', 'mensagem')
    list_filter = ('enviado_por', 'tipo', 'data')
    ordering = ('-data',)

@admin.action(description="Marcar agendamentos como não confirmados")
def desconfirmar_agendamentos(modeladmin, request, queryset):
    queryset.update(confirmado=False)

@admin.register(Appointment)
class AppointmentAdmin(admin.ModelAdmin):
    list_display = ('person', 'profissional', 'data_hora', 'confirmado', 'client', 'criado_em')
    search_fields = ('person__nome', 'profissional')
    list_filter = ('confirmado', 'client')
    ordering = ('-data_hora',)
    actions = [desconfirmar_agendamentos]

# @admin.register(OrdemServico)
#class OrdemServicoAdmin(admin.ModelAdmin):
 #   list_display = ('id', 'client', 'profissional', 'status', 'criado_em', 'atualizado_em')
 #   search_fields = ('client__nome', 'profissional__nome', 'status', 'descricao')
 #   list_filter = ('status', 'criado_em')
 #   ordering = ('-criado_em',)
 #  readonly_fields = ('criado_em', 'atualizado_em')

