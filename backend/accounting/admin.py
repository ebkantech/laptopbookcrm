from django.contrib import admin

from .models import BankAccount, BankEntry, CashEntry


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
