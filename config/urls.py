"""Root URL configuration."""
from django.contrib import admin
from django.urls import include, path

# Nordland-brand the admin site chrome (title bar, header text, index heading).
admin.site.site_header = "Nordland VVS — Administration"
admin.site.site_title = "Nordland VVS Admin"
admin.site.index_title = "Knowledge base, agents & CRM"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/chat/", include("chat.urls")),
    path("api/voice/", include("voice.urls")),
    path("dashboard/", include("dashboard.urls")),
    path("", include("core.urls")),
]
