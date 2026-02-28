from django.db import models
from django.core.exceptions import ValidationError
from django.contrib.auth.models import User
import secrets
import string


class Airport(models.Model):
    # Example: MSP, ORD
    code = models.CharField(max_length=3, unique=True)
    name = models.CharField(max_length=120)
    city = models.CharField(max_length=80)
    country = models.CharField(max_length=80, default="USA")

    def __str__(self):
        return f"{self.code} - {self.name}"


class Route(models.Model):
    # Example: MSP -> ORD
    from_airport = models.ForeignKey(
        Airport, on_delete=models.PROTECT, related_name="routes_from"
    )
    to_airport = models.ForeignKey(
        Airport, on_delete=models.PROTECT, related_name="routes_to"
    )

    def __str__(self):
        return f"{self.from_airport.code} -> {self.to_airport.code}"


class Flight(models.Model):
    # Example: AT101
    flight_code = models.CharField(max_length=10, unique=True)
    route = models.ForeignKey(Route, on_delete=models.PROTECT)

    def __str__(self):
        return f"{self.flight_code} ({self.route})"


class Trip(models.Model):
    # A scheduled flight (date + time)
    flight = models.ForeignKey(Flight, on_delete=models.CASCADE)
    depart_at = models.DateTimeField()
    arrive_at = models.DateTimeField()
    delay_minutes = models.PositiveSmallIntegerField(default=0)
    delay_note = models.CharField(max_length=200, blank=True)

    def clean(self):
        # If one of the fields is missing, don't compare yet
        if not self.depart_at or not self.arrive_at:
            return

        # Arrival must be after departure
        if self.arrive_at <= self.depart_at:
            raise ValidationError(
                {"arrive_at": "Arrival time must be after departure time."}
            )

    def __str__(self):
        return f"{self.flight.flight_code} | {self.depart_at}"


class SupportTicket(models.Model):
    class Status(models.TextChoices):
        OPEN = "open", "Open"
        IN_PROGRESS = "in_progress", "In Progress"
        RESOLVED = "resolved", "Resolved"

    name = models.CharField(max_length=120)
    email = models.EmailField()
    message = models.TextField()
    source_page = models.CharField(max_length=200, blank=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.OPEN,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.name} ({self.email}) - {self.get_status_display()}"


class Booking(models.Model):
    class Status(models.TextChoices):
        CONFIRMED = "confirmed", "Confirmed"
        CANCELLED = "cancelled", "Cancelled"

    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name="bookings")
    user = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="bookings"
    )
    reference = models.CharField(max_length=12, unique=True, db_index=True, editable=False)
    passenger_name = models.CharField(max_length=120)
    passenger_email = models.EmailField()
    passenger_phone = models.CharField(max_length=24, blank=True)
    seats = models.PositiveSmallIntegerField(default=1)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.CONFIRMED,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.reference} - {self.trip.flight.flight_code}"

    def _generate_reference(self):
        alphabet = string.ascii_uppercase + string.digits
        return "".join(secrets.choice(alphabet) for _ in range(8))

    def save(self, *args, **kwargs):
        if not self.reference:
            for _ in range(10):
                candidate = self._generate_reference()
                if not Booking.objects.filter(reference=candidate).exists():
                    self.reference = candidate
                    break
        super().save(*args, **kwargs)
