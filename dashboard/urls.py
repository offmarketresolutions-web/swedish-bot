from django.urls import path

from dashboard import views

urlpatterns = [
    path("", views.overview, name="dash-overview"),
    path("analytics/", views.analytics_dashboard, name="dash-analytics"),
    path("sessions/", views.session_list, name="dash-sessions"),
    path("sessions/<int:pk>/", views.session_detail, name="dash-session"),
    path("sessions/<int:pk>/replica", views.conversation_replica, name="dash-session-replica"),
    path("customers/", views.customer_list, name="dash-customers"),
    path("customers/<int:pk>/", views.customer_detail, name="dash-customer"),
    path("files/<int:pk>/", views.serve_customer_file, name="dash-file"),
    # Agent Config (HTMX inline save)
    path("agents/", views.agent_config, name="dash-agents"),
    path("agents/<int:pk>/save", views.agent_save, name="dash-agent-save"),
    path("agents/<int:pk>/assist", views.agent_prompt_assist, name="dash-agent-assist"),
    path("agents/<slug:role>/", views.agent_detail, name="dash-agent-detail"),
    # Flow builder (Vapi-style editable canvas) + its JSON save
    path("flow/", views.flow_canvas, name="dash-flow"),
    path("flow/save", views.flow_save, name="dash-flow-save"),
    # KB landing (vendors grouped) + brand + machine pages
    path("kb/", views.kb_manager, name="dash-kb"),
    path("kb/categories/", views.category_list, name="dash-kb-categories"),
    path("kb/category/<int:pk>/", views.category_detail, name="dash-kb-category"),
    path("kb/vendor/new/", views.vendor_new, name="dash-kb-vendor-new"),
    path("kb/vendor/<int:pk>/", views.kb_vendor, name="dash-kb-vendor"),
    path("kb/machine/new/", views.machine_new, name="dash-kb-machine-new"),
    # Full machine page (the machine link target — the user asked for a real page).
    path("kb/machine/<int:pk>/", views.kb_machine_page, name="dash-kb-machine-page"),
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
    # CRM create
    path("customers/new/", views.customer_new, name="dash-customer-new"),
]
