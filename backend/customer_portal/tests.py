from datetime import date, timedelta
from urllib.parse import urlparse

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import Client, TestCase
from django.utils import timezone

from parties.models import Party
from rentals.models import Rental, RentalApproval

from .models import CustomerAccessToken, CustomerProfile
from .services import get_or_create_customer_profile, issue_access_token


class CustomerPortalSecurityTests(TestCase):
    password = "River!Cloud9072"

    def setUp(self):
        cache.clear()
        User = get_user_model()
        self.staff = User.objects.create_superuser(
            username="portal_test_admin",
            email="admin@example.test",
            password="Staff!Password9072",
        )
        self.party = Party.objects.create(
            name="Portal Test Customer",
            type=Party.RENTAL,
            phone="9876543210",
            email="customer@example.test",
            joined=date.today(),
        )
        self.profile, _ = get_or_create_customer_profile(self.party, self.staff)
        _, self.activation_url = issue_access_token(
            self.profile,
            CustomerAccessToken.ACTIVATION,
            self.staff,
        )
        self.activation_token = urlparse(self.activation_url).path.rstrip("/").split("/")[-1]

    def csrf_client(self):
        client = Client(enforce_csrf_checks=True)
        response = client.get("/api/customer/auth/csrf/")
        self.assertEqual(response.status_code, 200)
        return client, response.json()["csrf_token"]

    def activate(self, client=None, csrf=None):
        if client is None or csrf is None:
            client, csrf = self.csrf_client()
        response = client.post(
            f"/api/customer/auth/activate/{self.activation_token}/",
            data={
                "phone": "9876543210",
                "password": self.password,
                "confirm_password": self.password,
            },
            content_type="application/json",
            HTTP_X_CSRFTOKEN=csrf,
        )
        self.assertEqual(response.status_code, 200, response.content)
        return client, csrf

    def login(self, client, csrf):
        response = client.post(
            "/api/customer/auth/login/",
            data={"phone": "9876543210", "password": self.password},
            content_type="application/json",
            HTTP_X_CSRFTOKEN=csrf,
        )
        self.assertEqual(response.status_code, 200, response.content)
        refreshed = client.get("/api/customer/auth/csrf/")
        self.assertEqual(refreshed.status_code, 200)
        return refreshed.json()["csrf_token"]

    def test_activation_requires_csrf_and_token_is_one_time(self):
        untrusted = Client(enforce_csrf_checks=True)
        response = untrusted.post(
            f"/api/customer/auth/activate/{self.activation_token}/",
            data={"phone": "9876543210", "password": self.password, "confirm_password": self.password},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)

        client, csrf = self.activate()
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.status, CustomerProfile.ACTIVE)
        self.assertTrue(self.profile.user.check_password(self.password))

        replay = client.post(
            f"/api/customer/auth/activate/{self.activation_token}/",
            data={"phone": "9876543210", "password": self.password, "confirm_password": self.password},
            content_type="application/json",
            HTTP_X_CSRFTOKEN=csrf,
        )
        self.assertEqual(replay.status_code, 404)

    def test_wrong_phone_does_not_consume_activation_link(self):
        client, csrf = self.csrf_client()
        response = client.post(
            f"/api/customer/auth/activate/{self.activation_token}/",
            data={"phone": "9999999999", "password": self.password, "confirm_password": self.password},
            content_type="application/json",
            HTTP_X_CSRFTOKEN=csrf,
        )
        self.assertEqual(response.status_code, 400)
        token = CustomerAccessToken.objects.get(purpose=CustomerAccessToken.ACTIVATION)
        self.assertIsNone(token.consumed_at)

    def test_customer_session_is_filtered_and_blocked_from_staff_apis(self):
        client, csrf = self.activate()
        csrf = self.login(client, csrf)

        dashboard = client.get("/api/customer/dashboard/")
        self.assertEqual(dashboard.status_code, 200)
        self.assertEqual(dashboard.json()["profile"]["parties"][0]["id"], self.party.id)

        internal = client.get("/api/parties/")
        self.assertEqual(internal.status_code, 403)

        staff_login = client.post(
            "/api/auth/token/",
            data={"username": self.profile.user.username, "password": self.password},
            content_type="application/json",
        )
        self.assertEqual(staff_login.status_code, 401)

    def test_customer_can_decide_own_rental_but_not_another_party(self):
        client, csrf = self.activate()
        csrf = self.login(client, csrf)
        rental = Rental.objects.create(
            party=self.party,
            product_label="Dell Latitude 5420",
            monthly_fee=2500,
            start=date.today(),
            tenure_months=6,
            last_payment=date.today(),
            agreement_code="RNT-PORTAL-0001",
            status=Rental.PENDING_APPROVAL,
        )
        approval = RentalApproval.objects.create(
            rental=rental,
            version=1,
            snapshot={"agreement_code": rental.agreement_code, "total_monthly_fee": 2500},
            expires_at=timezone.now() + timedelta(hours=24),
            requested_by=self.staff,
        )
        response = client.post(
            f"/api/customer/rental-approvals/{approval.id}/decision/",
            data={"decision": "approve", "consent": True, "reason": "Reviewed in portal"},
            content_type="application/json",
            HTTP_X_CSRFTOKEN=csrf,
        )
        self.assertEqual(response.status_code, 200, response.content)
        approval.refresh_from_db()
        rental.refresh_from_db()
        self.assertEqual(approval.status, RentalApproval.APPROVED)
        self.assertEqual(approval.source, RentalApproval.CUSTOMER)
        self.assertEqual(approval.decided_by_id, self.profile.user_id)
        self.assertEqual(rental.status, Rental.APPROVED)

        other_party = Party.objects.create(
            name="Another Customer",
            type=Party.RENTAL,
            phone="9123456780",
            joined=date.today(),
        )
        other_rental = Rental.objects.create(
            party=other_party,
            product_label="HP EliteBook",
            monthly_fee=3000,
            start=date.today(),
            tenure_months=6,
            last_payment=date.today(),
            agreement_code="RNT-PORTAL-0002",
            status=Rental.PENDING_APPROVAL,
        )
        other_approval = RentalApproval.objects.create(
            rental=other_rental,
            version=1,
            snapshot={},
            expires_at=timezone.now() + timedelta(hours=24),
        )
        forbidden = client.post(
            f"/api/customer/rental-approvals/{other_approval.id}/decision/",
            data={"decision": "approve", "consent": True},
            content_type="application/json",
            HTTP_X_CSRFTOKEN=csrf,
        )
        self.assertEqual(forbidden.status_code, 404)
