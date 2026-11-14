from django.urls import path

from . import views

urlpatterns = [
    path("api/ai-mode/", views.api_ai_mode, name="api_ai_mode"),
]
