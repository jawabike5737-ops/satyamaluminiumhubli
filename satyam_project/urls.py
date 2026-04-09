from django.contrib import admin
from django.urls import path, include   # 👈 ADD include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('core.urls')),   # 👈 ADD THIS LINE
]

