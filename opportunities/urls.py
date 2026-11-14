from django.urls import path

from . import views

urlpatterns = [
    path("opportunities/", views.opportunity_list, name="opportunity_list"),
    path("recommendations/", views.recommendations_page, name="recommendations"),
    path("api/recommendations/", views.api_recommendations, name="api_recommendations"),
    path("api/opportunities/<int:pk>/", views.api_opportunity_detail, name="api_opportunity_detail"),
    path("api/opportunities/<int:pk>/ai-assessment/", views.api_ai_assessment, name="api_ai_assessment"),
]
