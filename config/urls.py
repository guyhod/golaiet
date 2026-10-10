from django.contrib import admin
from django.urls import path
from django.views.generic import TemplateView

from api.api import api

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", api.urls),
    # The dashboard: the Vite build's index.html, served as-is (it holds no template tags).
    path("", TemplateView.as_view(template_name="index.html"), name="dashboard"),
]
