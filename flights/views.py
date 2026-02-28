from datetime import timedelta
import json
import math
import os
from urllib import error, request as urlrequest

from django.core.validators import validate_email
from django.core.exceptions import ValidationError
from django.contrib import messages
from django.contrib.auth import authenticate
from django.contrib.auth import login, logout
from django.contrib.auth.models import User
from django.views.decorators.http import require_POST
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .forms import BookingForm, PassengerSigninForm, PassengerSignupForm
from .models import Airport, Booking, SupportTicket, Trip

AIRPORT_COORDS = {
    "MSP": (44.8848, -93.2223),
    "ORD": (41.9742, -87.9073),
    "JFK": (40.6413, -73.7781),
    "LHR": (51.4700, -0.4543),
    "FRA": (50.0379, 8.5622),
    "MAD": (40.4893, -3.5676),
    "FCO": (41.8003, 12.2389),
    "IST": (41.2753, 28.7519),
    "DOH": (25.2731, 51.6081),
    "DXB": (25.2532, 55.3657),
    "JED": (21.6702, 39.1525),
    "CAI": (30.1219, 31.4056),
    "DEL": (28.5562, 77.1000),
    "BOM": (19.0896, 72.8656),
    "BKK": (13.6900, 100.7501),
    "CDG": (49.0097, 2.5479),
    "SIN": (1.3644, 103.9915),
    "HKG": (22.3080, 113.9185),
    "NRT": (35.7720, 140.3929),
    "ICN": (37.4602, 126.4407),
    "SYD": (-33.9399, 151.1753),
    "JNB": (-26.1367, 28.2410),
    "GRU": (-23.4356, -46.4731),
}

DEFAULT_HUB_CODE = "DOH"
TRACKING_UNLOCK_MINUTES = 45


def _effective_schedule(trip):
    depart_at = trip.depart_at + timedelta(minutes=trip.delay_minutes or 0)
    arrive_at = trip.arrive_at + timedelta(minutes=trip.delay_minutes or 0)
    return depart_at, arrive_at


def _duration_minutes(trip):
    """Return scheduled trip duration in minutes."""
    depart_at, arrive_at = _effective_schedule(trip)
    return max(int((arrive_at - depart_at).total_seconds() // 60), 0)


def _status_for_trip(trip, now=None):
    """Infer a simple live status from schedule and current time."""
    if now is None:
        now = timezone.now()

    depart_at, arrive_at = _effective_schedule(trip)
    boarding_open = depart_at - timedelta(minutes=45)
    if trip.delay_minutes > 0 and trip.depart_at <= now < depart_at:
        return "Delayed"
    if now < boarding_open:
        return "Scheduled"
    if boarding_open <= now < depart_at:
        return "Boarding"
    if depart_at <= now < arrive_at:
        return "In Air"
    return "Arrived"


def _ai_insights(trip):
    """Generate deterministic operational insights for UI automation panels."""
    now = timezone.now()
    duration = _duration_minutes(trip)
    depart_at, _arrive_at = _effective_schedule(trip)
    hours_until_departure = (depart_at - now).total_seconds() / 3600

    risk_score = 10
    if duration > 210:
        risk_score += 15
    if depart_at.hour in (6, 7, 8, 17, 18, 19, 20):
        risk_score += 20
    if hours_until_departure < 2:
        risk_score += 15
    if trip.delay_minutes > 0:
        risk_score += min(25, trip.delay_minutes // 3)

    if risk_score >= 55:
        risk_level = "High"
        recommendation = "Send proactive SMS update and offer self-service rebooking options."
    elif risk_score >= 35:
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
    depart_at, arrive_at = _effective_schedule(trip)
    if now <= depart_at:
        return 0
    if now >= arrive_at:
        return 100

    total_seconds = (arrive_at - depart_at).total_seconds()
    elapsed_seconds = (now - depart_at).total_seconds()
    if total_seconds <= 0:
        return 100
    return int((elapsed_seconds / total_seconds) * 100)


def _build_fallback_ai_message(trip):
    ai = _ai_insights(trip)
    route = f"{trip.flight.route.from_airport.code}->{trip.flight.route.to_airport.code}"
    delay_text = ""
    if trip.delay_minutes > 0:
        delay_text = f" Flight is delayed by {trip.delay_minutes} minutes."
    return (
        f"Flight {trip.flight.flight_code} on {route} is currently {ai['status']}. "
        f"Risk is {ai['risk_level']} ({ai['risk_score']}/100). "
        f"Recommended action: {ai['recommendation']}.{delay_text}"
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
    depart_at, arrive_at = _effective_schedule(trip)

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
        "from_name": trip.flight.route.from_airport.name,
        "to_name": trip.flight.route.to_airport.name,
        "from_city": trip.flight.route.from_airport.city,
        "from_country": trip.flight.route.from_airport.country,
        "to_city": trip.flight.route.to_airport.city,
        "to_country": trip.flight.route.to_airport.country,
        "start_latitude": round(start_lat, 5),
        "start_longitude": round(start_lon, 5),
        "end_latitude": round(end_lat, 5),
        "end_longitude": round(end_lon, 5),
        "latitude": round(lat, 5),
        "longitude": round(lon, 5),
        "depart_at": depart_at.isoformat(),
        "arrive_at": arrive_at.isoformat(),
        "scheduled_depart_at": trip.depart_at.isoformat(),
        "scheduled_arrive_at": trip.arrive_at.isoformat(),
        "delay_minutes": trip.delay_minutes,
        "delay_note": trip.delay_note,
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

    depart_at, arrive_at = _effective_schedule(trip)
    prompt = (
        "You are an airline operations copilot. Keep response under 55 words. "
        f"Flight: {trip.flight.flight_code}. "
        f"Route: {trip.flight.route.from_airport.code} to {trip.flight.route.to_airport.code}. "
        f"Departure: {depart_at.isoformat()}. Arrival: {arrive_at.isoformat()}. "
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
    if (
        not from_code
        and not to_code
        and Trip.objects.filter(flight__route__from_airport__code=DEFAULT_HUB_CODE).exists()
    ):
        from_code = DEFAULT_HUB_CODE

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
            "default_hub_code": DEFAULT_HUB_CODE,
        },
    )


def signin_view(request):
    if request.user.is_authenticated and not request.user.is_staff:
        return redirect("/my-trips/")

    form = PassengerSigninForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        identifier = form.cleaned_data["identifier"].strip()
        password = form.cleaned_data["password"]

        username = identifier
        if "@" in identifier:
            matched = User.objects.filter(email__iexact=identifier).first()
            if matched:
                username = matched.username

        user = authenticate(request, username=username, password=password)
        if user:
            login(request, user)
            if user.is_staff:
                return redirect("/admin/")
            next_url = request.GET.get("next", "/my-trips/")
            if not next_url.startswith("/") or next_url.startswith("/admin/"):
                next_url = "/my-trips/"
            return redirect(next_url)
        form.add_error(None, "Invalid credentials. Please try again.")

    return render(request, "flights/signin.html", {"form": form})


def signup_view(request):
    if request.user.is_authenticated and not request.user.is_staff:
        return redirect("/my-trips/")

    form = PassengerSignupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user)
        next_url = request.GET.get("next", "/my-trips/")
        if not next_url.startswith("/") or next_url.startswith("/admin/"):
            next_url = "/my-trips/"
        return redirect(next_url)
    return render(request, "flights/signup.html", {"form": form})


def ops_signin_view(request):
    return redirect("/admin/login/?next=/admin/")


def signout_view(request):
    logout(request)
    return redirect("/")


def my_trips_view(request):
    if not request.user.is_authenticated:
        return redirect("/signin/?next=/my-trips/")
    if request.user.is_staff:
        return redirect("/admin/")

    bookings = (
        Booking.objects.select_related(
            "trip",
            "trip__flight",
            "trip__flight__route",
            "trip__flight__route__from_airport",
            "trip__flight__route__to_airport",
        )
        .filter(user=request.user, status=Booking.Status.CONFIRMED)
        .order_by("trip__depart_at")
    )
    return render(request, "flights/my_trips.html", {"bookings": bookings})


def _tracking_opens_at(trip):
    depart_at, _arrive_at = _effective_schedule(trip)
    return depart_at - timedelta(minutes=TRACKING_UNLOCK_MINUTES)


def _authorized_booking_for_trip(request, trip):
    booking_ref = (request.GET.get("ref") or "").strip().upper()
    if not booking_ref:
        return None
    return Booking.objects.filter(
        trip=trip,
        reference=booking_ref,
        status=Booking.Status.CONFIRMED,
    ).first()


def _is_tracking_open(trip, now=None):
    if now is None:
        now = timezone.now()
    return now >= _tracking_opens_at(trip)


def _booking_allowed(request):
    return request.user.is_authenticated and not request.user.is_staff


def trip_detail(request, trip_id):
    trip = get_object_or_404(
        Trip.objects.select_related(
            "flight", "flight__route", "flight__route__from_airport", "flight__route__to_airport"
        ),
        id=trip_id,
    )
    booking = _authorized_booking_for_trip(request, trip)
    now = timezone.now()
    tracking_opens_at = _tracking_opens_at(trip)
    tracking_open = _is_tracking_open(trip, now)
    can_track = booking is not None and tracking_open
    booking_allowed = _booking_allowed(request)
    booking_form = None
    if booking_allowed:
        booking_form = BookingForm(
            initial={
                "passenger_name": (request.user.get_full_name() or "").strip(),
                "passenger_email": request.user.email,
            }
        )

    return render(
        request,
        "flights/trip_detail.html",
        {
            "trip": trip,
            "ai": _ai_insights(trip),
            "booking": booking,
            "booking_form": booking_form,
            "booking_allowed": booking_allowed,
            "tracking_open": tracking_open,
            "can_track": can_track,
            "tracking_opens_at": tracking_opens_at,
            "tracking_unlock_minutes": TRACKING_UNLOCK_MINUTES,
            "booking_ref": (request.GET.get("ref") or "").strip().upper(),
        },
    )


@require_POST
def book_trip(request, trip_id):
    if not request.user.is_authenticated:
        return redirect(f"/signin/?next=/trip/{trip_id}/")
    if request.user.is_staff:
        return redirect("/admin/")

    trip = get_object_or_404(
        Trip.objects.select_related(
            "flight", "flight__route", "flight__route__from_airport", "flight__route__to_airport"
        ),
        id=trip_id,
    )
    form = BookingForm(request.POST)
    if form.is_valid():
        booking = form.save(commit=False)
        booking.trip = trip
        booking.user = request.user
        if not booking.passenger_email:
            booking.passenger_email = request.user.email
        booking.save()
        messages.success(
            request,
            f"Booking confirmed. Reference: {booking.reference}",
        )
        return redirect(f"/trip/{trip.id}/?ref={booking.reference}")

    messages.error(request, "Please correct the booking form and try again.")
    return render(
        request,
        "flights/trip_detail.html",
        {
            "trip": trip,
            "ai": _ai_insights(trip),
            "booking_form": form,
            "booking": None,
            "booking_allowed": True,
            "tracking_open": _is_tracking_open(trip),
            "can_track": False,
            "tracking_opens_at": _tracking_opens_at(trip),
            "tracking_unlock_minutes": TRACKING_UNLOCK_MINUTES,
            "booking_ref": "",
        },
        status=400,
    )


def trip_status_api(request, trip_id):
    trip = get_object_or_404(
        Trip.objects.select_related(
            "flight", "flight__route", "flight__route__from_airport", "flight__route__to_airport"
        ),
        id=trip_id,
    )
    booking = _authorized_booking_for_trip(request, trip)
    if not booking:
        return JsonResponse(
            {"error": "Valid booking reference required.", "code": "booking_required"},
            status=403,
        )
    if not _is_tracking_open(trip):
        return JsonResponse(
            {
                "error": f"Tracking opens {TRACKING_UNLOCK_MINUTES} minutes before departure.",
                "code": "tracking_not_open",
                "opens_at": _tracking_opens_at(trip).isoformat(),
            },
            status=403,
        )

    now = timezone.now()
    status = _status_for_trip(trip, now)
    payload = {
        "trip_id": trip.id,
        "flight_code": trip.flight.flight_code,
        "status": status,
        "progress_percent": _progress_percent(trip, now),
        "from_code": trip.flight.route.from_airport.code,
        "to_code": trip.flight.route.to_airport.code,
        "from_name": trip.flight.route.from_airport.name,
        "to_name": trip.flight.route.to_airport.name,
        "delay_minutes": trip.delay_minutes,
        "delay_note": trip.delay_note,
        "depart_at": _effective_schedule(trip)[0].isoformat(),
        "arrive_at": _effective_schedule(trip)[1].isoformat(),
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
    booking = _authorized_booking_for_trip(request, trip)
    if not booking:
        return JsonResponse(
            {"error": "Valid booking reference required.", "code": "booking_required"},
            status=403,
        )
    if not _is_tracking_open(trip):
        return JsonResponse(
            {
                "error": f"Tracking opens {TRACKING_UNLOCK_MINUTES} minutes before departure.",
                "code": "tracking_not_open",
                "opens_at": _tracking_opens_at(trip).isoformat(),
            },
            status=403,
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
    booking = _authorized_booking_for_trip(request, trip)
    if not booking:
        return JsonResponse(
            {"error": "Valid booking reference required.", "code": "booking_required"},
            status=403,
        )
    if not _is_tracking_open(trip):
        return JsonResponse(
            {
                "error": f"Tracking opens {TRACKING_UNLOCK_MINUTES} minutes before departure.",
                "code": "tracking_not_open",
                "opens_at": _tracking_opens_at(trip).isoformat(),
            },
            status=403,
        )

    return JsonResponse(_live_position_for_trip(trip, timezone.now()))


def live_network_api(request):
    from_code = request.GET.get("from", DEFAULT_HUB_CODE).strip().upper()
    trips = (
        Trip.objects.select_related(
            "flight",
            "flight__route",
            "flight__route__from_airport",
            "flight__route__to_airport",
        )
        .filter(flight__route__from_airport__code=from_code)
        .order_by("depart_at")
    )
    now = timezone.now()
    return JsonResponse(
        {
            "hub_code": from_code,
            "updated_at": now.isoformat(),
            "flights": [_live_position_for_trip(trip, now) for trip in trips],
        }
    )


def _triage_support_message(message):
    lower_message = message.lower()

    easy_rules = (
        (
            ("check-in", "check in", "checkin"),
            "Online check-in usually opens 24 hours before departure and closes 60 minutes before takeoff for most routes.",
        ),
        (
            ("baggage", "bag", "luggage", "carry on", "carry-on"),
            "Most guests can bring 1 carry-on and 1 personal item. Checked baggage depends on fare type, so share your route and I can help estimate it.",
        ),
        (
            ("refund", "cancel", "cancellation"),
            "Refund timing depends on fare rules. Non-refundable fares often return taxes only; flexible fares can be refunded to your original payment method.",
        ),
        (
            ("payment", "card", "pay"),
            "Accepted payment methods include major cards. If payment fails, try matching billing address and retry with a fresh session.",
        ),
        (
            ("reschedule", "change flight", "change booking", "change ticket"),
            "You can change eligible bookings from Manage Trip. Change fees and fare differences depend on fare rules and route.",
        ),
        (
            ("boarding pass", "mobile pass", "pass"),
            "After successful check-in, your boarding pass is available in My Trips and can be downloaded to your phone.",
        ),
    )

    for keywords, reply in easy_rules:
        if any(keyword in lower_message for keyword in keywords):
            return {"handled_by": "ai", "escalate": False, "reply": reply}

    complex_signals = (
        "complaint",
        "legal",
        "chargeback",
        "emergency",
        "medical",
        "visa",
        "passport issue",
        "group booking",
        "corporate booking",
        "special assistance",
        "not received",
        "fraud",
        "representative",
        "agent",
    )
    if any(signal in lower_message for signal in complex_signals) or len(lower_message) > 220:
        return {"handled_by": "ai", "escalate": True}

    return {
        "handled_by": "ai",
        "escalate": False,
        "reply": (
            "I can help with check-in, baggage, payment, booking changes, and refund policy. "
            "If you share more details, I will try to solve it first."
        ),
    }


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

    if not message:
        return JsonResponse({"error": "Please enter your message."}, status=400)

    triage = _triage_support_message(message)
    if not triage.get("escalate"):
        return JsonResponse(
            {
                "ok": True,
                "handled_by": "ai",
                "escalated": False,
                "reply": triage["reply"],
            }
        )

    if email:
        try:
            validate_email(email)
        except ValidationError:
            return JsonResponse(
                {
                    "ok": True,
                    "handled_by": "ai",
                    "escalated": False,
                    "reply": (
                        "This needs a representative. Please share a valid email so "
                        "our team can follow up with you soon."
                    ),
                }
            )

    if not email:
        return JsonResponse(
            {
                "ok": True,
                "handled_by": "ai",
                "escalated": False,
                "reply": (
                    "This looks like a complex request. Please add your email and "
                    "send again so a representative can contact you soon."
                ),
            }
        )

    SupportTicket.objects.create(
        name=name or "Guest",
        email=email,
        message=message,
        source_page=source_page[:200],
    )

    return JsonResponse(
        {
            "ok": True,
            "handled_by": "ai",
            "escalated": True,
            "reply": (
                "Thanks. A representative will get back to you soon. "
                "Your request has been forwarded to our support desk."
            ),
        }
    )
