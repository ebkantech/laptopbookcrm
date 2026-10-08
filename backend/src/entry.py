import os
import sys

from workers import wsgi

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

os.environ.setdefault(
    "DJANGO_SETTINGS_MODULE",
    "crmbook_backend.settings",
)

from django.core.wsgi import get_wsgi_application

app = get_wsgi_application()

Default = wsgi.entrypoint(app)
