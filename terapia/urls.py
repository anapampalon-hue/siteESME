from django.urls import path
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('sessao/nova/', views.nova_sessao, name='nova_sessao'),
]