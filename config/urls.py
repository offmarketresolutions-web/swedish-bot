"""Root URL configuration."""
from django.contrib import admin
from django.urls import include, path

from chat import views as chat_views

# Nordland-brand the admin site chrome (title bar, header text, index heading).
admin.site.site_header = "Nordland VVS — Administration"
admin.site.site_title = "Nordland VVS Admin"
admin.site.index_title = "Knowledge base, agents & CRM"

urlpatterns = [
    path("admin/", admin.site.urls),
    # Django's set_language view — the POST target for the dashboard language switcher.
    # LocaleMiddleware is already installed; without this route there is no way to CHANGE
    # the language, which is why the sv translation was unreachable even once compiled.
    path("i18n/", include("django.conf.urls.i18n")),
    path("api/chat/", include("chat.urls")),
    path("api/prefill/<str:token>", chat_views.prefill, name="chat-prefill"),
    path("api/voice/", include("voice.urls")),
    path("dashboard/", include("dashboard.urls")),
    path("", include("core.urls")),
]
