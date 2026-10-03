from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import AddStockView, PartViewSet, ProductViewSet, ServiceViewSet, StockLocationView, StockPointViewSet

router = DefaultRouter()
router.register("stock-points", StockPointViewSet, basename="stockpoint")
router.register("products", ProductViewSet, basename="product")
router.register("parts", PartViewSet, basename="part")
router.register("services", ServiceViewSet, basename="service")

urlpatterns = router.urls + [
    path("inventory/add-stock/", AddStockView.as_view(), name="add-stock"),
    path("inventory/stock/<int:pk>/location/", StockLocationView.as_view(), name="stock-location"),
]
