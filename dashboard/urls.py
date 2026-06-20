from django.urls import path

from dashboard import views

urlpatterns = [
    path("", views.overview, name="dash-overview"),
    path("sessions/", views.session_list, name="dash-sessions"),
    path("sessions/<int:pk>/", views.session_detail, name="dash-session"),
]
