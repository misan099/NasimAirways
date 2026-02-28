from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("auth", "0012_alter_user_first_name_max_length"),
        ("flights", "0007_trip_delay_booking_phone"),
    ]

    operations = [
        migrations.AddField(
            model_name="booking",
            name="user",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="bookings",
                to="auth.user",
            ),
        ),
    ]
