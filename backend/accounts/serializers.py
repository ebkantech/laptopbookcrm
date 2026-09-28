from rest_framework import serializers

from .models import NotificationRule, Permission, Role, StaffNotification, User


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

    class Meta:
        model = User
        fields = [
            "id", "username", "first_name", "last_name", "email", "phone",
            "role", "role_label", "role_slug", "permissions", "is_superuser",
        ]

    def get_permissions(self, obj):
        if obj.is_superuser:
            return list(Permission.objects.values_list("codename", flat=True))
        if not obj.role:
            return []
        return list(obj.role.permissions.values_list("codename", flat=True))
