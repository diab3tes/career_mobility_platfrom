from django.urls import path

from . import views

urlpatterns = [
    path("", views.profile_form, name="profile_form"),
    path("profile/cv/", views.cv_upload, name="cv_upload"),
    path("profile/delete/", views.delete_my_data, name="delete_my_data"),
]
