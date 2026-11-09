"""Product categories edited at run time: rename, fields, required (*), new categories, switching off."""
from django.test import TestCase

from catalog.models import Product, ProductCategory, StockPoint
from crmbook_backend.testing import client_for, make_user

URL = "/api/product-categories/"


class CategoryEditingTests(TestCase):
    def setUp(self):
        self.kb = StockPoint.objects.create(slug="kb", name="Karol Bagh", kind=StockPoint.SHOP)
        self.owner = client_for(make_user("cat-owner", superuser=True))
        self.staff = client_for(make_user("cat-staff", ["inventory.edit"], stock_point=self.kb))
        self.laptop = ProductCategory.objects.get(key="laptop")

    def add_stock(self, client, category, specs, brand="Godrej", name="Ergo Chair"):
        return client.post("/api/inventory/add-stock/", {
            "category": category, "brand": brand, "model_name": name, "specs": specs, "stock_point": self.kb.id,
            "quantity": 1, "sell_price": 9000}, format="json")

    def test_the_starting_six_are_there(self):
        keys = [c["key"] for c in self.staff.get(URL).json()]
        self.assertEqual(keys, ["laptop", "charger", "ssd", "ram", "accessories", "other"])

    def test_only_an_admin_can_change_them(self):
        self.assertEqual(self.staff.patch(f"{URL}{self.laptop.id}/", {"name": "Notebook"}, format="json").status_code, 403)
        self.assertEqual(self.staff.post(URL, {"name": "Chairs"}, format="json").status_code, 403)

    def test_rename_and_make_a_field_required_keeps_its_key(self):
        fields = self.laptop.fields
        gen = next(f for f in fields if f["key"] == "generation")
        gen.update(label="CPU generation", required=True)
        response = self.owner.patch(f"{URL}{self.laptop.id}/", {"name": "Notebook", "fields": fields}, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertEqual(body["key"], "laptop")  # products keep pointing at it
        renamed = next(f for f in body["fields"] if f["label"] == "CPU generation")
        self.assertEqual((renamed["key"], renamed["required"]), ("generation", True))
        # now required on Add stock
        specs = {"processor": "i5", "ram": "8GB", "storage": "256GB"}
        bad = self.add_stock(self.staff, "laptop", specs, brand="Dell", name="Latitude")
        self.assertEqual(bad.status_code, 400)
        self.assertIn("specs.generation", bad.json())

    def test_a_new_category_with_its_own_fields_is_used_by_add_stock(self):
        response = self.owner.post(URL, {"name": "Office chair", "icon": "armchair", "brand_required": False, "code_prefix": "VC-FUR",
                                         "fields": [{"label": "Material", "type": "choice", "options": ["Mesh", "Leather"], "required": True, "summary": True},
                                                    {"label": "Colour shade"}]}, format="json")
        self.assertEqual(response.status_code, 201, response.content)
        cat = response.json()
        self.assertEqual(cat["key"], "office_chair")
        self.assertEqual([f["key"] for f in cat["fields"]], ["material", "colour_shade"])
        wrong = self.add_stock(self.staff, "office_chair", {"material": "Wood"}, brand="")
        self.assertIn("Choose one of", str(wrong.json()))
        ok = self.add_stock(self.staff, "office_chair", {"material": "Mesh"}, brand="")
        self.assertEqual(ok.status_code, 201, ok.content)
        product = Product.objects.get(category="office_chair")
        self.assertTrue(product.product_code.startswith("VC-FUR"))
        self.assertEqual(ok.json()["variant"]["spec"], "Mesh")
        # laptop details are not asked for (nor accepted) here
        self.assertEqual(self.add_stock(self.staff, "office_chair", {"material": "Mesh", "processor": "i5"}, brand="", name="Other Chair").status_code, 400)

    def test_choice_needs_two_options_and_names_are_unique(self):
        bad = self.owner.post(URL, {"name": "Tables", "fields": [{"label": "Top", "type": "choice", "options": ["Glass"]}]}, format="json")
        self.assertEqual(bad.status_code, 400)
        self.assertEqual(self.owner.post(URL, {"name": "laptop"}, format="json").status_code, 400)

    def test_a_category_in_use_is_switched_off_not_deleted(self):
        Product.objects.create(model_name="X", product_code="P-X", category="ssd")
        ssd = ProductCategory.objects.get(key="ssd")
        response = self.owner.delete(f"{URL}{ssd.id}/")
        self.assertEqual(response.status_code, 200)
        ssd.refresh_from_db()
        self.assertFalse(ssd.is_active)
        self.assertEqual(self.add_stock(self.staff, "ssd", {"capacity": "1TB", "interface": "NVMe"}).status_code, 400)
        unused = ProductCategory.objects.get(key="ram")
        self.assertEqual(self.owner.delete(f"{URL}{unused.id}/").status_code, 204)
