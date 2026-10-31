from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from catalog.models import StockPoint
from catalog.status import require_active

from .models import ActivityLog, NotificationRule, Permission, Role, StaffNotification, User
from .staff import is_staff_admin
from .store_scope import sees_all_stores


class PermissionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Permission
        fields = ["id", "codename", "description"]


class RoleSerializer(serializers.ModelSerializer):
    """Read shape -- nested permission objects plus a plain codename list for easy UI comparison."""
    permissions = PermissionSerializer(many=True, read_only=True)
    permission_codes = serializers.SlugRelatedField(
        source="permissions", many=True, read_only=True, slug_field="codename"
    )

    class Meta:
        model = Role
        fields = ["id", "slug", "label", "permissions", "permission_codes"]


class RoleWriteSerializer(serializers.ModelSerializer):
    """
    Task 1: create/update shape for the custom-roles UI. Takes a flat
    list of permission codenames (not nested objects) so the frontend
    can just POST/PATCH the checkbox state directly. The "owner" slug
    stays reserved -- it's tied to the superuser flag, not to any row
    a role-editor screen should be able to create or repoint another
    role onto (see accounts.views.UserViewSet.set_role, which already
    refuses to assign it the same way).
    """
    # NOT SlugField -- Permission.codename values are dotted ("cashbook.view",
    # "roles.manage"), which fails Django's slug regex (letters/digits/
    # hyphen/underscore only, no dots). The model field is also declared
    # SlugField but that's never enforced since seed_demo creates rows via
    # .save(), which skips field validators; a DRF serializer field does
    # NOT skip them, so this must stay a plain CharField or every real
    # toggle from the UI 400s. _resolve_permissions() below is what
    # actually validates each code against real Permission rows.
    permission_codes = serializers.ListField(child=serializers.CharField(max_length=64), required=False, write_only=True)

    class Meta:
        model = Role
        fields = ["id", "slug", "label", "permission_codes"]

    def validate_slug(self, value):
        if value == "owner":
            raise serializers.ValidationError("The \"owner\" slug is reserved for the built-in Owner role.")
        return value

    def _resolve_permissions(self, codes):
        perms = list(Permission.objects.filter(codename__in=codes))
        missing = set(codes) - {p.codename for p in perms}
        if missing:
            raise serializers.ValidationError({"permission_codes": f"Unknown permission codename(s): {', '.join(sorted(missing))}"})
        return perms

    def create(self, validated_data):
        codes = validated_data.pop("permission_codes", [])
        role = Role.objects.create(**validated_data)
        if codes:
            role.permissions.set(self._resolve_permissions(codes))
        return role

    def update(self, instance, validated_data):
        if instance.slug == "owner":
            raise serializers.ValidationError("The Owner role can't be edited here -- it's tied to the superuser account itself.")
        codes = validated_data.pop("permission_codes", None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        if codes is not None:
            instance.permissions.set(self._resolve_permissions(codes))
        return instance


class NotificationRuleSerializer(serializers.ModelSerializer):
    role_label = serializers.CharField(source="role.label", read_only=True)
    event_label = serializers.CharField(source="get_event_key_display", read_only=True)

    class Meta:
        model = NotificationRule
        fields = ["id", "event_key", "event_label", "role", "role_label", "via_email", "via_whatsapp", "via_inapp"]


class StaffNotificationSerializer(serializers.ModelSerializer):
    """The bell dropdown's own shape -- read-only, always scoped to the requesting user (see StaffNotificationViewSet)."""
    event_label = serializers.CharField(source="get_event_key_display", read_only=True)

    class Meta:
        model = StaffNotification
        fields = ["id", "event_key", "event_label", "subject", "body", "created_at", "read_at"]


class UserSerializer(serializers.ModelSerializer):
    role_label = serializers.CharField(source="role.label", read_only=True)
    role_slug = serializers.CharField(source="role.slug", read_only=True)
    permissions = serializers.SerializerMethodField()
    # Store Location -- read-only here; only UserViewSet.set_store changes it.
    stock_point_name = serializers.CharField(source="stock_point.name", read_only=True, default=None)
    stock_point_kind = serializers.CharField(source="stock_point.kind", read_only=True, default=None)
    sees_all_stores = serializers.SerializerMethodField()
    can_manage_store_status = serializers.SerializerMethodField()
    # Staff Activity Logs (accounts.activity): may this account open OTHER people's logs,
    # its own work timeline, and may the REQUESTING account open this one's
    can_view_staff_logs = serializers.SerializerMethodField()
    can_view_own_activity = serializers.SerializerMethodField()
    can_view_activity = serializers.SerializerMethodField()
    # store-wise Profit & Loss (reports.profit_loss); which stores is StoreScope's call
    can_view_profit_loss = serializers.SerializerMethodField()
    # Accounting -> Expenses (accounting.expenses.can_manage_expenses)
    can_manage_expenses = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id", "username", "first_name", "last_name", "email", "phone",
            "role", "role_label", "role_slug", "permissions", "is_superuser", "is_active",
            "stock_point", "stock_point_name", "stock_point_kind", "sees_all_stores", "can_manage_store_status",
            "can_view_staff_logs", "can_view_own_activity", "can_view_activity", "can_view_profit_loss",
            "can_manage_expenses",
        ]
        read_only_fields = ["stock_point", "is_active"]

    def get_sees_all_stores(self, obj):
        return sees_all_stores(obj)

    def get_can_manage_store_status(self, obj):
        # the backend rule (catalog.status) the Store Locator shows status for
        from catalog.status import can_manage_status
        return can_manage_status(obj)

    def get_can_view_staff_logs(self, obj):
        from .activity import can_view_staff_logs
        return can_view_staff_logs(obj)

    def get_can_view_own_activity(self, obj):
        from .activity import can_view_own_logs
        return can_view_own_logs(obj)

    def get_can_view_profit_loss(self, obj):
        from reports.profit_loss import can_view_profit_loss
        return can_view_profit_loss(obj)

    def get_can_manage_expenses(self, obj):
        from accounting.expenses import can_manage_expenses
        return can_manage_expenses(obj)

    def get_can_view_activity(self, obj):
        from .activity import can_view_logs_of
        request = self.context.get("request")
        return bool(request and can_view_logs_of(request.user, obj))

    def get_permissions(self, obj):
        if obj.is_superuser:
            return list(Permission.objects.values_list("codename", flat=True))
        if not obj.role:
            return []
        return list(obj.role.permissions.values_list("codename", flat=True))

    def to_representation(self, obj):
        data = super().to_representation(obj)
        request = self.context.get("request")
        viewer = getattr(request, "user", None)
        if viewer is None or not viewer.is_authenticated:
            return data
        if viewer.pk == obj.pk or is_staff_admin(viewer):
            # admins also see whether the account can sign in yet
            data["password_set"] = obj.has_usable_password()
            data["last_login"] = obj.last_login
            data["date_joined"] = obj.date_joined
        else:
            # a colleague's contact details are for administrators only
            data.pop("email", None)
            data.pop("phone", None)
        return data


class StaffWriteSerializer(serializers.ModelSerializer):
    """
    Create / edit a staff account (UserViewSet). Only these fields are
    writable -- is_superuser, is_staff, groups and permissions can't be
    mass-assigned. Role and Store Location are re-checked in the view
    against the acting administrator (accounts.staff).
    """
    role = serializers.PrimaryKeyRelatedField(queryset=Role.objects.all(), allow_null=True, required=False)
    stock_point = serializers.PrimaryKeyRelatedField(queryset=StockPoint.objects.all(), allow_null=True, required=False)
    password = serializers.CharField(write_only=True, required=False, allow_blank=True, trim_whitespace=False, style={"input_type": "password"})
    password_confirm = serializers.CharField(write_only=True, required=False, allow_blank=True, trim_whitespace=False)

    class Meta:
        model = User
        fields = ["username", "first_name", "last_name", "email", "phone", "role", "stock_point", "is_active",
                  "password", "password_confirm"]
        extra_kwargs = {"first_name": {"required": True, "allow_blank": False}}

    def validate_username(self, value):
        value = value.strip()
        clash = User.objects.filter(username__iexact=value)
        if self.instance:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise serializers.ValidationError("That username is already taken.")
        return value

    def validate_email(self, value):
        value = (value or "").strip()
        if value:
            clash = User.objects.filter(email__iexact=value)
            if self.instance:
                clash = clash.exclude(pk=self.instance.pk)
            if clash.exists():
                raise serializers.ValidationError("Another staff account already uses this email.")
        return value

    def validate_stock_point(self, value):
        if value is not None and value.kind != StockPoint.SHOP:
            raise serializers.ValidationError(f"{value.name} is an online channel -- staff can only be assigned to a physical shop.")
        # nobody is newly assigned to an inactive shop; staff already there keep it
        require_active(value, "staff assignments", current=self.instance.stock_point_id if self.instance else None)
        return value

    def validate(self, attrs):
        password = attrs.pop("password", "") or ""
        confirm = attrs.pop("password_confirm", "") or ""
        if self.instance and password:
            raise serializers.ValidationError({"password": "Use Reset Password to change another account's password."})
        if password or confirm:
            if password != confirm:
                raise serializers.ValidationError({"password_confirm": "The two passwords don't match."})
            probe = User(username=attrs.get("username", ""), first_name=attrs.get("first_name", ""),
                         last_name=attrs.get("last_name", ""), email=attrs.get("email", ""))
            try:
                validate_password(password, user=probe)
            except DjangoValidationError as e:
                raise serializers.ValidationError({"password": list(e.messages)})
        self._initial_password = password or None
        return attrs

    def create(self, validated_data):
        user = User(**validated_data)
        if self._initial_password:
            user.set_password(self._initial_password)
        else:
            # no password until the person sets one through a setup link
            user.set_unusable_password()
        user.save()
        return user


class ChangePasswordSerializer(serializers.Serializer):
    """Self-service: always the requesting account -- no user id is accepted."""
    current_password = serializers.CharField(trim_whitespace=False)
    new_password = serializers.CharField(trim_whitespace=False)
    confirm_password = serializers.CharField(trim_whitespace=False)

    def validate(self, attrs):
        user = self.context["request"].user
        if not user.check_password(attrs["current_password"]):
            raise serializers.ValidationError({"current_password": "Your current password is incorrect."})
        if attrs["new_password"] != attrs["confirm_password"]:
            raise serializers.ValidationError({"confirm_password": "The two new passwords don't match."})
        if attrs["new_password"] == attrs["current_password"]:
            raise serializers.ValidationError({"new_password": "Choose a password different from your current one."})
        try:
            validate_password(attrs["new_password"], user=user)
        except DjangoValidationError as e:
            raise serializers.ValidationError({"new_password": list(e.messages)})
        return attrs


class SetPasswordSerializer(serializers.Serializer):
    """Password-setup link: the user comes from the verified link, never the body."""
    new_password = serializers.CharField(trim_whitespace=False)
    confirm_password = serializers.CharField(trim_whitespace=False)

    def validate(self, attrs):
        if attrs["new_password"] != attrs["confirm_password"]:
            raise serializers.ValidationError({"confirm_password": "The two passwords don't match."})
        try:
            validate_password(attrs["new_password"], user=self.context["user"])
        except DjangoValidationError as e:
            raise serializers.ValidationError({"new_password": list(e.messages)})
        return attrs


class ActivityLogSerializer(serializers.ModelSerializer):
    """One Staff Activity Logs entry -- only what the log holds, nothing read from the record itself."""
    module_label = serializers.SerializerMethodField()
    record_kind = serializers.SerializerMethodField()
    store = serializers.SerializerMethodField()
    # position in the viewer's complete eligible timeline (oldest = 1), set by UserViewSet.activity
    seq = serializers.SerializerMethodField()

    class Meta:
        model = ActivityLog
        fields = ["id", "seq", "at", "module", "module_label", "action", "description", "record_type", "record_kind",
                  "record_id", "record_label", "store", "changes", "source"]

    def get_seq(self, obj):
        return getattr(obj, "seq", None)

    def get_record_kind(self, obj):
        from .activity import TRACKED
        track = TRACKED.get(obj.record_type)
        return track.noun[:1].upper() + track.noun[1:] if track else None

    def get_module_label(self, obj):
        from .activity import MODULE_LABELS
        return MODULE_LABELS.get(obj.module, obj.module.title())

    def get_store(self, obj):
        sp = obj.stock_point
        return {"id": sp.id, "name": sp.name, "kind": sp.kind} if sp else None
