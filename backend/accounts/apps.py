from django.apps import AppConfig


class AccountsConfig(AppConfig):
    name = 'accounts'

    def ready(self):
        # Staff Activity Logs: model signals feeding the per-request scope
        from .activity import connect_signals
        connect_signals()
