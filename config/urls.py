from django.contrib import admin
from django.urls import path
from flights.views import (
    book_trip,
    live_network_api,
    my_trips_view,
    ops_signin_view,
    signin_view,
    search_trips,
    signout_view,
    signup_view,
    support_contact_api,
    trip_ai_api,
    trip_detail,
    trip_position_api,
    trip_status_api,
)

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", search_trips),
    path("signin/", signin_view),
    path("ops-signin/", ops_signin_view),
    path("signup/", signup_view),
    path("signout/", signout_view),
    path("my-trips/", my_trips_view),
    path("trip/<int:trip_id>/", trip_detail),
    path("trip/<int:trip_id>/book/", book_trip),
    path("api/trip/<int:trip_id>/status/", trip_status_api),
    path("api/trip/<int:trip_id>/ai/", trip_ai_api),
    path("api/trip/<int:trip_id>/position/", trip_position_api),
    path("api/network/live/", live_network_api),
    path("api/support/contact/", support_contact_api),
]
