from django.db import models
from django.contrib.auth.models import User
from django.utils.timezone import now
from django.db.models import JSONField



# 🔁 Threads de conversa com o assistente da OpenAI
class Conversation(models.Model):
    phone = models.CharField(max_length=20)
    thread_id = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.phone} - {self.thread_id}"


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


class Especialidade(models.Model):
    nome = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return self.nome

class ClientUser(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)  # <- VÍNCULO AQUI
    client = models.ForeignKey(ClientConfig, on_delete=models.CASCADE)
    nome = models.CharField(max_length=255)
    email = models.EmailField()
    telefone = models.CharField(max_length=20)
    senha = models.CharField(max_length=255)  # considere usar user.set_password()
    ativo = models.BooleanField(default=True)
    especialidades = models.ManyToManyField(Especialidade, blank=True)  # <-- relação N:N


    def __str__(self):
        return f"{self.nome} ({self.client.nome})"



# 📇 Pessoas que interagem com a Gessie (clientes, leads, pacientes)
class Person(models.Model):
    client = models.ForeignKey(ClientConfig, on_delete=models.CASCADE)
    nome = models.CharField(max_length=255)
    idade = models.CharField(max_length=255)
    telefone = models.CharField(max_length=20)
    cpf = models.CharField(max_length=14, blank=True, null=True)
    grau_interesse = models.CharField(
    max_length=50,
    choices=[('baixo', 'Baixo'), ('médio', 'Médio'), ('alto', 'Alto')],
    blank=True,
    null=True
)
    responsavel = models.ForeignKey(ClientUser, on_delete=models.SET_NULL, null=True, blank=True)
    ativo = models.BooleanField(default=True)

    def __str__(self):
        return self.nome


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


# 📆 Agendamentos de sessões ou atendimentos
class Appointment(models.Model):
    client = models.ForeignKey(ClientConfig, on_delete=models.CASCADE)
    person = models.ForeignKey(Person, on_delete=models.CASCADE)
    client_user = models.ForeignKey(ClientUser, on_delete=models.SET_NULL, null=True, blank=True, related_name="agendamentos_recebidos")
    data_hora = models.DateTimeField()
    criado_em = models.DateTimeField(default=now)
    profissional = models.CharField(max_length=255)
    observacoes = models.TextField(blank=True, null=True)
    confirmado = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.person.nome} com {self.profissional} - {self.data_hora.strftime('%d/%m/%Y %H:%M')}"


# Campo customizado compatível com SQLite para listas simples
class ListaHorariosField(models.TextField):
    description = "Lista de horários como texto separado por vírgulas"

    def from_db_value(self, value, expression, connection):
        if value is None:
            return []
        return value.split(',')

    def to_python(self, value):
        if isinstance(value, list):
            return value
        if value is None:
            return []
        return value.split(',')

    def get_prep_value(self, value):
        return ','.join(value) if isinstance(value, list) else value


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
