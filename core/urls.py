from django.urls import path

from core import views

urlpatterns = [
    path("healthz", views.healthz, name="healthz"),
    path("widget-demo", views.widget_demo, name="widget-demo"),
]
