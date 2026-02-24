from django.db import DatabaseError
from django.utils import timezone


def admin_insights(request):
    """Small metrics block for admin dashboard templates."""
    if not request.path.startswith("/admin"):
        return {}

    try:
        from .models import Airport, Flight, Route, SupportTicket, Trip

        now = timezone.now()
        upcoming_qs = (
            Trip.objects.select_related("flight", "flight__route", "flight__route__from_airport", "flight__route__to_airport")
            .filter(depart_at__gte=now)
            .order_by("depart_at")[:5]
        )
        admin_metrics = {
            "airports": Airport.objects.count(),
            "routes": Route.objects.count(),
            "flights": Flight.objects.count(),
            "upcoming_trips": Trip.objects.filter(depart_at__gte=now).count(),
            "open_tickets": SupportTicket.objects.filter(status=SupportTicket.Status.OPEN).count(),
            "recent_departures": list(upcoming_qs),
        }
        return {"admin_metrics": admin_metrics}
    except (DatabaseError, Exception):
        return {}
