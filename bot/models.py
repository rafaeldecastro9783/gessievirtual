from django.db import models
from django.db.models import JSONField
from django.contrib.auth.models import User
from django.core.validators import RegexValidator
from django.utils import timezone
from django.utils.timezone import now
from django.core.files.storage import FileSystemStorage
from django.conf import settings
import os
from .fields import ListaHorariosField

# Configuração para armazenamento de fotos
fs = FileSystemStorage(location=os.path.join(settings.MEDIA_ROOT, 'fotos'))


# 🕒 Mensagens recebidas aguardando agrupamento ou processamento
class PendingMessage(models.Model):
    phone = models.CharField(max_length=20)
    content = models.TextField()
    timestamp = models.DateTimeField(auto_now_add=True)
    processed = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.phone} - {self.timestamp.strftime('%d/%m/%Y %H:%M')}"


# 🏢 Clientes que contratam a Gessie (clínica, empresa de manutenção etc.)
class ClientConfig(models.Model):
    nome = models.CharField(max_length=255)
    cnpj = models.CharField(max_length=18, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    telefone = models.CharField(max_length=20, blank=True, null=True)

    # Integrações
    zapi_url_text = models.URLField()
    zapi_url_audio = models.URLField()
    zapi_token = models.CharField(max_length=255)

    # Integração OpenAI 
    assistant_id = models.CharField(max_length=100)
    prompt_personalizado = models.TextField()

    regras_json = JSONField(blank=True, null=True)

    ativo = models.BooleanField(default=True)

    def __str__(self):
        return self.nome

class UnidadeDeAtendimento(models.Model):
    nome = models.CharField(max_length=255)
    endereco = models.TextField()
    telefone = models.CharField(max_length=20, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    cnpj = models.CharField(max_length=18, blank=True, null=True)
    client = models.ForeignKey(ClientConfig, on_delete=models.CASCADE, related_name='unidades')

    def __str__(self):
        return f"{self.nome} ({self.client.nome})"

# 🔁 Threads de conversa com o assistente da OpenAI
class Conversation(models.Model):
    phone = models.CharField(max_length=20)
    thread_id = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    client = models.ForeignKey(ClientConfig, on_delete=models.CASCADE)

    def __str__(self):
        return f"{self.phone} - {self.thread_id}"
        
class Especialidade(models.Model):
    nome = models.CharField(max_length=100)
    client = models.ForeignKey(ClientConfig, on_delete=models.CASCADE, related_name="especialidades")

    class Meta:
        unique_together = ('nome', 'client')  # evita nomes duplicados dentro do mesmo cliente

    def __str__(self):
        return f"{self.nome} ({self.client.nome})"

class ClientUser(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)  
    client = models.ForeignKey(ClientConfig, on_delete=models.CASCADE)
    nome = models.CharField(max_length=255)
    email = models.EmailField()
    telefone = models.CharField(max_length=20)
    senha = models.CharField(max_length=255)  
    foto_url = models.URLField(blank=True, null=True)
    ativo = models.BooleanField(default=True)
    especialidades = models.ManyToManyField(Especialidade, blank=True)
    unidades = models.ManyToManyField('UnidadeDeAtendimento', related_name='profissionais', blank=True)

    def __str__(self):
        return f"{self.nome} ({self.client.nome})"


# 📇 Pessoas que interagem com a Gessie (clientes, leads, pacientes)
class Person(models.Model):
    client = models.ForeignKey(ClientConfig, on_delete=models.CASCADE, related_name='pessoas')
    nome = models.CharField(max_length=255, blank=True, null=True)
    foto_url = models.URLField(blank=True, null=True)
    photo = models.ImageField(
        upload_to='fotos/%Y/%m/%d/',
        storage=fs,
        blank=True,
        null=True,
        help_text='Foto local do contato'
    )
    idade = models.CharField(max_length=3, blank=True, null=True)  
    telefone = models.CharField(max_length=20, unique=True)
    cpf = models.CharField(max_length=14, blank=True, null=True, validators=[
        RegexValidator(
            regex='^[0-9]{11}$',
            message='CPF deve conter 11 dígitos numéricos',
            code='invalid_cpf'
        )
    ])
    grau_interesse = models.CharField(
        max_length=50,
        choices=[('baixo', 'Baixo'), ('médio', 'Médio'), ('alto', 'Alto')],
        blank=True,
        null=True
    )
    responsavel = models.ForeignKey(
        ClientUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='pessoas_responsaveis'
    )
    ativo = models.BooleanField(default=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Pessoa'
        verbose_name_plural = 'Pessoas'
        ordering = ['-ativo', 'nome']

    def __str__(self):
        return self.nome or self.telefone

    def save(self, *args, **kwargs):
        # Se não tiver nome, usar o telefone
        if not self.nome:
            self.nome = self.telefone
        super().save(*args, **kwargs)


# 💬 Mensagens trocadas entre Gessie, usuário e cliente
class Message(models.Model):
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, null=True, blank=True)
    person = models.ForeignKey(Person, on_delete=models.CASCADE, null=True, blank=True)
    client_user = models.ForeignKey(ClientUser, on_delete=models.SET_NULL, null=True, blank=True)
    enviado_por = models.CharField(max_length=10, choices=[('gessie', 'Gessie'), ('pessoa', 'Pessoa'), ('usuario', 'Usuário')])
    mensagem = models.TextField()
    tipo = models.CharField(max_length=10, choices=[('texto', 'Texto'), ('áudio', 'Áudio')])
    data = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        if self.person:
            return f"{self.person.nome} ({self.enviado_por}) - {self.data.strftime('%d/%m/%Y %H:%M')}"
        return f"{self.enviado_por} - {self.data.strftime('%d/%m/%Y %H:%M')}"

    @property
    def foto_remetente(self):
        if self.person and hasattr(self.person, 'foto_url'):
            return self.person.foto_url
        elif self.client_user and hasattr(self.client_user, 'foto_url'):
            return self.client_user.foto_url
        return 'https://via.placeholder.com/150?text=Sem+foto'


# 📆 Agendamentos de sessões ou atendimentos
class Appointment(models.Model):
    client = models.ForeignKey(ClientConfig, on_delete=models.CASCADE)
    person = models.ForeignKey(Person, on_delete=models.CASCADE)
    client_user = models.ForeignKey(ClientUser, on_delete=models.SET_NULL, null=True, blank=True, related_name="agendamentos_recebidos")
    data_hora = models.DateTimeField()
    criado_em = models.DateTimeField(default=now)
    profissional = models.ForeignKey(ClientUser, on_delete=models.SET_NULL, null=True, blank=True, related_name="agendamentos_como_profissional")
    observacoes = models.TextField(blank=True, null=True)
    confirmado = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.person.nome} com {self.profissional} - {self.data_hora.strftime('%d/%m/%Y %H:%M')}"


class Disponibilidade(models.Model):
    profissional = models.ForeignKey(ClientUser, on_delete=models.CASCADE, related_name='disponibilidades')
    dia_semana = models.CharField(max_length=10, choices=[
        ('segunda', 'Segunda'),
        ('terca', 'Terça'),
        ('quarta', 'Quarta'),
        ('quinta', 'Quinta'),
        ('sexta', 'Sexta'),
        ('sabado', 'Sábado'),
        ('domingo', 'Domingo'),
    ])
    horarios = ListaHorariosField()

    def __str__(self):
        return f"{self.profissional.nome} - {self.dia_semana.capitalize()}"

class SilencioTemporario(models.Model):
    phone = models.CharField(max_length=20, unique=True)
    ate = models.DateTimeField()


class OrdemServico(models.Model):
    numero_os = models.CharField(max_length=20, unique=True)
    data_emissao = models.DateField(auto_now_add=True)
    cliente_nome = models.CharField(max_length=255)
    cliente_endereco = models.TextField()
    cliente_contato = models.CharField(max_length=100)

    descricao_servico = models.TextField()
    profissional_responsavel = models.ForeignKey(ClientUser, on_delete=models.SET_NULL, null=True)
    
    materiais_equipamentos = models.TextField(blank=True)
    tempo_estimado = models.CharField(max_length=100)
    custo = models.DecimalField(max_digits=10, decimal_places=2)

    client = models.ForeignKey(ClientConfig, on_delete=models.CASCADE)  # vínculo com o cliente principal
    atualizado_em = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"OS #{self.numero_os} - {self.cliente_nome}"
