from django.urls import path

from . import views

urlpatterns = [
    path("copilot/status/", views.StatusView.as_view(), name="copilot-status"),
    path("copilot/chat/", views.ChatView.as_view(), name="copilot-chat"),
    path("copilot/tasks/", views.TasksView.as_view(), name="copilot-tasks"),
    path("copilot/conversations/", views.ConversationsView.as_view(), name="copilot-conversations"),
    path("copilot/conversations/<int:pk>/", views.ConversationDetailView.as_view(), name="copilot-conversation"),
    path("copilot/actions/<int:pk>/confirm/", views.ConfirmActionView.as_view(), name="copilot-action-confirm"),
    path("copilot/actions/<int:pk>/reject/", views.RejectActionView.as_view(), name="copilot-action-reject"),
    path("copilot/inbox/", views.InboxListView.as_view(), name="copilot-inbox"),
    path("copilot/inbox/dismiss/", views.DismissView.as_view(), name="copilot-inbox-dismiss"),
    path("copilot/drafts/", views.DraftCreateView.as_view(), name="copilot-drafts"),
    path("copilot/drafts/<int:pk>/send/", views.DraftSendView.as_view(), name="copilot-draft-send"),
]
