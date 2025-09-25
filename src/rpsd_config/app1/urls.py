app_name = "app1"  # Add this line

urlpatterns = [
    # Your app's URL patterns here
    # path('', views.index, name='index'),
]

# Remove when not needed anymore
from django.urls import path  # noqa: E402
from django.views import debug  # noqa: E402

urlpatterns += [
    path("", debug.default_urlconf),
]
