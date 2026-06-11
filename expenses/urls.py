from django.urls import path

from . import views

urlpatterns = [
    path("categories/", views.category_list, name="category-list"),
    path("expenses/", views.expense_list, name="expense-list"),
    path("expenses/summary/", views.expense_summary, name="expense-summary"),
    path("expenses/<pk>/", views.expense_detail, name="expense-detail"),
]
