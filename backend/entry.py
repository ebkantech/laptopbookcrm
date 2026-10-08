import os

from django.core.wsgi import get_wsgi_application
from workers import wsgi

os.environ.setdefault(
    "DJANGO_SETTINGS_MODULE",
    "crmbook_backend.settings",
)

app = get_wsgi_application()

Default = wsgi.entrypoint(app)
