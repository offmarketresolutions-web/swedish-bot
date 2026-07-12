"""Dashboard-managed secrets (ported pattern from budtender/voice/dashboard/models.py).

One row per credential the app itself needs to reach Vapi / Meta / n8n. ``credentials.set_credential``
writes the row AND live-applies it to ``os.environ`` + ``settings`` (no redeploy). The plaintext
value never leaves this DB table / the operator's browser — provider keys that only Vapi needs
(ElevenLabs/Deepgram) live in Vapi's own dashboard, not here.
"""

from __future__ import annotations

from django.db import models


class Credential(models.Model):
    name = models.CharField(max_length=64, unique=True)  # ENV/settings var name
    value = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"Credential<{self.name}>"
