from datetime import timedelta

from django.contrib import admin
from django.utils import timezone

from .models import Airport, Flight, Route, SupportTicket, Trip

admin.site.site_header = "NASIM Airways Admin"
admin.site.site_title = "NASIM Admin"
admin.site.index_title = "Operations Control Panel"


def _trip_live_status(trip):
    now = timezone.now()
    boarding_open = trip.depart_at - timedelta(minutes=45)
    if now < boarding_open:
        return "Scheduled"
    if boarding_open <= now < trip.depart_at:
        return "Boarding"
    if trip.depart_at <= now < trip.arrive_at:
        return "In Air"
    return "Arrived"


class TripLiveStatusFilter(admin.SimpleListFilter):
    title = "live status"
    parameter_name = "live_status"

    def lookups(self, request, model_admin):
        return (
            ("scheduled", "Scheduled"),
            ("boarding", "Boarding"),
            ("in_air", "In Air"),
            ("arrived", "Arrived"),
        )

    def queryset(self, request, queryset):
        now = timezone.now()
        boarding_cutoff = now + timedelta(minutes=45)
        value = self.value()
        if value == "scheduled":
            return queryset.filter(depart_at__gt=boarding_cutoff)
        if value == "boarding":
            return queryset.filter(depart_at__lte=boarding_cutoff, depart_at__gt=now)
        if value == "in_air":
            return queryset.filter(depart_at__lte=now, arrive_at__gt=now)
        if value == "arrived":
            return queryset.filter(arrive_at__lte=now)
        return queryset


@admin.register(Airport)
class AirportAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "city", "country")
    search_fields = ("code", "name", "city")
    list_filter = ("country",)


@admin.register(Route)
class RouteAdmin(admin.ModelAdmin):
    list_display = ("from_airport", "to_airport")
    search_fields = ("from_airport__code", "to_airport__code")


@admin.register(Flight)
class FlightAdmin(admin.ModelAdmin):
    list_display = ("flight_code", "route")
    search_fields = ("flight_code", "route__from_airport__code", "route__to_airport__code")


@admin.register(Trip)
class TripAdmin(admin.ModelAdmin):
    list_display = ("flight", "trip_route", "depart_at", "arrive_at", "live_status")
    list_filter = (TripLiveStatusFilter, "depart_at")
    search_fields = ("flight__flight_code", "flight__route__from_airport__code", "flight__route__to_airport__code")
    date_hierarchy = "depart_at"
    list_per_page = 25

    @admin.display(description="Route")
    def trip_route(self, obj):
        return f"{obj.flight.route.from_airport.code} -> {obj.flight.route.to_airport.code}"

    @admin.display(description="Live status")
    def live_status(self, obj):
        return _trip_live_status(obj)


@admin.register(SupportTicket)
class SupportTicketAdmin(admin.ModelAdmin):
    list_display = ("name", "email", "status", "source_page", "created_at")
    list_filter = ("status", "created_at")
    search_fields = ("name", "email", "message", "source_page")
    readonly_fields = ("created_at",)
    actions = ("mark_in_progress", "mark_resolved")

    @admin.action(description="Mark selected tickets as In Progress")
    def mark_in_progress(self, request, queryset):
        queryset.update(status=SupportTicket.Status.IN_PROGRESS)

    @admin.action(description="Mark selected tickets as Resolved")
    def mark_resolved(self, request, queryset):
        queryset.update(status=SupportTicket.Status.RESOLVED)
