"""Inventory parts on a new repair ticket: search, mandatory serial, one-time stock deduction, store scope."""
import os
from datetime import date
from unittest import mock

from django.test import TestCase

from catalog.models import Product, SerialEvent, Stock, StockPoint, StockSerial, Variant
from crmbook_backend.testing import client_for, make_user, results
from parties.models import Party
from repairs.models import RepairPartUse, RepairTicket

PERMS = ["repairs.view", "repairs.book", "repairs.manage"]


@mock.patch.dict(os.environ, {"WHATSAPP_PROVIDER": "console"})
class RepairPartsTests(TestCase):
    def setUp(self):
        self.a = StockPoint.objects.create(slug="store-a", name="Store A", kind=StockPoint.SHOP)
        self.b = StockPoint.objects.create(slug="store-b", name="Store B", kind=StockPoint.SHOP)
        self.party = Party.objects.create(name="Repair Customer", type=Party.RETAIL, phone="9876543210", joined=date.today())
        self.staff_a = make_user("staff-a", PERMS, stock_point=self.a)
        self.client_a = client_for(self.staff_a)
        self.client_b = client_for(make_user("staff-b", PERMS, stock_point=self.b))
        self.owner = client_for(make_user("boss", PERMS, owner=True))
        self.ssd = self.product("NVMe SSD 512GB", Product.SSD, tracked=True)
        self.laptop = self.product("Latitude 5420", Product.LAPTOP, tracked=True)
        self.bag = self.product("Laptop Bag", Product.ACCESSORIES, tracked=False)
        self.units = {}
        for name, variant in (("SSD", self.ssd), ("LAP", self.laptop)):
            for shop in (self.a, self.b):
                for i in (1, 2, 3):
                    self.unit(variant, shop, f"{name}-{shop.slug[-1].upper()}{i}")
        Stock.objects.create(variant=self.bag, stock_point=self.a, quantity=5)

    def product(self, name, category, tracked):
        n = Product.objects.count()
        p = Product.objects.create(brand="X", model_name=name, product_code=f"VC-T-{n:04d}", category=category, serial_tracking=tracked)
        return Variant.objects.create(product=p, code=f"VC-SKU-{n:04d}", spec="std", mrp=1, sell_price=1, cost=1)

    def unit(self, variant, shop, serial):
        stock, _ = Stock.objects.get_or_create(variant=variant, stock_point=shop)
        stock.quantity += 1
        stock.save()
        self.units[serial] = StockSerial.objects.create(variant=variant, stock_point=shop, serial_number=serial, received_by=self.staff_a)

    def shelf(self, variant, shop):
        return Stock.objects.get(variant=variant, stock_point=shop).quantity

    def book(self, client=None, shop=None, parts=None, **extra):
        body = {"party": self.party.id, "brand": "Dell", "model_name": "Inspiron", "serial": "SN-1",
                "stock_point": (shop or self.a).id, "issue": "Slow", "payment": "full", "received": date.today().isoformat(),
                "parts": parts if parts is not None else []}
        body.update(extra)
        return (client or self.client_a).post("/api/tickets/", body, format="json")

    # ---------------------------------------------------------------- search
    def test_search_lists_only_non_laptop_tracked_parts_and_never_their_serials(self):
        rows = self.client_a.get(f"/api/repair-parts/?stock_point={self.a.id}").json()
        self.assertEqual([r["label"].split(" · ")[0] for r in rows], ["X NVMe SSD 512GB"])
        self.assertEqual(rows[0]["available"], 3)
        self.assertNotIn("SSD-A1", str(rows))
        self.assertEqual(self.client_a.get(f"/api/repair-parts/?stock_point={self.a.id}&q=latitude").json(), [])
        self.assertEqual(len(self.client_a.get(f"/api/repair-parts/?stock_point={self.a.id}&q=nvme").json()), 1)

    def test_search_counts_only_units_in_stock_and_hides_a_product_with_none(self):
        StockSerial.objects.filter(serial_number="SSD-A1").update(status=StockSerial.SOLD)
        self.assertEqual(self.client_a.get(f"/api/repair-parts/?stock_point={self.a.id}").json()[0]["available"], 2)
        StockSerial.objects.filter(variant=self.ssd, stock_point=self.a).update(status=StockSerial.SOLD)
        self.assertEqual(self.client_a.get(f"/api/repair-parts/?stock_point={self.a.id}").json(), [])

    def test_staff_cannot_search_another_store_but_owner_can(self):
        self.assertEqual(self.client_a.get(f"/api/repair-parts/?stock_point={self.b.id}").status_code, 403)
        rows = self.owner.get(f"/api/repair-parts/?stock_point={self.b.id}").json()
        self.assertEqual(rows[0]["available"], 3)

    def test_search_needs_repair_booking_permission(self):
        viewer = client_for(make_user("viewer", ["repairs.view"], stock_point=self.a))
        self.assertEqual(viewer.get(f"/api/repair-parts/?stock_point={self.a.id}").status_code, 403)

    # ---------------------------------------------------------- serial check
    def check(self, serial, client=None, variant=None, shop=None):
        r = (client or self.client_a).get("/api/repair-parts/check-serial/", {
            "stock_point": (shop or self.a).id, "variant": (variant or self.ssd).id, "serial": serial})
        self.assertEqual(r.status_code, 200, r.content)
        return r.json()

    def test_typed_serial_is_checked_against_inventory(self):
        self.assertTrue(self.check("SSD-A2")["ok"])
        self.assertTrue(self.check("  ssd-a2 ")["ok"])
        wrong = self.check("NOPE-1")
        self.assertFalse(wrong["ok"])
        self.assertIn("not found", wrong["message"])
        self.assertFalse(self.check("")["ok"])

    def test_check_rejects_other_products_other_stores_and_used_units(self):
        self.assertIn("does not belong", self.check("SSD-A1", variant=self.bag)["message"])
        self.assertIn("not found in stock at Store A", self.check("SSD-B1")["message"])   # another store's unit looks unknown
        self.assertIn("Laptops", self.check("LAP-A1", variant=self.laptop)["message"])
        self.assertEqual(self.book(parts=[{"variant": self.ssd.id, "serial_number": "SSD-A2"}]).status_code, 201)
        self.assertIn("not available", self.check("SSD-A2")["message"])

    def test_check_is_store_scoped_and_needs_booking_permission(self):
        denied = self.client_a.get("/api/repair-parts/check-serial/", {"stock_point": self.b.id, "variant": self.ssd.id, "serial": "SSD-B1"})
        self.assertEqual(denied.status_code, 403)
        self.assertTrue(self.check("SSD-B1", client=self.owner, shop=self.b)["ok"])
        viewer = client_for(make_user("viewer2", ["repairs.view"], stock_point=self.a))
        self.assertEqual(viewer.get("/api/repair-parts/check-serial/", {"stock_point": self.a.id, "variant": self.ssd.id, "serial": "SSD-A1"}).status_code, 403)

    def test_changing_the_product_means_the_old_serial_no_longer_matches(self):
        self.assertTrue(self.check("SSD-A1")["ok"])
        other = self.product("DDR4 8GB", Product.RAM, tracked=True)
        self.assertFalse(self.check("SSD-A1", variant=other)["ok"])

    # ------------------------------------------------------------- deduction
    def test_booking_takes_exactly_the_chosen_unit_out_of_stock_once(self):
        response = self.book(parts=[{"variant": self.ssd.id, "serial_number": "SSD-A2"}])
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["parts_used"][0]["serial_number"], "SSD-A2")
        self.assertEqual(self.shelf(self.ssd, self.a), 2)
        statuses = dict(StockSerial.objects.filter(variant=self.ssd, stock_point=self.a).values_list("serial_number", "status"))
        self.assertEqual(statuses, {"SSD-A1": "in_stock", "SSD-A2": "used", "SSD-A3": "in_stock"})
        ticket = RepairTicket.objects.get(pk=response.json()["id"])
        use = RepairPartUse.objects.get()
        self.assertEqual((use.ticket_id, use.serial.serial_number, use.stock_point_id), (ticket.id, "SSD-A2", self.a.id))
        event = SerialEvent.objects.get(serial__serial_number="SSD-A2", event="used_in_repair")
        self.assertIn(ticket.code, event.text)
        self.assertEqual(self.shelf(self.ssd, self.b), 3)

    def test_same_serial_cannot_be_used_twice(self):
        self.assertEqual(self.book(parts=[{"variant": self.ssd.id, "serial_number": "SSD-A2"}]).status_code, 201)
        again = self.book(parts=[{"variant": self.ssd.id, "serial_number": "ssd-a2"}])
        self.assertEqual(again.status_code, 400)
        self.assertEqual((self.shelf(self.ssd, self.a), RepairPartUse.objects.count(), RepairTicket.objects.count()), (2, 1, 1))

    def test_duplicate_serial_in_one_request_is_refused_and_nothing_moves(self):
        parts = [{"variant": self.ssd.id, "serial_number": "SSD-A1"}, {"variant": self.ssd.id, "serial_number": "SSD-A1"}]
        self.assertEqual(self.book(parts=parts).status_code, 400)
        self.assertEqual((self.shelf(self.ssd, self.a), RepairPartUse.objects.count(), RepairTicket.objects.count()), (3, 0, 0))
        self.assertEqual(StockSerial.objects.get(serial_number="SSD-A1").status, "in_stock")

    def test_failed_booking_rolls_the_whole_ticket_back(self):
        parts = [{"variant": self.ssd.id, "serial_number": "SSD-A1"}, {"variant": self.ssd.id, "serial_number": "NOPE"}]
        self.assertEqual(self.book(parts=parts).status_code, 400)
        self.assertEqual((self.shelf(self.ssd, self.a), RepairPartUse.objects.count(), RepairTicket.objects.count()), (3, 0, 0))

    def test_two_parts_in_one_ticket(self):
        parts = [{"variant": self.ssd.id, "serial_number": "SSD-A1"}, {"variant": self.ssd.id, "serial_number": "SSD-A3"}]
        self.assertEqual(self.book(parts=parts).status_code, 201)
        self.assertEqual((self.shelf(self.ssd, self.a), RepairPartUse.objects.count()), (1, 2))

    # ------------------------------------------------------------ validation
    def test_serial_must_belong_to_the_selected_product_and_be_a_part(self):
        r = self.book(parts=[{"variant": self.laptop.id, "serial_number": "LAP-A1"}])
        self.assertEqual(r.status_code, 400)
        self.assertIn("Laptops", " ".join(r.json()["parts"]))
        r = self.book(parts=[{"variant": self.bag.id, "serial_number": "SSD-A1"}])
        self.assertIn("does not belong", " ".join(r.json()["parts"]))
        self.assertEqual(self.shelf(self.ssd, self.a), 3)

    def test_serial_is_mandatory(self):
        self.assertEqual(self.book(parts=[{"variant": self.ssd.id}]).status_code, 400)
        self.assertEqual(self.book(parts=[{"variant": self.ssd.id, "serial_number": ""}]).status_code, 400)
        self.assertEqual(self.shelf(self.ssd, self.a), 3)

    def test_untracked_product_cannot_be_issued(self):
        r = self.book(parts=[{"variant": self.bag.id, "serial_number": "ANY"}])
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.shelf(self.bag, self.a), 5)

    def test_serial_from_another_store_is_refused(self):
        r = self.book(parts=[{"variant": self.ssd.id, "serial_number": "SSD-B1"}])
        self.assertEqual(r.status_code, 400)
        self.assertIn("not found in stock at Store A", " ".join(r.json()["parts"]))
        self.assertEqual(self.shelf(self.ssd, self.b), 3)

    def test_staff_cannot_book_at_another_store(self):
        r = self.book(shop=self.b, parts=[{"variant": self.ssd.id, "serial_number": "SSD-B1"}])
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.shelf(self.ssd, self.b), 3)

    def test_owner_can_book_with_parts_at_any_store(self):
        r = self.book(client=self.owner, shop=self.b, parts=[{"variant": self.ssd.id, "serial_number": "SSD-B1"}])
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(self.shelf(self.ssd, self.b), 2)

    def test_empty_shelf_with_a_stray_in_stock_serial_is_refused(self):
        Stock.objects.filter(variant=self.ssd, stock_point=self.a).update(quantity=0)
        r = self.book(parts=[{"variant": self.ssd.id, "serial_number": "SSD-A1"}])
        self.assertEqual(r.status_code, 400)
        self.assertEqual(StockSerial.objects.get(serial_number="SSD-A1").status, "in_stock")

    def test_the_charger_example(self):
        """Dell Laptop Charger, 5 units CHG001-CHG005; a ticket fitting CHG003 leaves 4."""
        charger = self.product("Dell Laptop Charger", Product.CHARGER, tracked=True)
        for n in range(1, 6):
            self.unit(charger, self.a, f"CHG00{n}")
        self.assertEqual(self.shelf(charger, self.a), 5)
        found = self.client_a.get(f"/api/repair-parts/?stock_point={self.a.id}&q=charger").json()
        self.assertEqual([(r["variant"], r["available"]) for r in found], [(charger.id, 5)])
        r = self.book(parts=[{"variant": charger.id, "serial_number": "CHG003"}],
                      estimate_lines=[{"description": found[0]["label"], "quantity": 1, "unit_price": 1500}])
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(self.shelf(charger, self.a), 4)
        statuses = dict(StockSerial.objects.filter(variant=charger).values_list("serial_number", "status"))
        self.assertEqual(statuses, {"CHG001": "in_stock", "CHG002": "in_stock", "CHG003": "used", "CHG004": "in_stock", "CHG005": "in_stock"})
        ticket = RepairTicket.objects.get(pk=r.json()["id"])
        self.assertEqual(list(SerialEvent.objects.filter(serial__serial_number="CHG003").values_list("event", "text")),
                         [("used_in_repair", f"Used in repair {ticket.code}")])
        self.assertEqual(r.json()["parts_used"], [{"id": RepairPartUse.objects.get().id, "description": found[0]["label"],
                                                   "serial_number": "CHG003", "variant": charger.id}])
        # the same unit can't go out again on a retry or a second ticket
        self.assertEqual(self.book(parts=[{"variant": charger.id, "serial_number": "CHG003"}]).status_code, 400)
        self.assertEqual(self.shelf(charger, self.a), 4)

    # ------------------------------------------------- repair services mapped to a part
    def service(self, label, variant=None, charge=2000):
        from catalog.models import Service
        return Service.objects.create(slug=label.lower().replace(" ", "-")[:32], label=label, segment=Service.HARDWARE, charge=charge, variant=variant)

    def test_search_offers_services_with_their_mapped_part_and_stock(self):
        self.service("SSD replacement", self.ssd, 3500)
        self.service("Windows installation")
        rows = self.client_a.get(f"/api/repair-parts/?stock_point={self.a.id}&q=replacement").json()
        self.assertEqual(rows, [{"kind": "service", "service": rows[0]["service"], "label": "SSD replacement", "charge": 3500,
                                 "variant": self.ssd.id, "part_label": "X NVMe SSD 512GB · std", "available": 3}])
        labour = self.client_a.get(f"/api/repair-parts/?stock_point={self.a.id}&q=windows").json()
        self.assertEqual((labour[0]["variant"], labour[0]["available"]), (None, 0))
        self.assertNotIn("SSD-A1", str(rows))

    def test_mapped_service_deducts_the_entered_serial(self):
        svc = self.service("SSD replacement", self.ssd, 3500)
        r = self.book(estimate_lines=[{"service_id": svc.id, "description": svc.label, "quantity": 1, "unit_price": 3500}],
                      parts=[{"variant": self.ssd.id, "serial_number": "SSD-A3"}])
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(self.shelf(self.ssd, self.a), 2)
        self.assertEqual(StockSerial.objects.get(serial_number="SSD-A3").status, "used")
        self.assertEqual(r.json()["parts_used"][0]["serial_number"], "SSD-A3")

    def test_mapped_service_without_its_serial_is_refused(self):
        svc = self.service("SSD replacement", self.ssd, 3500)
        r = self.book(estimate_lines=[{"service_id": svc.id, "description": svc.label, "quantity": 1, "unit_price": 3500}])
        self.assertEqual(r.status_code, 400)
        self.assertIn("SSD replacement", " ".join(r.json()["parts"]))
        # a serial of a different product doesn't satisfy it either
        other = self.product("DDR4 8GB", Product.RAM, tracked=True)
        self.unit(other, self.a, "RAM-A1")
        r = self.book(estimate_lines=[{"service_id": svc.id, "description": svc.label, "quantity": 1, "unit_price": 3500}],
                      parts=[{"variant": other.id, "serial_number": "RAM-A1"}])
        self.assertEqual(r.status_code, 400)
        self.assertEqual((self.shelf(self.ssd, self.a), self.shelf(other, self.a), RepairTicket.objects.count()), (3, 1, 0))

    def test_mapped_service_is_one_unit_per_line(self):
        svc = self.service("SSD replacement", self.ssd, 3500)
        r = self.book(estimate_lines=[{"service_id": svc.id, "description": svc.label, "quantity": 2, "unit_price": 3500}],
                      parts=[{"variant": self.ssd.id, "serial_number": "SSD-A1"}])
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.shelf(self.ssd, self.a), 3)

    def test_labour_service_needs_no_serial(self):
        svc = self.service("Windows installation", None, 800)
        r = self.book(estimate_lines=[{"service_id": svc.id, "description": svc.label, "quantity": 1, "unit_price": 800}])
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(RepairPartUse.objects.count(), 0)

    def test_service_cannot_be_mapped_to_a_laptop_or_untracked_product(self):
        from django.core.exceptions import ValidationError
        from catalog.models import Service
        for bad in (self.laptop, self.bag):
            with self.assertRaises(ValidationError):
                Service(slug="x", label="X", segment=Service.HARDWARE, charge=1, variant=bad).full_clean()

    def test_labour_lines_move_no_stock_and_need_no_serial(self):
        before = dict(Stock.objects.values_list("id", "quantity"))
        r = self.book(estimate_lines=[{"description": "Windows Installation", "quantity": 1, "unit_price": 800},
                                      {"description": "Motherboard Repair", "quantity": 1, "unit_price": 2500}])
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()["parts_used"], [])
        self.assertEqual(dict(Stock.objects.values_list("id", "quantity")), before)
        self.assertEqual(StockSerial.objects.exclude(status=StockSerial.IN_STOCK).count(), 0)

    # --------------------------------------------------------------- editing
    def ticket_with_part(self):
        r = self.book(parts=[{"variant": self.ssd.id, "serial_number": "SSD-A2"}])
        self.assertEqual(r.status_code, 201, r.content)
        return r.json()["id"]

    def test_editing_a_ticket_never_moves_stock(self):
        tid = self.ticket_with_part()
        r = self.client_a.patch(f"/api/tickets/{tid}/", {"issue": "Now it will not boot"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual((self.shelf(self.ssd, self.a), RepairPartUse.objects.count()), (2, 1))
        self.assertEqual(r.json()["parts_used"][0]["serial_number"], "SSD-A2")

    def test_parts_cannot_be_changed_after_booking(self):
        tid = self.ticket_with_part()
        r = self.client_a.patch(f"/api/tickets/{tid}/", {"parts": [{"variant": self.ssd.id, "serial_number": "SSD-A1"}]}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual((self.shelf(self.ssd, self.a), RepairPartUse.objects.count()), (2, 1))
        self.assertEqual(StockSerial.objects.get(serial_number="SSD-A1").status, "in_stock")

    def test_ticket_with_fitted_parts_cannot_be_deleted_and_stock_stays_out(self):
        tid = self.ticket_with_part()
        self.assertEqual(self.client_a.delete(f"/api/tickets/{tid}/").status_code, 400)
        self.assertTrue(RepairTicket.objects.filter(pk=tid).exists())
        self.assertEqual(self.shelf(self.ssd, self.a), 2)

    def test_ticket_without_parts_books_and_deletes_as_before(self):
        r = self.book()
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()["parts_used"], [])
        self.assertEqual(self.client_a.delete(f"/api/tickets/{r.json()['id']}/").status_code, 204)

    # ------------------------------------------------------------------ bulk
    def test_bulk_order_issues_parts_per_device(self):
        r = self.client_a.post("/api/repair-orders/", {
            "party": self.party.id, "stock_point": self.a.id, "payment": "full", "received": date.today().isoformat(),
            "devices": [
                {"brand": "Dell", "model_name": "A", "serial": "S1", "issue": "x", "parts": [{"variant": self.ssd.id, "serial_number": "SSD-A1"}]},
                {"brand": "HP", "model_name": "B", "serial": "S2", "issue": "y", "parts": [{"variant": self.ssd.id, "serial_number": "SSD-A2"}]},
            ]}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual((self.shelf(self.ssd, self.a), RepairPartUse.objects.count()), (1, 2))
        bad = self.client_a.post("/api/repair-orders/", {
            "party": self.party.id, "stock_point": self.a.id, "payment": "full", "received": date.today().isoformat(),
            "devices": [
                {"brand": "Dell", "model_name": "A", "serial": "S3", "issue": "x", "parts": [{"variant": self.ssd.id, "serial_number": "SSD-A3"}]},
                {"brand": "HP", "model_name": "B", "serial": "S4", "issue": "y", "parts": [{"variant": self.ssd.id, "serial_number": "SSD-A1"}]},
            ]}, format="json")
        self.assertEqual(bad.status_code, 400)
        self.assertEqual((self.shelf(self.ssd, self.a), RepairPartUse.objects.count()), (1, 2))
        self.assertEqual(StockSerial.objects.get(serial_number="SSD-A3").status, "in_stock")
