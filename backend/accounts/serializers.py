from rest_framework import serializers

from .models import Permission, Role, User


class PermissionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Permission
        fields = ["id", "codename", "description"]


class RoleSerializer(serializers.ModelSerializer):
    permissions = PermissionSerializer(many=True, read_only=True)
    permission_codes = serializers.SlugRelatedField(
        source="permissions", many=True, read_only=True, slug_field="codename"
    )

    class Meta:
        model = Role
        fields = ["id", "slug", "label", "permissions", "permission_codes"]


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
