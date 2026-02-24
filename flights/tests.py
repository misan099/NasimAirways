from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from .models import Airport, Flight, Route, Trip


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

    def test_search_page_renders(self):
        self._create_trip(120, 90)
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "NASIM Airways")
        self.assertContains(response, "AT101")

    def test_search_ai_recommends_shortest_trip(self):
        short_trip = self._create_trip(180, 70)
        self._create_trip(60, 120)

        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["ai_recommended_trip"].id, short_trip.id)

    def test_trip_detail_renders_ai_panel(self):
        trip = self._create_trip(30, 100)
        response = self.client.get(f"/trip/{trip.id}/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "AI Operations Desk")
        self.assertContains(response, "Risk Score")
        self.assertContains(response, "Live Flight Map")

    def test_trip_status_api_returns_payload(self):
        trip = self._create_trip(-10, 120)
        response = self.client.get(f"/api/trip/{trip.id}/status/")
        self.assertEqual(response.status_code, 200)

        data = response.json()
        self.assertEqual(data["trip_id"], trip.id)
        self.assertEqual(data["flight_code"], "AT101")
        self.assertIn("status", data)
        self.assertIn("progress_percent", data)

    @patch.dict("os.environ", {}, clear=True)
    def test_trip_ai_api_falls_back_without_openai_key(self):
        trip = self._create_trip(45, 110)
        response = self.client.get(f"/api/trip/{trip.id}/ai/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["source"], "fallback")
        self.assertIn("Flight AT101", data["message"])

    def test_trip_position_api_returns_location_fields(self):
        trip = self._create_trip(-20, 120)
        response = self.client.get(f"/api/trip/{trip.id}/position/")
        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertEqual(data["trip_id"], trip.id)
        self.assertEqual(data["flight_code"], "AT101")
        self.assertIn("latitude", data)
        self.assertIn("longitude", data)
        self.assertIn("altitude_ft", data)
        self.assertIn("ground_speed_kts", data)
        self.assertIn("mode", data)
