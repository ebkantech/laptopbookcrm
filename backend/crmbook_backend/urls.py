from django.contrib import admin
from django.urls import include, path
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
    path('api/dashboard/', include('dashboard.urls')),
]
