from django.contrib import admin

from .models import Conversation, Message


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ("chat_id", "channel", "session_id", "last_message_at")


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ("created_at", "direction", "text_short", "job_run")
    list_filter = ("direction",)
    search_fields = ("text",)

    @admin.display(description="text")
    def text_short(self, message):
        return message.text[:100]
