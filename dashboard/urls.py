from django.urls import path

from dashboard import views

urlpatterns = [
    path("", views.overview, name="dash-overview"),
    path("sessions/", views.session_list, name="dash-sessions"),
    path("sessions/<int:pk>/", views.session_detail, name="dash-session"),
    path("customers/", views.customer_list, name="dash-customers"),
    path("customers/<int:pk>/", views.customer_detail, name="dash-customer"),
    path("files/<int:pk>/", views.serve_customer_file, name="dash-file"),
]
