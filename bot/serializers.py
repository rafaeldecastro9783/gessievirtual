# bot/serializers.py
from rest_framework import serializers
from .models import ClientConfig, ClientUser, Person, Appointment, Conversation, Message, Disponibilidade, SilencioTemporario, Especialidade
from rest_framework import serializers
from django.contrib.auth.models import User
from django.utils.timezone import now
from django.utils.crypto import get_random_string
import ast
import traceback


class EspecialidadeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Especialidade
        fields = ['id', 'nome', 'client']
        read_only_fields = ['client']


from rest_framework import serializers
from django.contrib.auth.models import User
from bot.models import ClientUser, Especialidade

class ClientUserSerializer(serializers.ModelSerializer):
    username = serializers.CharField(write_only=True, required=False)
    password = serializers.CharField(write_only=True, min_length=6, required=False)
    senha = serializers.CharField(write_only=True, required=False)

    especialidades = EspecialidadeSerializer(many=True, read_only=True)
    especialidades_ids = serializers.ListField(
        child=serializers.IntegerField(),
        write_only=True,
        required=False
    )

    class Meta:
        model = ClientUser
        fields = [
            'id', 'nome', 'email', 'telefone', 'ativo', 'client',
            'username', 'password', 'senha',
            'especialidades', 'especialidades_ids'
        ]
        extra_kwargs = {
            'client': {'read_only': True}
        }

    def validate_especialidades_ids(self, value):
        request = self.context.get("request")
        if request and hasattr(request.user, "clientuser"):
            client = request.user.clientuser.client
            allowed_ids = set(Especialidade.objects.filter(client=client).values_list("id", flat=True))
            invalid_ids = [pk for pk in value if pk not in allowed_ids]

            if invalid_ids:
                raise serializers.ValidationError(f"Especialidades inválidas: {invalid_ids}")
        return value

    def create(self, validated_data):
        especialidades_ids = validated_data.pop('especialidades_ids', [])
        validated_data.pop('username', None)
        validated_data.pop('password', None)
        validated_data.pop('user', None)
        validated_data.pop('client', None)  # 🔧 remove duplicidade
        senha = validated_data.pop('senha', '')

        request = self.context.get("request")
        client = request.user.clientuser.client if request and hasattr(request.user, 'clientuser') else None

        from django.contrib.auth.models import User
        from django.utils.crypto import get_random_string

        email = validated_data.get("email", "")
        nome = validated_data.get("nome", "")
        username = f"{email}-{get_random_string(5)}"

        user = User.objects.create_user(
            username=username,
            email=email,
            password=get_random_string(12),
            first_name=nome
        )

        client_user = ClientUser.objects.create(
            user=user,
            client=client,
            senha=senha,
            **validated_data
        )

        especialidades = Especialidade.objects.filter(id__in=especialidades_ids)
        client_user.especialidades.set(especialidades)

        return client_user

    def update(self, instance, validated_data):
        from rest_framework.exceptions import ValidationError
        import traceback

        try:
            especialidades_ids = validated_data.pop('especialidades_ids', None)
            if especialidades_ids is not None:
                especialidades = Especialidade.objects.filter(id__in=especialidades_ids)
                instance.especialidades.set(especialidades)

            username = validated_data.pop('username', None)
            password = validated_data.pop('password', None)
            senha = validated_data.pop('senha', None)

            instance.nome = validated_data.get('nome', instance.nome)
            instance.telefone = validated_data.get('telefone', instance.telefone)
            instance.email = validated_data.get('email', instance.email)
            if senha:
                instance.senha = senha
            instance.save()

            user = instance.user
            if username:
                user.username = username
            if password:
                user.set_password(password)
            user.email = instance.email
            user.first_name = instance.nome
            user.save()

            return instance

        except ValidationError as ve:
            print("❌ Erro de validação:", ve.detail)
            raise ve
        except Exception as e:
            print("❌ Erro inesperado no update:", e)
            print(traceback.format_exc())
            raise e

class DisponibilidadeSerializer(serializers.ModelSerializer):
    horarios = serializers.SerializerMethodField()

    class Meta:
        model = Disponibilidade
        fields = '__all__'

    def get_horarios(self, obj):
        if isinstance(obj.horarios, str):
            try:
                return ast.literal_eval(obj.horarios)
            except Exception as e:
                print(f"Erro ao converter horários: {e}")
                return []
        return obj.horarios

class ClientConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = ClientConfig
        fields = ['id', 'nome', 'cnpj', 'email', 'telefone', 'zapi_url_text', 'zapi_url_audio', 'zapi_token', 'assistant_id', 'prompt_personalizado', 'regras_json', 'ativo']

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data['status'] = 'ativo' if instance.ativo else 'inativo'
        return data

class PersonSerializer(serializers.ModelSerializer):
    foto_url = serializers.SerializerMethodField()
    photo_url = serializers.SerializerMethodField()

    class Meta:
        model = Person
        fields = [
            'id', 'nome', 'foto_url', 'photo_url', 'photo', 'idade', 
            'telefone', 'cpf', 'grau_interesse', 'responsavel', 'ativo', 'client'
        ]

    def get_foto_url(self, obj):
        return obj.foto_url or 'https://via.placeholder.com/150?text=Sem+foto'
   
    def get_photo_url(self, obj):
        request = self.context.get('request')
        if obj.photo and request:
            return request.build_absolute_uri(obj.photo.url)
        return None


class AppointmentSerializer(serializers.ModelSerializer):
    person_nome = serializers.CharField(source="person.nome", read_only=True)
    client_user_nome = serializers.CharField(source="client_user.nome", read_only=True)

    class Meta:
        model = Appointment
        fields = ['id', 'data_hora', 'profissional', 'observacoes', 'confirmado', 'person_nome', 'client_user_nome']


# serializers.py
class MessageSerializer(serializers.ModelSerializer):
    client_user_nome = serializers.SerializerMethodField()

    class Meta:
        model = Message
        fields = ['id', 'conversation', 'person', 'client_user', 'enviado_por', 'mensagem', 'tipo', 'data', 'foto_remetente', 'client_user_nome']
        extra_kwargs = {
            'person': {'required': False, 'allow_null': True}
        }

    def get_foto_remetente(self, obj):
        if obj.client_user:
            return obj.client_user.foto_url
        elif obj.person:
            return obj.person.foto_url
        else:
            return None

    def get_client_user_nome(self, obj):
        return obj.client_user.nome if obj.client_user else None

    def create(self, validated_data):
        if 'person' not in validated_data or not validated_data['person']:
            conversation = validated_data.get('conversation')
            if conversation:
                ultima_msg = conversation.message_set.last()
                if ultima_msg and ultima_msg.person:
                    validated_data['person'] = ultima_msg.person
                else:
                    try:
                        from .models import Person
                        validated_data['person'] = Person.objects.get(telefone=conversation.phone)
                    except Person.DoesNotExist:
                        validated_data['person'] = None

        return super().create(validated_data)



class ConversationSerializer(serializers.ModelSerializer):
    person_nome = serializers.SerializerMethodField()
    person_telefone = serializers.SerializerMethodField()
    ultima_mensagem = serializers.SerializerMethodField()
    gessie_silenciada = serializers.SerializerMethodField() 
    assumido_por_mim = serializers.SerializerMethodField()  # 👈 aqui

    class Meta:
        model = Conversation
        fields = ['id', 'phone', 'created_at', 'person_nome', 'person_telefone', 'ultima_mensagem', 'gessie_silenciada','assumido_por_mim']

    def get_person_nome(self, obj):
        try:
            last = obj.message_set.last()
            return last.person.nome if last and last.person else obj.phone
        except Exception:
            return obj.phone

    def get_person_telefone(self, obj):
        try:
            last = obj.message_set.last()
            return last.person.telefone if last and last.person else obj.phone
        except Exception:
            return obj.phone

    def get_ultima_mensagem(self, obj):
        try:
            last = obj.message_set.last()
            return last.mensagem if last else None
        except Exception:
            return None

    def get_gessie_silenciada(self, obj):
        return SilencioTemporario.objects.filter(phone=obj.phone, ate__gt=now()).exists()
        
    def get_assumido_por_mim(self, obj):
        try:
            request = self.context.get('request')
            user = request.user
            last_msg = obj.message_set.last()
            return last_msg and hasattr(user, 'clientuser') and last_msg.client_user == user.clientuser
        except Exception:
            return False

