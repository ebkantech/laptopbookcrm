"""
Staff Copilot records.

Nothing here holds business data of its own: a copilot action is carried out
through the CRM's normal API as the signed-in staff member (copilot.dispatch),
so these rows only remember what was asked, proposed, confirmed and sent.
"""
from django.conf import settings
from django.db import models

from parties.models import Message, Party


class Conversation(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="copilot_conversations")
    title = models.CharField(max_length=120, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]


class ChatMessage(models.Model):
    USER, ASSISTANT = "user", "assistant"
    ROLE_CHOICES = [(USER, "Staff"), (ASSISTANT, "Copilot")]

    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="messages")
    role = models.CharField(max_length=10, choices=ROLE_CHOICES)
    text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]


class ProposedAction(models.Model):
    """A change the copilot prepared. It runs only when its owner confirms it."""
    PROPOSED, EXECUTING, DONE, FAILED, REJECTED, EXPIRED = "proposed", "executing", "done", "failed", "rejected", "expired"
    STATUS_CHOICES = [
        (PROPOSED, "Waiting for confirmation"), (EXECUTING, "Running"), (DONE, "Done"),
        (FAILED, "Failed"), (REJECTED, "Rejected"), (EXPIRED, "Expired"),
    ]

    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="actions")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="copilot_actions")
    action_key = models.CharField(max_length=40)
    label = models.CharField(max_length=120)
    target = models.CharField(max_length=240, blank=True, help_text="Read from the CRM by the server, not written by the model.")
    method = models.CharField(max_length=6)
    path = models.CharField(max_length=200)
    body = models.JSONField(default=dict, blank=True)
    # The role and store the proposal was made under: confirming under another is refused.
    active_role = models.CharField(max_length=20, blank=True)
    active_store = models.CharField(max_length=20, blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=PROPOSED)
    result = models.CharField(max_length=500, blank=True)
    verification = models.CharField(max_length=240, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["created_at", "id"]


class ReplyDraft(models.Model):
    """A suggested answer to a customer message. Only a staff member can send it."""
    PENDING, SENDING, SENT, DISMISSED = "pending", "sending", "sent", "dismissed"
    STATUS_CHOICES = [(PENDING, "Waiting for review"), (SENDING, "Sending"), (SENT, "Sent"), (DISMISSED, "Dismissed")]

    party = models.ForeignKey(Party, on_delete=models.CASCADE, related_name="copilot_drafts")
    message = models.ForeignKey(Message, on_delete=models.CASCADE, related_name="copilot_drafts")
    body = models.TextField()
    sources = models.JSONField(default=list, blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=PENDING)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    sent_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    sent_message = models.ForeignKey(Message, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    edited = models.BooleanField(default=False, help_text="Staff changed the suggested text before sending.")
    created_at = models.DateTimeField(auto_now_add=True)
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]


class DocChunk(models.Model):
    """
    Searchable text for one CRM record, with its embedding. It is only a
    pointer for finding records: search results are always re-read through the
    CRM as the person asking (copilot.search), so this table never decides who
    sees what, and stale text never reaches an answer.
    """
    source_type = models.CharField(max_length=20)
    source_id = models.PositiveBigIntegerField()
    content = models.TextField()
    content_hash = models.CharField(max_length=64)
    model = models.CharField(max_length=120)
    embedding = models.JSONField()
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["source_type", "source_id"], name="copilot_chunk_unique_source")]
