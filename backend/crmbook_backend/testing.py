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


# A tiny valid JPEG header -- enough for the upload sniffing in
# rentals.handover; tests never decode the image.
FAKE_JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00" + b"\x00" * 64 + b"\xff\xd9"


def complete_handover(line, user=None, accessories=None):
    """Fill in a rental line's handover so an approval link can be issued:
    every check passed, working confirmed, and every required photo."""
    from django.core.files.uploadedfile import SimpleUploadedFile

    from rentals.models import RentalLine, RentalLinePhoto

    line.checks = {key: True for key, _ in RentalLine.CHECKS}
    line.working_confirmed = True
    line.accessories = accessories or []
    line.handover_by = user
    line.save()
    kinds = [k for k, _ in RentalLinePhoto.REQUIRED_KINDS] + ([RentalLinePhoto.ACCESSORY] if accessories else [])
    for kind in kinds:
        RentalLinePhoto.objects.create(
            line=line, kind=kind, content_type="image/jpeg", uploaded_by=user,
            image=SimpleUploadedFile(f"{kind}.jpg", FAKE_JPEG, content_type="image/jpeg"),
        )
    return line
