from datetime import timedelta

from django.db import migrations
from django.utils import timezone


def seed_hub_routes(apps, schema_editor):
    Airport = apps.get_model("flights", "Airport")
    Route = apps.get_model("flights", "Route")
    Flight = apps.get_model("flights", "Flight")
    Trip = apps.get_model("flights", "Trip")

    hub = {
        "code": "DOH",
        "name": "Hamad International Airport",
        "city": "Doha",
        "country": "Qatar",
    }
    destinations = [
        ("JFK", "John F. Kennedy International Airport", "New York", "USA"),
        ("LHR", "Heathrow Airport", "London", "United Kingdom"),
        ("CDG", "Charles de Gaulle Airport", "Paris", "France"),
        ("FRA", "Frankfurt Airport", "Frankfurt", "Germany"),
        ("MAD", "Adolfo Suarez Madrid-Barajas Airport", "Madrid", "Spain"),
        ("FCO", "Leonardo da Vinci Fiumicino Airport", "Rome", "Italy"),
        ("IST", "Istanbul Airport", "Istanbul", "Turkey"),
        ("DXB", "Dubai International Airport", "Dubai", "UAE"),
        ("JED", "King Abdulaziz International Airport", "Jeddah", "Saudi Arabia"),
        ("CAI", "Cairo International Airport", "Cairo", "Egypt"),
        ("DEL", "Indira Gandhi International Airport", "Delhi", "India"),
        ("BOM", "Chhatrapati Shivaji Maharaj International Airport", "Mumbai", "India"),
        ("BKK", "Suvarnabhumi Airport", "Bangkok", "Thailand"),
        ("SIN", "Singapore Changi Airport", "Singapore", "Singapore"),
        ("HKG", "Hong Kong International Airport", "Hong Kong", "Hong Kong"),
        ("NRT", "Narita International Airport", "Tokyo", "Japan"),
        ("ICN", "Incheon International Airport", "Seoul", "South Korea"),
        ("SYD", "Sydney Kingsford Smith Airport", "Sydney", "Australia"),
        ("JNB", "O.R. Tambo International Airport", "Johannesburg", "South Africa"),
        ("GRU", "Sao Paulo/Guarulhos International Airport", "Sao Paulo", "Brazil"),
    ]

    hub_airport, _ = Airport.objects.get_or_create(code=hub["code"], defaults=hub)
    for code, name, city, country in destinations:
        Airport.objects.get_or_create(
            code=code,
            defaults={"name": name, "city": city, "country": country},
        )

    now = timezone.now()
    for index, (code, _name, _city, _country) in enumerate(destinations, start=1):
        to_airport = Airport.objects.get(code=code)
        route, _ = Route.objects.get_or_create(
            from_airport=hub_airport,
            to_airport=to_airport,
        )
        flight, _ = Flight.objects.get_or_create(
            flight_code=f"AT{200 + index}",
            defaults={"route": route},
        )
        if flight.route_id != route.id:
            flight.route = route
            flight.save(update_fields=["route"])

        if not Trip.objects.filter(flight=flight).exists():
            depart_at = now + timedelta(minutes=(index * 35) - 180)
            duration_minutes = 150 + ((index % 6) * 45)
            arrive_at = depart_at + timedelta(minutes=duration_minutes)
            Trip.objects.create(
                flight=flight,
                depart_at=depart_at,
                arrive_at=arrive_at,
            )


class Migration(migrations.Migration):
    dependencies = [
        ("flights", "0004_supportticket"),
    ]

    operations = [
        migrations.RunPython(seed_hub_routes, migrations.RunPython.noop),
    ]
