"""Fetch + persist the authoritative full conversation for a call from Vapi.

``python manage.py full_conversation <call_id>``.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from core.services import vapi
from voice import callfetch


class Command(BaseCommand):
    help = "Fetch GET /call/{id} from Vapi and persist transcript + tool calls."

    def add_arguments(self, parser):
        parser.add_argument("call_id")

    def handle(self, *args, **opts):
        if not vapi.configured():
            raise CommandError("VAPI_PRIVATE_KEY not configured — cannot fetch a live call.")
        out = callfetch.fetch_full_conversation(opts["call_id"])
        self.stdout.write(self.style.SUCCESS(
            f"persisted call={out['persisted']['voice_call']} "
            f"tool_calls={out['persisted']['tool_calls']}"))
