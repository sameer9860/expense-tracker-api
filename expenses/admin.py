from django.contrib import admin

from .models import Category, Expense


# Register your models here.
@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'user', 'monthly_limit')
    list_filter = ('user',)
    search_fields = ('name', 'description')

@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    list_display = ('title', 'user', 'amount', 'category', 'date')
    list_filter = ('user', 'category', 'date')
    search_fields = ('title', 'notes', 'category__name')
    date_hierarchy = 'date'
    ordering = ('-date',)
