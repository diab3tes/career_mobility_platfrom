from django.urls import path

from . import views

urlpatterns = [
    path("shortlist/", views.shortlist_page, name="shortlist"),
    path("shortlist/<int:pk>/remove/", views.shortlist_remove, name="shortlist_remove"),
    path("api/shortlist/<int:pk>/", views.api_shortlist, name="api_shortlist"),
]
