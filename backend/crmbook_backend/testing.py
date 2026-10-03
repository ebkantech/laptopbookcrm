"""Shared helpers for the apps' tests.py files."""
import itertools

from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from accounts.models import Permission, Role

_role_counter = itertools.count(1)


def make_user(username, perms=(), superuser=False):
    """A staff user whose role holds exactly `perms` (permission codenames)."""
    User = get_user_model()
    if superuser:
        return User.objects.create_user(username=username, password="safe-test-password", is_superuser=True)
    role = Role.objects.create(slug=f"test-role-{next(_role_counter)}", label=f"Test role for {username}")
    for code in perms:
        role.permissions.add(Permission.objects.get_or_create(codename=code, defaults={"description": code})[0])
    return User.objects.create_user(username=username, password="safe-test-password", role=role)


def client_for(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


def results(response):
    """List payload whether or not the endpoint is paginated."""
    data = response.json()
    return data["results"] if isinstance(data, dict) and "results" in data else data
