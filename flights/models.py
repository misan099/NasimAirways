from django.db import models

class Airport(models.Model):
    name = models.CharField(max_length=120)
    iata_code = models.CharField(max_length=3, unique=True)  # MSP
    city = models.CharField(max_length=80)
    country = models.CharField(max_length=80, default="USA")

    def __str__(self):
        return f"{self.iata_code} - {self.name}"
