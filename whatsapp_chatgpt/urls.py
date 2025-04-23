from django.contrib import admin
from django.urls import path, include
from django.views.decorators.csrf import csrf_exempt
from bot import views

urlpatterns = [
    path('admin/', admin.site.urls),                         # acesso ao painel admin
    path('api/', include('bot.urls')),                        # rotas da API
    path("webhook/", csrf_exempt(views.whatsapp_webhook)),                     # webhook do WhatsApp
]

