from django.contrib import admin
from .models import Airport

@admin.register(Airport)
class AirportAdmin(admin.ModelAdmin):
    list_display = ("iata_code", "name", "city", "country")
    search_fields = ("iata_code", "name", "city")
    list_filter = ("country",)