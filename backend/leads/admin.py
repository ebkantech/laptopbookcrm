from django.contrib import admin

from .models import Lead, LeadApproval, LeadEvent, LeadQuote, LeadQuoteLine

admin.site.register([Lead, LeadQuote, LeadQuoteLine, LeadApproval, LeadEvent])
