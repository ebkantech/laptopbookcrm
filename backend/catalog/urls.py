from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import AddStockView, PartViewSet, ProductViewSet, ServiceViewSet, StockLocationView, StockPointViewSet, StockSerialViewSet

router = DefaultRouter()
router.register("stock-points", StockPointViewSet, basename="stockpoint")
router.register("products", ProductViewSet, basename="product")
router.register("parts", PartViewSet, basename="part")
router.register("services", ServiceViewSet, basename="service")
router.register("stock-serials", StockSerialViewSet, basename="stockserial")

from .category_views import ProductCategoryViewSet  # noqa: E402
router.register("product-categories", ProductCategoryViewSet, basename="productcategory")

from .cost_views import BulkCostView, CostReviewView, PartCostView, VariantCostView
from .purchase_views import SupplierComparisonView, SupplierHistoryView, SupplierPayView, TagStockView, UntaggedUnitsView

urlpatterns = router.urls + [
    path("costs/review/", CostReviewView.as_view(), name="cost-review"),
    path("costs/variant/<int:pk>/", VariantCostView.as_view(), name="variant-cost"),
    path("costs/part/<int:pk>/", PartCostView.as_view(), name="part-cost"),
    path("costs/bulk/", BulkCostView.as_view(), name="cost-bulk"),
    path("inventory/add-stock/", AddStockView.as_view(), name="add-stock"),
    path("inventory/stock/<int:pk>/location/", StockLocationView.as_view(), name="stock-location"),
    path("purchases/supplier/<int:pk>/", SupplierHistoryView.as_view(), name="supplier-history"),
    path("purchases/supplier/<int:pk>/pay/", SupplierPayView.as_view(), name="supplier-pay"),
    path("purchases/tag/", TagStockView.as_view(), name="purchase-tag"),
    path("purchases/untagged/", UntaggedUnitsView.as_view(), name="purchase-untagged"),
    path("reports/supplier-comparison/", SupplierComparisonView.as_view(), name="supplier-comparison"),
]
