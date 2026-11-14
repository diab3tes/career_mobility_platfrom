from django.urls import include, path

urlpatterns = [
    path("", include("profiles.urls")),
    path("", include("opportunities.urls")),
    path("", include("shortlist.urls")),
    path("", include("ai.urls")),
]
