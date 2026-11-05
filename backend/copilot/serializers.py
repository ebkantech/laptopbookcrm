from rest_framework import serializers

from parties.models import Message

from .models import ChatMessage, Conversation, ProposedAction, ReplyDraft


class ChatMessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChatMessage
        fields = ["id", "role", "text", "created_at"]


class ProposedActionSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProposedAction
        fields = ["id", "action_key", "label", "target", "body", "status", "result", "verification", "created_at"]


class ConversationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Conversation
        fields = ["id", "title", "created_at", "updated_at"]


class InboxMessageSerializer(serializers.ModelSerializer):
    party_name = serializers.CharField(source="party.name")
    draft = serializers.SerializerMethodField()

    class Meta:
        model = Message
        fields = ["id", "party", "party_name", "channel", "body", "at", "draft"]

    def get_draft(self, obj):
        row = obj.copilot_drafts.filter(status=ReplyDraft.PENDING).first()
        return ReplyDraftSerializer(row).data if row else None


class ReplyDraftSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReplyDraft
        fields = ["id", "party", "message", "body", "sources", "status", "edited", "created_at"]
