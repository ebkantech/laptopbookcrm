"""
Product categories, edited at run time (Inventory -> Add stock -> Edit
categories). Everyone who can open Add stock reads them; only the Owner /
Super Admin or an Admin (accounts.staff.is_staff_admin) changes them.

A category or field key is made once from its name and never changes, so
renaming never disconnects products already saved under it. A category
that products use can't be deleted -- it's switched off (hidden from Add
stock) instead, and can be switched back on.
"""
import re

from django.db.models import Max
from django.utils.text import slugify
from rest_framework import permissions, serializers, status, viewsets
from rest_framework.response import Response

from accounts import activity
from accounts.staff import is_staff_admin

from .models import Product, ProductCategory

FIELD_TYPES = ("text", "choice", "long")
MAX_FIELDS = 30
MAX_OPTIONS = 30
PREFIX_RE = re.compile(r"^[A-Z0-9]{1,5}(-[A-Z0-9]{1,5})?$")


def _key(text, taken, limit=20):
    base = slugify(text).replace("-", "_")[:limit].strip("_") or "item"
    key, n = base, 2
    while key in taken:
        suffix = f"_{n}"
        key, n = f"{base[:limit - len(suffix)]}{suffix}", n + 1
    return key


def _strings(value, field, limit, max_len=40):
    if value in (None, ""):
        return []
    if not isinstance(value, list):
        raise serializers.ValidationError(f"{field}: send a list.")
    out = []
    for item in value:
        text = re.sub(r"\s+", " ", str(item)).strip()[:max_len]
        if text and text.lower() not in (o.lower() for o in out):
            out.append(text)
    if len(out) > limit:
        raise serializers.ValidationError(f"{field}: at most {limit}.")
    return out


class ProductCategorySerializer(serializers.ModelSerializer):
    product_count = serializers.SerializerMethodField()

    class Meta:
        model = ProductCategory
        fields = ["id", "key", "name", "icon", "position", "is_active", "name_label", "brand_required", "show_condition",
                  "code_prefix", "fields", "product_count", "updated_at"]
        read_only_fields = ["key", "updated_at"]

    def get_product_count(self, obj):
        counts = self.context.get("counts")
        return counts.get(obj.key, 0) if counts is not None else Product.objects.filter(category=obj.key).count()

    def validate_name(self, value):
        value = re.sub(r"\s+", " ", value).strip()
        if not value:
            raise serializers.ValidationError("Enter the category name.")
        clash = ProductCategory.objects.filter(name__iexact=value)
        if self.instance:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise serializers.ValidationError(f"There's already a category called {value}.")
        return value

    def validate_icon(self, value):
        return value if value in ProductCategory.ICONS else "package"

    def validate_name_label(self, value):
        return re.sub(r"\s+", " ", value).strip() or "Model / product name"

    def validate_code_prefix(self, value):
        value = (value or "").strip().upper()
        if not PREFIX_RE.match(value):
            raise serializers.ValidationError("Use capital letters / digits, e.g. VC-ACC or VC-FUR.")
        return value

    def validate_fields(self, value):
        if not isinstance(value, list):
            raise serializers.ValidationError("Send the fields as a list.")
        if len(value) > MAX_FIELDS:
            raise serializers.ValidationError(f"A category can have at most {MAX_FIELDS} fields.")
        old = {f["key"] for f in (self.instance.fields if self.instance else [])}
        taken, out, labels = set(), [], set()
        for n, raw in enumerate(value, start=1):
            if not isinstance(raw, dict):
                raise serializers.ValidationError(f"Field {n} isn't valid.")
            label = re.sub(r"\s+", " ", str(raw.get("label") or "")).strip()[:40]
            if not label:
                raise serializers.ValidationError(f"Field {n} needs a name.")
            if label.lower() in labels:
                raise serializers.ValidationError(f"Two fields are called “{label}”.")
            labels.add(label.lower())
            # an existing field keeps its key (its saved values stay attached); a new one gets one from its name
            key = str(raw.get("key") or "")
            if key not in old or key in taken:
                key = _key(label, taken | old)
            taken.add(key)
            ftype = raw.get("type") if raw.get("type") in FIELD_TYPES else "text"
            options = _strings(raw.get("options"), f"“{label}” choices", MAX_OPTIONS)
            if ftype == "choice" and len(options) < 2:
                raise serializers.ValidationError(f"“{label}” is a choice: give at least two options.")
            out.append({
                "key": key, "label": label, "type": ftype, "required": bool(raw.get("required")),
                "options": options if ftype == "choice" else [],
                "suggest": _strings(raw.get("suggest"), f"“{label}” suggestions", MAX_OPTIONS) if ftype == "text" else [],
                "placeholder": str(raw.get("placeholder") or "").strip()[:80],
                "summary": bool(raw.get("summary")),
            })
        return out

    def create(self, validated):
        validated["key"] = _key(validated["name"], set(ProductCategory.objects.values_list("key", flat=True)))
        validated.setdefault("position", (ProductCategory.objects.aggregate(m=Max("position"))["m"] or 0) + 1)
        return super().create(validated)


class CanEditCategories(permissions.BasePermission):
    message = "Only the Owner or an Admin can change product categories."

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated or hasattr(user, "customer_profile"):
            return False
        if request.method in permissions.SAFE_METHODS:
            return True
        return user.is_superuser or is_staff_admin(user)


class ProductCategoryViewSet(viewsets.ModelViewSet):
    """GET/POST /api/product-categories/, PATCH/DELETE /api/product-categories/<id>/"""
    serializer_class = ProductCategorySerializer
    permission_classes = [permissions.IsAuthenticated, CanEditCategories]
    pagination_class = None
    http_method_names = ["get", "post", "patch", "delete"]

    def get_queryset(self):
        qs = ProductCategory.objects.all()
        if self.request.query_params.get("active") == "1":
            qs = qs.filter(is_active=True)
        return qs

    def get_serializer_context(self):
        from django.db.models import Count

        context = super().get_serializer_context()
        context["counts"] = dict(Product.objects.exclude(category="").values("category").annotate(n=Count("id")).values_list("category", "n"))
        return context

    def perform_create(self, serializer):
        category = serializer.save()
        activity.note(category, "category-added", f"Product category {category.name} added")

    def perform_update(self, serializer):
        category = serializer.save()
        activity.note(category, "category-edited", f"Product category {category.name} edited")

    def destroy(self, request, *args, **kwargs):
        category = self.get_object()
        if Product.objects.filter(category=category.key).exists():
            category.is_active = False
            category.save(update_fields=["is_active", "updated_at"])
            return Response({**self.get_serializer(category).data,
                             "detail": f"{category.name} has products, so it was switched off instead of deleted."})
        category.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
