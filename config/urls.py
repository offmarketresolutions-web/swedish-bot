"""Root URL configuration."""
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/chat/", include("chat.urls")),
    path("dashboard/", include("dashboard.urls")),
    path("", include("core.urls")),
]
