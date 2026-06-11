from django.urls import path
from rest_framework.authtoken.views import obtain_auth_token

from . import views

urlpatterns = [
    # Authentication endpoints
    path("auth/register/", views.register_user, name="register"),
    path("auth/login/", obtain_auth_token, name="login"),
    path("auth/logout/", views.logout_user, name="logout"),

    # Expense and category endpoints
    path("categories/", views.category_list, name="category-list"),
    path("expenses/", views.expense_list, name="expense-list"),
    path("expenses/summary/", views.expense_summary, name="expense-summary"),
    path("expenses/<int:pk>/", views.expense_detail, name="expense-detail"),
]
