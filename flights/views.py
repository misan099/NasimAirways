from datetime import timedelta
import json
import math
import os
from urllib import error, request as urlrequest

from django.core.validators import validate_email
from django.core.exceptions import ValidationError
from django.views.decorators.http import require_POST
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from .models import Airport, SupportTicket, Trip

AIRPORT_COORDS = {
    "MSP": (44.8848, -93.2223),
    "ORD": (41.9742, -87.9073),
    "JFK": (40.6413, -73.7781),
    "LHR": (51.4700, -0.4543),
    "DOH": (25.2731, 51.6081),
    "DXB": (25.2532, 55.3657),
    "CDG": (49.0097, 2.5479),
    "SIN": (1.3644, 103.9915),
}


def _duration_minutes(trip):
    """Return scheduled trip duration in minutes."""
    return max(int((trip.arrive_at - trip.depart_at).total_seconds() // 60), 0)


def _status_for_trip(trip, now=None):
    """Infer a simple live status from schedule and current time."""
    if now is None:
        now = timezone.now()

    boarding_open = trip.depart_at - timedelta(minutes=45)
    if now < boarding_open:
        return "Scheduled"
    if boarding_open <= now < trip.depart_at:
        return "Boarding"
    if trip.depart_at <= now < trip.arrive_at:
        return "In Air"
    return "Arrived"


def _ai_insights(trip):
    """Generate deterministic operational insights for UI automation panels."""
    now = timezone.now()
    duration = _duration_minutes(trip)
    hours_until_departure = (trip.depart_at - now).total_seconds() / 3600

    risk_score = 10
    if duration > 210:
        risk_score += 15
    if trip.depart_at.hour in (6, 7, 8, 17, 18, 19, 20):
        risk_score += 20
    if hours_until_departure < 2:
        risk_score += 15

    if risk_score >= 35:
        risk_level = "Medium"
        recommendation = "Auto-alert gate changes and push check-in reminder now."
    else:
        risk_level = "Low"
        recommendation = "No intervention needed. Keep live tracking enabled."

    return {
        "duration_minutes": duration,
        "status": _status_for_trip(trip, now),
        "risk_score": risk_score,
        "risk_level": risk_level,
        "recommendation": recommendation,
    }


def _progress_percent(trip, now=None):
    """Estimate trip progress from schedule only."""
    if now is None:
        now = timezone.now()
    if now <= trip.depart_at:
        return 0
    if now >= trip.arrive_at:
        return 100

    total_seconds = (trip.arrive_at - trip.depart_at).total_seconds()
    elapsed_seconds = (now - trip.depart_at).total_seconds()
    if total_seconds <= 0:
        return 100
    return int((elapsed_seconds / total_seconds) * 100)


def _build_fallback_ai_message(trip):
    ai = _ai_insights(trip)
    route = f"{trip.flight.route.from_airport.code}->{trip.flight.route.to_airport.code}"
    return (
        f"Flight {trip.flight.flight_code} on {route} is currently {ai['status']}. "
        f"Risk is {ai['risk_level']} ({ai['risk_score']}/100). "
        f"Recommended action: {ai['recommendation']}"
    )


def _airport_coords_from_code(code):
    """Return airport coordinates; deterministic fallback if unknown."""
    if code in AIRPORT_COORDS:
        return AIRPORT_COORDS[code]

    seed = sum(ord(ch) for ch in code)
    lat = 20.0 + (seed % 45)
    lon = -120.0 + (seed % 70)
    return (round(lat, 4), round(lon, 4))


def _live_position_for_trip(trip, now=None):
    """Build a synthetic live position from schedule and route coordinates."""
    if now is None:
        now = timezone.now()

    from_code = trip.flight.route.from_airport.code
    to_code = trip.flight.route.to_airport.code
    start_lat, start_lon = _airport_coords_from_code(from_code)
    end_lat, end_lon = _airport_coords_from_code(to_code)

    progress = _progress_percent(trip, now) / 100.0
    status = _status_for_trip(trip, now)

    lat = start_lat + (end_lat - start_lat) * progress
    lon = start_lon + (end_lon - start_lon) * progress

    # Add a soft "arc" during flight so movement feels more natural on the map.
    if status == "In Air":
        lat += math.sin(progress * math.pi) * 1.5

    if status in ("Scheduled", "Boarding"):
        altitude_ft = 0
        ground_speed_kts = 0
    elif status == "In Air":
        altitude_ft = int(38000 * math.sin(progress * math.pi))
        ground_speed_kts = 460 + int(40 * math.sin(progress * math.pi))
    else:
        altitude_ft = 0
        ground_speed_kts = 0

    return {
        "trip_id": trip.id,
        "flight_code": trip.flight.flight_code,
        "status": status,
        "from_code": from_code,
        "to_code": to_code,
        "start_latitude": round(start_lat, 5),
        "start_longitude": round(start_lon, 5),
        "end_latitude": round(end_lat, 5),
        "end_longitude": round(end_lon, 5),
        "latitude": round(lat, 5),
        "longitude": round(lon, 5),
        "depart_at": trip.depart_at.isoformat(),
        "arrive_at": trip.arrive_at.isoformat(),
        "altitude_ft": altitude_ft,
        "ground_speed_kts": ground_speed_kts,
        "progress_percent": int(progress * 100),
        "mode": "simulated_live",
        "updated_at": now.isoformat(),
    }


def _generate_ai_message(trip):
    """Use OpenAI if configured; otherwise return deterministic fallback text."""
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return _build_fallback_ai_message(trip), "fallback"

    prompt = (
        "You are an airline operations copilot. Keep response under 55 words. "
        f"Flight: {trip.flight.flight_code}. "
        f"Route: {trip.flight.route.from_airport.code} to {trip.flight.route.to_airport.code}. "
        f"Departure: {trip.depart_at.isoformat()}. Arrival: {trip.arrive_at.isoformat()}. "
        f"Heuristic insight: {_build_fallback_ai_message(trip)}"
    )

    payload = {
        "model": os.environ.get("OPENAI_MODEL", "gpt-4.1-mini"),
        "input": prompt,
    }
    req = urlrequest.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urlrequest.urlopen(req, timeout=8) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except (error.URLError, error.HTTPError, TimeoutError, ValueError):
        return _build_fallback_ai_message(trip), "fallback"

    text = body.get("output_text")
    if not text:
        return _build_fallback_ai_message(trip), "fallback"
    return text.strip(), "openai"


def search_trips(request):
    airports = Airport.objects.all().order_by("code")

    from_code = request.GET.get("from", "")
    to_code = request.GET.get("to", "")

    trips = Trip.objects.select_related(
        "flight", "flight__route", "flight__route__from_airport", "flight__route__to_airport"
    )

    if from_code:
        trips = trips.filter(flight__route__from_airport__code=from_code)
    if to_code:
        trips = trips.filter(flight__route__to_airport__code=to_code)

    trips = list(trips.order_by("depart_at"))

    # Basic AI automation: surface a default "best operational" option.
    ai_recommended_trip = None
    if trips:
        ai_recommended_trip = min(
            trips,
            key=lambda t: (
                _duration_minutes(t),
                t.depart_at,
            ),
        )

    return render(
        request,
        "flights/search.html",
        {
            "airports": airports,
            "from_code": from_code,
            "to_code": to_code,
            "trips": trips,
            "ai_recommended_trip": ai_recommended_trip,
        },
    )


def trip_detail(request, trip_id):
    trip = get_object_or_404(
        Trip.objects.select_related(
            "flight", "flight__route", "flight__route__from_airport", "flight__route__to_airport"
        ),
        id=trip_id,
    )
    return render(
        request,
        "flights/trip_detail.html",
        {
            "trip": trip,
            "ai": _ai_insights(trip),
        },
    )


def trip_status_api(request, trip_id):
    trip = get_object_or_404(
        Trip.objects.select_related(
            "flight", "flight__route", "flight__route__from_airport", "flight__route__to_airport"
        ),
        id=trip_id,
    )
    now = timezone.now()
    status = _status_for_trip(trip, now)
    payload = {
        "trip_id": trip.id,
        "flight_code": trip.flight.flight_code,
        "status": status,
        "progress_percent": _progress_percent(trip, now),
        "depart_at": trip.depart_at.isoformat(),
        "arrive_at": trip.arrive_at.isoformat(),
        "updated_at": now.isoformat(),
    }
    return JsonResponse(payload)


def trip_ai_api(request, trip_id):
    trip = get_object_or_404(
        Trip.objects.select_related(
            "flight", "flight__route", "flight__route__from_airport", "flight__route__to_airport"
        ),
        id=trip_id,
    )
    message, source = _generate_ai_message(trip)
    return JsonResponse(
        {
            "trip_id": trip.id,
            "source": source,
            "message": message,
        }
    )


def trip_position_api(request, trip_id):
    trip = get_object_or_404(
        Trip.objects.select_related(
            "flight", "flight__route", "flight__route__from_airport", "flight__route__to_airport"
        ),
        id=trip_id,
    )
    return JsonResponse(_live_position_for_trip(trip, timezone.now()))


@require_POST
def support_contact_api(request):
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "Invalid payload."}, status=400)

    name = (payload.get("name") or "").strip()
    email = (payload.get("email") or "").strip()
    message = (payload.get("message") or "").strip()
    source_page = (payload.get("source_page") or "").strip()

    if not name or not email or not message:
        return JsonResponse({"error": "Name, email, and message are required."}, status=400)

    try:
        validate_email(email)
    except ValidationError:
        return JsonResponse({"error": "Enter a valid email address."}, status=400)

    SupportTicket.objects.create(
        name=name,
        email=email,
        message=message,
        source_page=source_page[:200],
    )

    return JsonResponse(
        {
            "ok": True,
            "reply": (
                "Thanks, your request has been logged. "
                "Our support team will reach out shortly."
            ),
        }
    )
