from django.contrib import admin

from .models import BankAccount, BankEntry, CashEntry, ExpenseCategory


@admin.register(CashEntry)
class CashEntryAdmin(admin.ModelAdmin):
    list_display = ["date", "particulars", "type", "amount", "by"]


@admin.register(BankAccount)
class BankAccountAdmin(admin.ModelAdmin):
    list_display = ["name", "opening"]


@admin.register(BankEntry)
class BankEntryAdmin(admin.ModelAdmin):
    list_display = ["account", "date", "particulars", "type", "amount", "reconciled"]
    list_filter = ["account", "reconciled"]


@admin.register(ExpenseCategory)
class ExpenseCategoryAdmin(admin.ModelAdmin):
    """Where new expense categories are added (Accounting -> Expenses)."""
    list_display = ["label", "classification", "is_active"]
    list_filter = ["classification", "is_active"]
    prepopulated_fields = {"slug": ["label"]}

    def has_delete_permission(self, request, obj=None):
        # expenses PROTECT their category; retire one with is_active instead
        return False
