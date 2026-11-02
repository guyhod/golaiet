from django.contrib import admin
from django.http import HttpResponse
from django.urls import path

from agent import prompts
from api.api import api


def system_prompts(request):
    """The agent's standing instructions, one page to read them in; they change only in code."""
    named = [(name, text) for name, text in vars(prompts).items() if name.endswith("_SYSTEM_PROMPT")]
    return HttpResponse("\n\n\n".join(f"--- {name} ---\n{text}" for name, text in named), content_type="text/plain; charset=utf-8")


urlpatterns = [
    path("admin/prompts/", system_prompts),
    path("admin/", admin.site.urls),
    path("api/", api.urls),
]
