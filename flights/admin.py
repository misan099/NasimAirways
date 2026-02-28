from datetime import timedelta
import base64
import os
from urllib import parse as urlparse
from urllib import request as urlrequest

from django.contrib import admin
from django.utils import timezone

from .models import Airport, Booking, Flight, Route, SupportTicket, Trip

admin.site.site_header = "NASIM Airways Admin"
admin.site.site_title = "NASIM Admin"
admin.site.index_title = "Operations Control Panel"


def _trip_live_status(trip):
    now = timezone.now()
    delayed_depart = trip.depart_at + timedelta(minutes=trip.delay_minutes or 0)
    delayed_arrive = trip.arrive_at + timedelta(minutes=trip.delay_minutes or 0)
    boarding_open = delayed_depart - timedelta(minutes=45)
    if trip.delay_minutes > 0 and trip.depart_at <= now < delayed_depart:
        return "Delayed"
    if now < boarding_open:
        return "Scheduled"
    if boarding_open <= now < delayed_depart:
        return "Boarding"
    if delayed_depart <= now < delayed_arrive:
        return "In Air"
    return "Arrived"


def _send_sms_message(phone_number, body):
    provider = (os.environ.get("SMS_PROVIDER") or "").lower()
    if provider != "twilio":
        return False, "SMS_PROVIDER is not configured (set to 'twilio' to send real SMS)."

    account_sid = os.environ.get("TWILIO_ACCOUNT_SID", "")
    auth_token = os.environ.get("TWILIO_AUTH_TOKEN", "")
    from_number = os.environ.get("TWILIO_FROM_NUMBER", "")
    if not account_sid or not auth_token or not from_number:
        return False, "Twilio environment variables are incomplete."

    payload = urlparse.urlencode(
        {"To": phone_number, "From": from_number, "Body": body}
    ).encode("utf-8")
    auth = base64.b64encode(f"{account_sid}:{auth_token}".encode("utf-8")).decode("utf-8")
    req = urlrequest.Request(
        f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json",
        data=payload,
        headers={
            "Authorization": f"Basic {auth}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    try:
        with urlrequest.urlopen(req, timeout=8):
            return True, ""
    except Exception as exc:  # pragma: no cover
        return False, str(exc)


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


class RouteFromInline(admin.TabularInline):
    model = Route
    fk_name = "from_airport"
    extra = 1
    autocomplete_fields = ("to_airport",)


class TripInline(admin.TabularInline):
    model = Trip
    extra = 1
    fields = ("depart_at", "arrive_at", "delay_minutes", "delay_note")


class BookingInline(admin.TabularInline):
    model = Booking
    extra = 0
    fields = (
        "user",
        "reference",
        "passenger_name",
        "passenger_email",
        "passenger_phone",
        "seats",
        "status",
        "created_at",
    )
    readonly_fields = ("reference", "created_at")
    show_change_link = True


@admin.register(Airport)
class AirportAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "city", "country")
    search_fields = ("code", "name", "city")
    list_filter = ("country",)
    inlines = (RouteFromInline,)


@admin.register(Route)
class RouteAdmin(admin.ModelAdmin):
    list_display = ("from_airport", "to_airport")
    search_fields = ("from_airport__code", "to_airport__code", "from_airport__city", "to_airport__city")
    autocomplete_fields = ("from_airport", "to_airport")


@admin.register(Flight)
class FlightAdmin(admin.ModelAdmin):
    list_display = ("flight_code", "route", "from_code", "to_code")
    search_fields = ("flight_code", "route__from_airport__code", "route__to_airport__code")
    autocomplete_fields = ("route",)
    inlines = (TripInline,)
    list_select_related = ("route__from_airport", "route__to_airport")

    @admin.display(description="From")
    def from_code(self, obj):
        return obj.route.from_airport.code

    @admin.display(description="To")
    def to_code(self, obj):
        return obj.route.to_airport.code


@admin.register(Trip)
class TripAdmin(admin.ModelAdmin):
    list_display = (
        "flight",
        "trip_route",
        "depart_at",
        "arrive_at",
        "delay_minutes",
        "delay_note",
        "live_status",
        "booking_count",
    )
    list_editable = ("depart_at", "arrive_at", "delay_minutes", "delay_note")
    list_filter = (TripLiveStatusFilter, "depart_at")
    search_fields = ("flight__flight_code", "flight__route__from_airport__code", "flight__route__to_airport__code")
    date_hierarchy = "depart_at"
    list_per_page = 25
    autocomplete_fields = ("flight",)
    inlines = (BookingInline,)
    list_select_related = ("flight__route__from_airport", "flight__route__to_airport")
    actions = ("duplicate_one_week_later", "apply_30_min_delay", "send_delay_sms")

    @admin.display(description="Route")
    def trip_route(self, obj):
        return f"{obj.flight.route.from_airport.code} -> {obj.flight.route.to_airport.code}"

    @admin.display(description="Live status")
    def live_status(self, obj):
        return _trip_live_status(obj)

    @admin.display(description="Bookings")
    def booking_count(self, obj):
        return obj.bookings.count()

    @admin.action(description="Duplicate selected trips +7 days")
    def duplicate_one_week_later(self, request, queryset):
        count = 0
        for trip in queryset:
            Trip.objects.create(
                flight=trip.flight,
                depart_at=trip.depart_at + timedelta(days=7),
                arrive_at=trip.arrive_at + timedelta(days=7),
            )
            count += 1
        self.message_user(request, f"Created {count} duplicated trips.")

    @admin.action(description="Apply 30-minute delay to selected trips")
    def apply_30_min_delay(self, request, queryset):
        updated = queryset.update(delay_minutes=30, delay_note="Operational delay")
        self.message_user(request, f"Updated {updated} trip(s) with 30-minute delay.")

    @admin.action(description="Send delay SMS to booked passengers")
    def send_delay_sms(self, request, queryset):
        sent = 0
        skipped = 0
        failures = 0
        for trip in queryset:
            if trip.delay_minutes <= 0:
                skipped += 1
                continue
            bookings = trip.bookings.filter(status=Booking.Status.CONFIRMED).exclude(passenger_phone="")
            if not bookings.exists():
                skipped += 1
                continue
            depart_at = trip.depart_at + timedelta(minutes=trip.delay_minutes)
            for booking in bookings:
                body = (
                    f"NASIM update: {trip.flight.flight_code} is delayed by "
                    f"{trip.delay_minutes} min. New departure: {depart_at:%Y-%m-%d %H:%M UTC}."
                )
                if trip.delay_note:
                    body = f"{body} Note: {trip.delay_note[:80]}"
                ok, _error_text = _send_sms_message(booking.passenger_phone, body)
                if ok:
                    sent += 1
                else:
                    failures += 1
        self.message_user(
            request,
            f"Delay SMS summary: sent={sent}, skipped={skipped}, failed={failures}.",
        )


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "reference",
        "trip",
        "passenger_name",
        "passenger_email",
        "passenger_phone",
        "seats",
        "status",
        "created_at",
    )
    list_filter = ("status", "created_at")
    search_fields = (
        "user__username",
        "user__email",
        "reference",
        "passenger_name",
        "passenger_email",
        "passenger_phone",
        "trip__flight__flight_code",
    )
    readonly_fields = ("reference", "created_at")
    autocomplete_fields = ("trip",)
    list_select_related = ("trip__flight",)


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
