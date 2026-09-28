from django.conf import settings
from django.contrib import admin
from django.http import Http404, HttpResponse
from django.urls import include, path, re_path
from django.views.static import serve as serve_static
from rest_framework_simplejwt.views import TokenRefreshView

from accounts.views import LogoutView, ThrottledTokenObtainPairView

urlpatterns = [
    path('admin/', admin.site.urls),

    path('api/auth/token/', ThrottledTokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('api/auth/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('api/auth/logout/', LogoutView.as_view(), name='logout'),

    path('api/', include('accounts.urls')),
    path('api/', include('catalog.urls')),
    path('api/', include('parties.urls')),
    path('api/', include('sales.urls')),
    path('api/', include('rentals.urls')),
    path('api/', include('repairs.urls')),
    path('api/', include('accounting.urls')),
    path('api/', include('broadcast.urls')),
    path('api/', include('warranty.urls')),
    path('api/', include('portal.urls')),
    path('api/', include('reports.urls')),
    path('api/dashboard/', include('dashboard.urls')),
]

# --------------------------------------------------------------------- #
# Single-server dev convenience: serve the already-built frontend
# (frontend/dist/, built via `npm run build`) straight from Django, so
# `python manage.py runserver` alone is enough to run the whole app at
# http://127.0.0.1:8000/ -- no separate `npm run dev` process needed for
# day-to-day use. Not wired for production (django.views.static.serve is
# a dev-only helper); a real deployment should serve frontend/dist via
# Nginx/whitenoise instead. Rebuild the frontend (`npm run build`) after
# any frontend change, then just refresh the browser -- no server restart
# needed.
# --------------------------------------------------------------------- #
if settings.DEBUG:
    FRONTEND_DIST = settings.BASE_DIR.parent / "frontend" / "dist"

    def spa_view(request, path=""):
        candidate = FRONTEND_DIST / path
        if path and candidate.is_file():
            return serve_static(request, path, document_root=FRONTEND_DIST)
        index_path = FRONTEND_DIST / "index.html"
        if not index_path.exists():
            raise Http404(
                "frontend/dist/index.html not found -- run `npm run build` in "
                "frontend/ at least once before loading this in the browser."
            )
        return HttpResponse(index_path.read_text(encoding="utf-8"))

    # Must stay LAST -- it matches every path not already claimed by
    # admin/ or api/ above, including /portal/..., /rental-approval/...
    # etc. (App.jsx's own client-side routing handles those).
    urlpatterns += [
        re_path(r'^(?P<path>.*)$', spa_view),
    ]
