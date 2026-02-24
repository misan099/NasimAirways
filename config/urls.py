from django.contrib import admin
from django.urls import path
from flights.views import (
    search_trips,
    support_contact_api,
    trip_ai_api,
    trip_detail,
    trip_position_api,
    trip_status_api,
)

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", search_trips),
    path("trip/<int:trip_id>/", trip_detail),
    path("api/trip/<int:trip_id>/status/", trip_status_api),
    path("api/trip/<int:trip_id>/ai/", trip_ai_api),
    path("api/trip/<int:trip_id>/position/", trip_position_api),
    path("api/support/contact/", support_contact_api),
]
