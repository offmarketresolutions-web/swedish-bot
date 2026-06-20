from django.urls import path

from chat import views

urlpatterns = [
    path("session", views.create_session, name="chat-session"),
    path("<uuid:public_id>/message", views.post_message, name="chat-message"),
]
