# bot/serializers.py

from rest_framework import serializers
from .models import ClientConfig, ClientUser, Person, Appointment, Conversation, Message
from rest_framework import serializers
from django.contrib.auth.models import User
from .models import ClientUser

from django.contrib.auth.models import User
from rest_framework import serializers
from .models import ClientUser

class ClientUserSerializer(serializers.ModelSerializer):
    username = serializers.CharField(write_only=True)
    password = serializers.CharField(write_only=True, min_length=6)

    class Meta:
        model = ClientUser
        fields = ['id', 'nome', 'email', 'telefone', 'ativo', 'client', 'username', 'password']
        extra_kwargs = {
            'client': {'read_only': True}  # evita que client_id seja sobrescrito no frontend
        }

    def create(self, validated_data):
        username = validated_data.pop('username')
        password = validated_data.pop('password')

        user = User.objects.create_user(
            username=username,
            password=password,
            email=validated_data.get('email'),
            first_name=validated_data.get('nome', '')
        )

        return ClientUser.objects.create(user=user, **validated_data)



class ClientConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = ClientConfig
        fields = '__all__'

class PersonSerializer(serializers.ModelSerializer):
    class Meta:
        model = Person
        fields = '__all__'

# bot/serializers.py

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
        fields = ['id', 'conversation', 'person', 'mensagem', 'tipo', 'enviado_por', 'client_user', 'client_user_nome', 'data']
        extra_kwargs = {
            'person': {'required': False, 'allow_null': True}
        }
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
    assumido_por_mim = serializers.SerializerMethodField()  # 👈 aqui

    class Meta:
        model = Conversation
        fields = ['id', 'phone', 'created_at', 'person_nome', 'person_telefone', 'ultima_mensagem', 'assumido_por_mim']

    def get_person_nome(self, obj):
        last = obj.message_set.last()
        return last.person.nome if last and last.person else obj.phone

    def get_person_telefone(self, obj):
        last = obj.message_set.last()
        return last.person.telefone if last and last.person else obj.phone

    def get_ultima_mensagem(self, obj):
        last = obj.message_set.last()
        return last.mensagem if last else None

    def get_assumido_por_mim(self, obj):
        request = self.context.get("request")
        if not request or not hasattr(request.user, "clientuser"):
            return False
        return obj.message_set.filter(client_user=request.user.clientuser).exists()
