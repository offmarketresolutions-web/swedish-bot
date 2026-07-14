from django.urls import path

from dashboard import views, voice_views

urlpatterns = [
    # Voice / phone control plane
    path("voice/", voice_views.voice_phone, name="dash-voice-phone"),
    path("voice/publish", voice_views.voice_publish, name="dash-voice-publish"),
    path("voice/credentials/", voice_views.voice_credentials, name="dash-voice-credentials"),
    path("voice/calls/<str:call_id>/fetch", voice_views.voice_fetch_conversation,
         name="dash-voice-fetch"),
    path("", views.overview, name="dash-overview"),
    path("analytics/", views.analytics_dashboard, name="dash-analytics"),
    path("sessions/", views.session_list, name="dash-sessions"),
    path("sessions/<int:pk>/", views.session_detail, name="dash-session"),
    path("sessions/<int:pk>/replica", views.conversation_replica, name="dash-session-replica"),
    path("customers/", views.customer_list, name="dash-customers"),
    path("customers/<int:pk>/", views.customer_detail, name="dash-customer"),
    path("customers/<int:pk>/files/upload", views.customer_file_upload, name="dash-customer-file-upload"),
    path("files/<int:pk>/", views.serve_customer_file, name="dash-file"),
    # Machine documentation pop-up (PDF overlay) + integration settings
    path("kb/machine/<int:pk>/docs", views.machine_docs, name="dash-machine-docs"),
    path("settings/", views.integration_settings, name="dash-settings"),
    # Service area (plan S5)
    path("settings/service-area/", views.service_area_settings, name="dash-service-area"),
    path("settings/service-area/add", views.service_area_add, name="dash-service-area-add"),
    path("settings/service-area/<int:pk>/delete", views.service_area_delete, name="dash-service-area-delete"),
    path("settings/service-area/<int:pk>/toggle", views.service_area_toggle, name="dash-service-area-toggle"),
    path("settings/service-area/<int:pk>/export", views.service_area_export, name="dash-service-area-export"),
    path("settings/service-area/test", views.service_area_test, name="dash-service-area-test"),
    # Agent Config (HTMX inline save)
    path("agents/", views.agent_config, name="dash-agents"),
    path("guardrails/", views.guardrails_page, name="dash-guardrails"),
    path("guardrails/<slug:role>/add", views.guardrail_add, name="dash-guardrail-add"),
    path("guardrails/<int:pk>/delete", views.guardrail_delete, name="dash-guardrail-delete"),
    path("guardrails/<int:pk>/toggle", views.guardrail_toggle, name="dash-guardrail-toggle"),
    path("agents/<int:pk>/save", views.agent_save, name="dash-agent-save"),
    path("agents/<int:pk>/assist", views.agent_prompt_assist, name="dash-agent-assist"),
    path("agents/<slug:role>/", views.agent_detail, name="dash-agent-detail"),
    # Flow builder (Vapi-style editable canvas) + its JSON save
    path("flow/", views.flow_canvas, name="dash-flow"),
    path("flow/save", views.flow_save, name="dash-flow-save"),
    # KB landing (vendors grouped) + brand + machine pages
    path("kb/", views.kb_manager, name="dash-kb"),
    path("kb/categories/", views.category_list, name="dash-kb-categories"),
    path("kb/category/new/", views.category_new, name="dash-kb-category-new"),
    path("kb/category/<int:pk>/", views.category_detail, name="dash-kb-category"),
    path("kb/vendor/new/", views.vendor_new, name="dash-kb-vendor-new"),
    path("kb/vendor/<int:pk>/", views.kb_vendor, name="dash-kb-vendor"),
    path("kb/vendor/<int:pk>/delete", views.vendor_delete, name="dash-kb-vendor-delete"),
    path("kb/machine/new/", views.machine_new, name="dash-kb-machine-new"),
    # Full machine page (the machine link target — the user asked for a real page).
    path("kb/machine/<int:pk>/", views.kb_machine_page, name="dash-kb-machine-page"),
    path("kb/machine/<int:pk>/delete", views.machine_delete, name="dash-kb-machine-delete"),
    # Inline PDF preview/serve for an uploaded manual.
    path("kb/document/<int:pk>/pdf", views.serve_document, name="dash-kb-doc"),
    # PDF upload/replace + notes (HTMX; targets #kb-panel on the machine page).
    path("kb/machine/<int:pk>/upload", views.kb_doc_upload, name="dash-kb-upload"),
    path("kb/machine/<int:pk>/note", views.kb_note_add, name="dash-kb-note"),
    path("kb/machine/<int:pk>/notes", views.kb_machine_notes, name="dash-kb-notes"),
    path("kb/note/<int:pk>/delete", views.kb_note_delete, name="dash-kb-note-delete"),
    path("kb/vendor/<int:pk>/notes", views.kb_vendor_notes, name="dash-kb-vendor-notes"),
    # Site FAQ
    path("faq/", views.faq_list, name="dash-faq"),
    path("faq/category/new/", views.faq_entry_new, name="dash-faq-entry-new"),
    path("faq/site/new/", views.site_faq_new, name="dash-site-faq-new"),
    path("faq/pending/<str:kind>/<int:pk>/approve", views.faq_approve, name="dash-faq-approve"),
    path("faq/pending/<str:kind>/<int:pk>/reject", views.faq_reject, name="dash-faq-reject"),
    # CRM create
    path("customers/new/", views.customer_new, name="dash-customer-new"),
]
