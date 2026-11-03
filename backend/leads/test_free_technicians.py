from accounts.models import Role, User
from crmbook_backend.testing import client_for, make_user

from .models import Lead
from .tests import ADMIN, TECH, Base


class FreeTechnicianTests(Base):
    """Field technicians belong to no store; outsourced ones are Admin / Super Admin only."""

    def setUp(self):
        super().setUp()
        self.free = make_user("free1", TECH)  # no store at all
        self.free.staff_kind = User.FIELD
        self.free.save()
        self.ext = make_user("ext1", TECH)
        self.ext.staff_kind, self.ext.company = User.OUTSOURCED, "FixIt Services"
        self.ext.save()
        self.ext_c = client_for(self.ext)
        self.free_c = client_for(self.free)
        # a store admin who can add/assign staff but holds no outsource permission
        self.plain_admin = make_user("plain", ADMIN + ("roles.manage",), stock_point=self.shop)
        self.super_admin = make_user("boss", ADMIN + ("roles.manage", "leads.outsource"), stock_point=self.shop)
        self.pa, self.sa = client_for(self.plain_admin), client_for(self.super_admin)

    def test_store_less_field_technician_gets_and_works_a_job_at_any_store(self):
        lead = self.new_lead(assigned_to=self.free.id)
        r = self.free_c.get("/api/leads/")
        data = r.json()
        self.assertEqual([l["id"] for l in data.get("results", data)], [lead["id"]])
        self.assertEqual(self.free_c.post(f"/api/leads/{lead['id']}/check_in/", {"lat": 22.7, "lng": 75.8}, format="json").status_code, 200)

    def test_outsourced_technician_is_hidden_from_and_refused_for_plain_admin(self):
        techs = {t["id"]: t for t in self.pa.get("/api/leads/technicians/").json()}
        self.assertIn(self.free.id, techs)
        self.assertNotIn(self.ext.id, techs)
        lead = self.new_lead()
        r = self.pa.post(f"/api/leads/{lead['id']}/assign/", {"assigned_to": self.ext.id}, format="json")
        self.assertEqual(r.status_code, 403)
        r = self.pa.post("/api/leads/", {"party": self.party.id, "stock_point": self.shop.id, "site_address": "12 MG Road, Indore",
                                         "issue": "Laptop not charging", "assigned_to": self.ext.id}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_admin_with_outsource_permission_can_assign_outsourced_technician(self):
        techs = {t["id"]: t for t in self.sa.get("/api/leads/technicians/").json()}
        self.assertEqual(techs[self.ext.id]["kind"], "outsourced")
        self.assertEqual(techs[self.ext.id]["company"], "FixIt Services")
        lead = self.new_lead()
        r = self.sa.post(f"/api/leads/{lead['id']}/assign/", {"assigned_to": self.ext.id}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(Lead.objects.get(pk=lead["id"]).assigned_to_id, self.ext.id)
        self.assertEqual(self.ext_c.get(f"/api/leads/{lead['id']}/").status_code, 200)

    def test_creating_staff_kinds(self):
        body = {"first_name": "Ext", "username": "ext2", "role": self.tech.role_id, "staff_kind": "outsourced", "company": "ACME"}
        self.assertEqual(self.pa.post("/api/users/", body, format="json").status_code, 403)  # plain admin
        r = self.sa.post("/api/users/", body, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        made = User.objects.get(username="ext2")
        self.assertIsNone(made.stock_point_id)
        self.assertEqual((made.staff_kind, made.company), ("outsourced", "ACME"))
        # a field technician (no store) needs no outsource permission
        r = self.pa.post("/api/users/", {**body, "username": "fld", "staff_kind": "field", "company": ""}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertIsNone(User.objects.get(username="fld").stock_point_id)
        # outsourced needs a company; a free technician needs a role that can do on-site work
        self.assertEqual(self.sa.post("/api/users/", {**body, "username": "ext3", "company": ""}, format="json").status_code, 400)
        office = make_user("office", ("invoices.view",)).role_id
        self.assertEqual(self.sa.post("/api/users/", {**body, "username": "ext4", "role": office}, format="json").status_code, 400)

    def test_store_staff_stay_bound_to_their_store(self):
        r = self.pa.post("/api/users/", {"first_name": "S", "username": "stf", "role": self.tech.role_id}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(User.objects.get(username="stf").stock_point_id, self.shop.id)

    def test_store_admin_sees_free_technicians_and_can_bring_one_into_their_store(self):
        data = self.pa.get("/api/users/").json()
        ids = {u["id"] for u in data.get("results", data)}
        self.assertIn(self.free.id, ids)
        r = self.pa.patch(f"/api/users/{self.free.id}/", {"staff_kind": "store"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.free.refresh_from_db()
        self.assertEqual((self.free.staff_kind, self.free.stock_point_id), ("store", self.shop.id))
        # plain admin may not touch an outsourced account
        self.assertEqual(self.pa.patch(f"/api/users/{self.ext.id}/", {"first_name": "X"}, format="json").status_code, 403)
