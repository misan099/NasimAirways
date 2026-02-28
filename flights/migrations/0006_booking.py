from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("flights", "0005_seed_hub_routes"),
    ]

    operations = [
        migrations.CreateModel(
            name="Booking",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("reference", models.CharField(db_index=True, editable=False, max_length=12, unique=True)),
                ("passenger_name", models.CharField(max_length=120)),
                ("passenger_email", models.EmailField(max_length=254)),
                ("seats", models.PositiveSmallIntegerField(default=1)),
                (
                    "status",
                    models.CharField(
                        choices=[("confirmed", "Confirmed"), ("cancelled", "Cancelled")],
                        default="confirmed",
                        max_length=20,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "trip",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="bookings",
                        to="flights.trip",
                    ),
                ),
            ],
            options={
                "ordering": ("-created_at",),
            },
        ),
    ]
