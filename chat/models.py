"""Thin append-only transcript (plan §7). All structured reporting lives on
crm.Session, not here — Conversation/Message are just the chat log + audit trail.
"""
from __future__ import annotations

import uuid

from django.db import models

from core.enums import LANG_CHOICES


class Conversation(models.Model):
    # Anonymous session token the embedded widget uses (no auth, no PII here).
    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    language = models.CharField(max_length=5, choices=LANG_CHOICES, default="en")
    status = models.CharField(max_length=16, default="open")  # open | closed
    # Orchestrator working state (transient; the canonical copy is flushed to Session).
    case_state = models.JSONField(default=dict, blank=True)
    started_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return f"Conversation<{self.pk}> {self.public_id}"


class Message(models.Model):
    ROLE_CHOICES = [("user", "User"), ("assistant", "Assistant"), ("tool", "Tool")]

    conversation = models.ForeignKey(
        Conversation, on_delete=models.CASCADE, related_name="messages"
    )
    role = models.CharField(max_length=16, choices=ROLE_CHOICES)
    content = models.TextField(blank=True)
    # Tool turns (role="tool"): vision extraction, machine match, etc.
    tool_name = models.CharField(max_length=64, blank=True)
    tool_args = models.JSONField(null=True, blank=True)
    tool_result = models.JSONField(null=True, blank=True)
    # Nameplate / display photo uploaded by the customer (plan §8, crit 0.11).
    image = models.ImageField(upload_to="photos/", null=True, blank=True)
    # Optional per-message diagnostics (specialist confidence, model used).
    confidence = models.FloatField(null=True, blank=True)
    model = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [models.Index(fields=["conversation", "created_at"])]

    def __str__(self):
        return f"Message<{self.pk}> {self.tool_name or self.role}"
