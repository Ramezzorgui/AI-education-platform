from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from accounts.views import home_redirect_view
from django.http import HttpResponse
from web_project.views import SystemView
from django.conf import settings
from django.conf.urls.static import static


urlpatterns = [
    path("admin/", admin.site.urls),

    path('feed/', include('feed.urls')),

    path("accounts/", include("accounts.urls")),
    path("", home_redirect_view, name="index"),
    # Searchx HTML CRUD
    #path("searchx/", include("searchx.urls")),
    # Searchx APIs mounted at root (/api/...)
    #path("", include("searchx.urls_api")),
    # Dashboard urls
    path("dashboard/", include("apps.dashboards.urls")),
    path("objectives/", include(("objectif.urls", "objectifs"), namespace="objectifs")),
    path("moderation/", include("moderation.urls", namespace="moderation")),
    # layouts urls
    path("", include("apps.layouts.urls")),
    path('feed/', include('feed.urls', namespace='feed')),  # ✅

    # Pages urls
    path("", include("apps.pages.urls")),

    # Auth urls
    path("", include("apps.authentication.urls")),

    # Card urls
    path("", include("apps.cards.urls")),

    # UI urls
    path("", include("apps.ui.urls")),

    # Extended UI urls
    path("", include("apps.extended_ui.urls")),

    # Icons urls
    path("", include("apps.icons.urls")),

    # Forms urls
    path("", include("apps.forms.urls")),

    # FormLayouts urls
    path("", include("apps.form_layouts.urls")),

    # Tables urls
    path("", include("apps.tables.urls")),

    # Chat urls
    path("chat/", include(("chat.urls", "chat"), namespace="chat")),
    path("quiz/", include(("quiz.urls", "quiz"), namespace="quiz")),
    path("resources/", include(("resources.urls", "resources"), namespace="resources")),
    # Silence Chrome DevTools well-known probe
    path(".well-known/appspecific/com.chrome.devtools.json", lambda request: HttpResponse(status=204)),
]
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)



handler404 = SystemView.as_view(template_name="pages_misc_error.html", status=404)
handler400 = SystemView.as_view(template_name="pages_misc_error.html", status=400)
handler500 = SystemView.as_view(template_name="pages_misc_error.html", status=500)
