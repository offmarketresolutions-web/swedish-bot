from django.urls import path

from voice import webhooks, whatsapp

urlpatterns = [
    path("vapi/webhook", webhooks.vapi_webhook, name="voice-vapi-webhook"),
    path("whatsapp/webhook", whatsapp.whatsapp_webhook, name="voice-whatsapp-webhook"),
]
