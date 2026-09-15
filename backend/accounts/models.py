from django.contrib.auth.models import AbstractUser
from django.db import models


class Permission(models.Model):
    """
    One row per named action in the system, e.g. 'cashbook.edit'.
    This is the vocabulary a Role draws from -- mirrors the PERMS
    dictionary from the prototype so the same access model carries
    over exactly.
    """
    codename = models.SlugField(max_length=64, unique=True)
    description = models.CharField(max_length=200)

    class Meta:
        ordering = ["codename"]

    def __str__(self):
        return self.codename


class Role(models.Model):
    """A named set of permissions -- Owner, Accountant, Store Manager, etc."""
    slug = models.SlugField(max_length=32, unique=True)
    label = models.CharField(max_length=64)
    permissions = models.ManyToManyField(Permission, related_name="roles", blank=True)

    class Meta:
        ordering = ["label"]

    def __str__(self):
        return self.label

    def has_perm(self, codename: str) -> bool:
        return self.permissions.filter(codename=codename).exists()


class User(AbstractUser):
    """
    Staff account. `role` drives every permission check across the
    API -- see accounts.permissions.HasPerm.
    """
    role = models.ForeignKey(Role, on_delete=models.PROTECT, related_name="users", null=True, blank=True)
    phone = models.CharField(max_length=20, blank=True)

    def has_perm_code(self, codename: str) -> bool:
        if self.is_superuser:
            return True
        return bool(self.role and self.role.has_perm(codename))

    def __str__(self):
        return self.get_full_name() or self.username
