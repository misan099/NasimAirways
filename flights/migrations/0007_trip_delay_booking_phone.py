from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("flights", "0006_booking"),
    ]

    operations = [
        migrations.AddField(
            model_name="trip",
            name="delay_minutes",
            field=models.PositiveSmallIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="trip",
            name="delay_note",
            field=models.CharField(blank=True, max_length=200),
        ),
        migrations.AddField(
            model_name="booking",
            name="passenger_phone",
            field=models.CharField(blank=True, max_length=24),
        ),
    ]
