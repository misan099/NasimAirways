from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from .models import Airport, Booking, Flight, Route, SupportTicket, Trip


class TripViewsTests(TestCase):
    def setUp(self):
        self.msp = Airport.objects.create(code="MSP", name="MSP Intl", city="Minneapolis")
        self.ord = Airport.objects.create(code="ORD", name="OHare", city="Chicago")
        self.route = Route.objects.create(from_airport=self.msp, to_airport=self.ord)
        self.flight = Flight.objects.create(flight_code="AT101", route=self.route)

    def _create_trip(self, dep_delta_min, duration_min):
        depart_at = timezone.now() + timedelta(minutes=dep_delta_min)
        arrive_at = depart_at + timedelta(minutes=duration_min)
        return Trip.objects.create(flight=self.flight, depart_at=depart_at, arrive_at=arrive_at)

    def _create_booking(self, trip):
        return Booking.objects.create(
            trip=trip,
            passenger_name="Test Passenger",
            passenger_email="test@example.com",
            seats=1,
        )

    def _create_user(self, email="passenger@example.com", password="SafePass123!"):
        return User.objects.create_user(username=email, email=email, password=password)

    def test_search_page_renders(self):
        self._create_trip(120, 90)
        response = self.client.get("/?from=MSP")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "NASIM Airways")
        self.assertContains(response, "AT101")

    def test_search_ai_recommends_shortest_trip(self):
        short_trip = self._create_trip(180, 70)
        self._create_trip(60, 120)

        response = self.client.get("/?from=MSP")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["ai_recommended_trip"].id, short_trip.id)

    def test_trip_detail_renders_ai_panel(self):
        trip = self._create_trip(30, 100)
        response = self.client.get(f"/trip/{trip.id}/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Operations insight")
        self.assertContains(response, "Risk score")
        self.assertContains(response, "Live map")

    def test_trip_status_api_returns_payload(self):
        trip = self._create_trip(-10, 120)
        booking = self._create_booking(trip)
        response = self.client.get(f"/api/trip/{trip.id}/status/?ref={booking.reference}")
        self.assertEqual(response.status_code, 200)

        data = response.json()
        self.assertEqual(data["trip_id"], trip.id)
        self.assertEqual(data["flight_code"], "AT101")
        self.assertEqual(data["from_name"], "MSP Intl")
        self.assertEqual(data["to_name"], "OHare")
        self.assertIn("status", data)
        self.assertIn("progress_percent", data)

    @patch.dict("os.environ", {}, clear=True)
    def test_trip_ai_api_falls_back_without_openai_key(self):
        trip = self._create_trip(10, 110)
        booking = self._create_booking(trip)
        response = self.client.get(f"/api/trip/{trip.id}/ai/?ref={booking.reference}")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["source"], "fallback")
        self.assertIn("Flight AT101", data["message"])

    def test_trip_position_api_returns_location_fields(self):
        trip = self._create_trip(-20, 120)
        booking = self._create_booking(trip)
        response = self.client.get(f"/api/trip/{trip.id}/position/?ref={booking.reference}")
        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertEqual(data["trip_id"], trip.id)
        self.assertEqual(data["flight_code"], "AT101")
        self.assertIn("latitude", data)
        self.assertIn("longitude", data)
        self.assertIn("altitude_ft", data)
        self.assertIn("ground_speed_kts", data)
        self.assertIn("mode", data)
        self.assertIn("start_latitude", data)
        self.assertIn("end_latitude", data)
        self.assertIn("from_name", data)
        self.assertIn("to_name", data)

    def test_live_network_api_returns_flights_from_selected_origin(self):
        trip = self._create_trip(-10, 120)
        response = self.client.get("/api/network/live/?from=MSP")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["hub_code"], "MSP")
        self.assertEqual(len(data["flights"]), 1)
        self.assertEqual(data["flights"][0]["trip_id"], trip.id)

    def test_trip_tracking_api_requires_booking_reference(self):
        trip = self._create_trip(-20, 120)
        response = self.client.get(f"/api/trip/{trip.id}/status/")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "booking_required")

    def test_trip_tracking_api_blocks_before_tracking_window(self):
        trip = self._create_trip(180, 120)
        booking = self._create_booking(trip)
        response = self.client.get(f"/api/trip/{trip.id}/status/?ref={booking.reference}")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "tracking_not_open")

    def test_trip_tracking_window_uses_delayed_departure(self):
        trip = self._create_trip(20, 120)
        trip.delay_minutes = 120
        trip.save(update_fields=["delay_minutes"])
        booking = self._create_booking(trip)
        response = self.client.get(f"/api/trip/{trip.id}/status/?ref={booking.reference}")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "tracking_not_open")

    def test_booking_flow_requires_signin_when_anonymous(self):
        trip = self._create_trip(60, 120)
        response = self.client.post(
            f"/trip/{trip.id}/book/",
            data={
                "passenger_name": "Misan Rijal",
                "passenger_email": "misan@example.com",
                "passenger_phone": "+13125550148",
                "seats": 2,
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("/signin/", response.url)
        self.assertEqual(Booking.objects.count(), 0)

    def test_booking_flow_creates_reference_and_redirects(self):
        trip = self._create_trip(60, 120)
        user = self._create_user()
        self.client.force_login(user)
        response = self.client.post(
            f"/trip/{trip.id}/book/",
            data={
                "passenger_name": "Misan Rijal",
                "passenger_email": "misan@example.com",
                "passenger_phone": "+13125550148",
                "seats": 2,
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Booking.objects.count(), 1)
        booking = Booking.objects.first()
        self.assertEqual(booking.passenger_phone, "+13125550148")
        self.assertEqual(booking.user_id, user.id)
        self.assertIn(f"ref={booking.reference}", response.url)

    def test_signup_rejects_mismatched_passwords(self):
        response = self.client.post(
            "/signup/",
            data={
                "username": "newpassenger",
                "email": "newpassenger@example.com",
                "full_name": "New Passenger",
                "password1": "SafePass123!",
                "password2": "Mismatch123!",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Passwords do not match.")

    def test_signin_allows_email_identifier(self):
        user = self._create_user(email="emailsignin@example.com", password="SafePass123!")
        response = self.client.post(
            "/signin/",
            data={"identifier": user.email, "password": "SafePass123!"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/my-trips/")

    def test_my_trips_requires_passenger_signin(self):
        response = self.client.get("/my-trips/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/signin/", response.url)

    def test_support_contact_api_answers_easy_questions_with_ai(self):
        response = self.client.post(
            "/api/support/contact/",
            data='{"message":"When does check-in open?"}',
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["handled_by"], "ai")
        self.assertFalse(data["escalated"])
        self.assertIn("check-in", data["reply"].lower())
        self.assertEqual(SupportTicket.objects.count(), 0)

    def test_support_contact_api_escalates_complex_questions(self):
        response = self.client.post(
            "/api/support/contact/",
            data='{"name":"Misan","email":"misan@example.com","message":"I need a representative for a group booking issue.","source_page":"/"}',
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["escalated"])
        self.assertEqual(SupportTicket.objects.count(), 1)
