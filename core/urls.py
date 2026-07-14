from django.urls import path

from core import views

urlpatterns = [
    path("healthz", views.healthz, name="healthz"),
    path("", views.widget_demo, name="home"),  # root = the live chat widget
    path("widget-demo", views.widget_demo, name="widget-demo"),
    path("demo/homepage", views.homepage_demo, name="homepage-demo"),
    path("demo/form", views.demo_form, name="demo-form"),
    path("playground", views.playground, name="playground"),
]
