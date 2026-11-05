from datetime import date

from crmbook_backend.testing import client_for, give_out, make_user
from repairs.models import RepairTicket
from repairs.test_revisions import ADMIN, Base
from sales.models import Invoice

class DeliveryOnPaymentTests(Base):
    def setUp(self):
        super().setUp(); self.admin = make_user("adm9", ADMIN + ("invoices.view","invoices.settle","invoices.create"), stock_point=self.store)
    def test_pay_delivers(self):
        for pay in (RepairTicket.FULL, RepairTicket.ADVANCE):
            c = client_for(self.admin)
            r = c.post("/api/tickets/", {"party": self.party.pk, "brand": "Dell", "model_name": "L5", "serial": "S1", "stock_point": self.store.pk,
                "issue": "x", "received": date.today().isoformat(), "payment": pay, "service_ids": [self.service.pk]}, format="json")
            t = RepairTicket.objects.get(pk=r.data["id"])
            self.approve_current(t); give_out(t, self.admin)
            for inv in Invoice.objects.filter(repair_ticket=t, is_advance=True):
                c.post(f"/api/invoices/{inv.pk}/settle/", {"pay_method": "Cash"}, format="json")
            for st in ("In progress", "Ready for pickup"):
                x = c.post(f"/api/tickets/{t.pk}/set-stage/", {"status": st}, format="json")
            s = c.post(f"/api/tickets/{t.pk}/settle/")
            for inv in Invoice.objects.filter(repair_ticket=t):
                if inv.status != "Paid":
                    c.post(f"/api/invoices/{inv.pk}/settle/", {"pay_method": "Cash"}, format="json")
            t.refresh_from_db()
            self.assertEqual(t.status, RepairTicket.DELIVERED, pay)

    def test_stuck_paid_ticket_self_heals(self):
        c = client_for(self.admin)
        r = c.post("/api/tickets/", {"party": self.party.pk, "brand": "Dell", "model_name": "L5", "serial": "S1", "stock_point": self.store.pk,
            "issue": "x", "received": date.today().isoformat(), "payment": RepairTicket.FULL, "service_ids": [self.service.pk]}, format="json")
        t = RepairTicket.objects.get(pk=r.data["id"]); self.approve_current(t); give_out(t, self.admin)
        for st in ("In progress", "Ready for pickup"):
            c.post(f"/api/tickets/{t.pk}/set-stage/", {"status": st}, format="json")
        c.post(f"/api/tickets/{t.pk}/settle/")
        Invoice.objects.filter(repair_ticket=t).update(status="Paid")  # paid, but the hook never ran
        self.assertEqual(RepairTicket.objects.get(pk=t.pk).status, "Ready for pickup")
        got = c.get(f"/api/tickets/{t.pk}/")
        self.assertEqual(got.data["status"], "Delivered")
