import os
import requests
import threading
from decimal import Decimal
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework.authtoken.models import Token
from django.db.models import Sum
from django.contrib.auth.models import User

from .models import Category, Expense
from .serializers import CategorySerializer, ExpenseSerializer


def send_bot_alert_async(category_name, total_spent, limit, base_currency, month_name, year):
    # Support Discord Webhooks (easiest fallback if Telegram is blocked)
    discord_webhook_url = os.getenv("DISCORD_WEBHOOK_URL")
    if discord_webhook_url:
        message = (
            f"⚠️ **Budget alert**: \"{category_name}\" is over its monthly limit.\n"
            f"Spent {total_spent:.2f} / {limit:.2f} {base_currency} for {month_name} {year}."
        )
        payload = {"content": message}
        
        def run_discord():
            try:
                response = requests.post(discord_webhook_url, json=payload, timeout=5)
                print(f"Discord webhook response: {response.status_code}")
            except Exception as e:
                print(f"Failed to send Discord alert: {e}")
                
        threading.Thread(target=run_discord).start()
        return

    # Fallback to Telegram Bot API
    token = os.getenv("BOT_TOKEN")
    chat_id = os.getenv("BOT_CHAT_ID")
    if not token or not chat_id:
        print("Bot credentials (Telegram or Discord) not found in environment settings.")
        return

    message = (
        f"⚠️ Budget alert: \"{category_name}\" is over its monthly limit.\n"
        f"Spent {total_spent:.2f} / {limit:.2f} {base_currency} for {month_name} {year}."
    )

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message
    }

    def run_telegram():
        try:
            response = requests.post(url, json=payload, timeout=5)
            print(f"Telegram bot alert response: {response.status_code} {response.text}")
        except Exception as e:
            print(f"Failed to send Telegram alert: {e}")

    threading.Thread(target=run_telegram).start()


def check_budget_threshold(user, category, expense_date, current_expense_id=None):
    if not category.monthly_limit:
        return Decimal("0.00")

    base_currency = os.getenv("BASE_CURRENCY", "USD")
    rates, _ = get_exchange_rates(base_currency)

    # Get MTD expenses excluding the current one (if it's an update)
    expenses = Expense.objects.filter(
        user=user,
        category=category,
        date__year=expense_date.year,
        date__month=expense_date.month
    )
    if current_expense_id:
        expenses = expenses.exclude(pk=current_expense_id)

    total_before = Decimal("0.00")
    for exp in expenses:
        amount = exp.amount
        currency = exp.currency.upper()
        if currency == base_currency:
            total_before += amount
        else:
            rate_to_base = rates.get(currency)
            if rate_to_base:
                total_before += amount / Decimal(str(rate_to_base))
            else:
                total_before += amount

    return total_before


@api_view(["GET", "POST"])
def category_list(request):
    if request.method == "GET":
        # Scope categories to the authenticated user
        categories = Category.objects.filter(user=request.user)
        serializer = CategorySerializer(categories, many=True)
        return Response(serializer.data)

    serializer = CategorySerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    # Save category associated with the logged-in user
    serializer.save(user=request.user)
    return Response(serializer.data, status=status.HTTP_201_CREATED)


@api_view(["GET", "POST"])
def expense_list(request):
    if request.method == "GET":
        # Scope expenses to the authenticated user
        expenses = Expense.objects.filter(user=request.user)

        start_date = request.query_params.get("start_date")
        end_date = request.query_params.get("end_date")
        if start_date:
            expenses = expenses.filter(date__gte=start_date)
        if end_date:
            expenses = expenses.filter(date__lte=end_date)

        serializer = ExpenseSerializer(expenses, many=True)
        return Response(serializer.data)

    serializer = ExpenseSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    category = serializer.validated_data.get("category")
    expense_date = serializer.validated_data.get("date")

    # Calculate total MTD spent before saving
    total_before = Decimal("0.00")
    if category and category.user == request.user and category.monthly_limit and expense_date:
        total_before = check_budget_threshold(request.user, category, expense_date)

    # Save expense associated with the logged-in user
    expense = serializer.save(user=request.user)

    # Calculate total MTD spent after saving
    if category and category.user == request.user and category.monthly_limit and expense_date:
        base_currency = os.getenv("BASE_CURRENCY", "USD")
        new_amount = expense.amount
        new_currency = expense.currency.upper()
        rates, _ = get_exchange_rates(base_currency)

        if new_currency == base_currency:
            new_amount_base = new_amount
        else:
            rate_to_base = rates.get(new_currency)
            new_amount_base = new_amount / Decimal(str(rate_to_base)) if rate_to_base else new_amount

        total_after = total_before + new_amount_base

        if total_before <= category.monthly_limit < total_after:
            month_name = expense_date.strftime("%B")
            send_bot_alert_async(
                category.name,
                total_after,
                category.monthly_limit,
                base_currency,
                month_name,
                expense_date.year
            )

    return Response(serializer.data, status=status.HTTP_201_CREATED)


@api_view(["GET", "PUT", "DELETE"])
def expense_detail(request, pk):
    try:
        # Only allow accessing expenses belonging to the authenticated user
        expense = Expense.objects.get(pk=pk, user=request.user)
    except Expense.DoesNotExist:
        return Response(status=status.HTTP_404_NOT_FOUND)

    if request.method == "GET":
        serializer = ExpenseSerializer(expense)
        return Response(serializer.data)

    if request.method == "PUT":
        serializer = ExpenseSerializer(expense, data=request.data)
        serializer.is_valid(raise_exception=True)

        category = serializer.validated_data.get("category", expense.category)
        expense_date = serializer.validated_data.get("date", expense.date)

        # Calculate total MTD spent before saving (excluding the current expense)
        total_before = Decimal("0.00")
        if category and category.user == request.user and category.monthly_limit and expense_date:
            total_before = check_budget_threshold(request.user, category, expense_date, current_expense_id=expense.id)

        updated_expense = serializer.save()

        # Calculate total MTD spent after saving
        if category and category.user == request.user and category.monthly_limit and expense_date:
            base_currency = os.getenv("BASE_CURRENCY", "USD")
            new_amount = updated_expense.amount
            new_currency = updated_expense.currency.upper()
            rates, _ = get_exchange_rates(base_currency)

            if new_currency == base_currency:
                new_amount_base = new_amount
            else:
                rate_to_base = rates.get(new_currency)
                new_amount_base = new_amount / Decimal(str(rate_to_base)) if rate_to_base else new_amount

            total_after = total_before + new_amount_base

            if total_before <= category.monthly_limit < total_after:
                month_name = expense_date.strftime("%B")
                send_bot_alert_async(
                    category.name,
                    total_after,
                    category.monthly_limit,
                    base_currency,
                    month_name,
                    expense_date.year
                )

        return Response(serializer.data)

    expense.delete()
    return Response(status=status.HTTP_204_NO_CONTENT)


def get_exchange_rates(base_currency):
    api_url = os.getenv("EXCHANGE_RATE_API_URL")
    if not api_url:
        api_url = "https://open.er-api.com/v6/latest"
    
    urls_to_try = []
    if "open.er-api.com" in api_url:
        urls_to_try.append(f"{api_url.rstrip('/')}/{base_currency}")
    else:
        urls_to_try.append(f"{api_url.rstrip('/')}/latest?base={base_currency}")
        urls_to_try.append(f"{api_url.rstrip('/')}/{base_currency}")
        
    for url in urls_to_try:
        try:
            response = requests.get(url, timeout=5)
            if response.status_code == 200:
                data = response.json()
                if data.get("result") == "success" or "rates" in data:
                    rates = data.get("rates", {})
                    as_of = data.get("time_last_update_utc", "")
                    if as_of:
                        try:
                            from datetime import datetime
                            dt = datetime.strptime(as_of.split(" +")[0], "%a, %d %b %Y %H:%M:%S")
                            as_of = dt.strftime("%Y-%m-%d")
                        except Exception:
                            pass
                    return rates, as_of
        except Exception:
            continue
            
    return {base_currency: 1.0}, ""


@api_view(["GET"])
def expense_summary(request):
    base_currency = os.getenv("BASE_CURRENCY", "USD")
    rates, as_of = get_exchange_rates(base_currency)

    categories = Category.objects.filter(user=request.user)
    categories_summary = []
    
    for category in categories:
        expenses = Expense.objects.filter(user=request.user, category=category)
        if not expenses.exists():
            continue
            
        total_category_spent = Decimal("0.00")
        last_rate = "1.00"
        
        for expense in expenses:
            amount = expense.amount
            currency = expense.currency.upper()
            
            if currency == base_currency:
                total_category_spent += amount
                last_rate = "1.00"
            else:
                rate_to_base = rates.get(currency)
                if rate_to_base:
                    rate_dec = Decimal(str(rate_to_base))
                    converted_amount = amount / rate_dec
                    total_category_spent += converted_amount
                    
                    display_rate = Decimal("1") / rate_dec
                    last_rate = f"{display_rate:.2f}"
                else:
                    total_category_spent += amount
                    last_rate = "1.00"
                    
        categories_summary.append({
            "category": category.name,
            "total": f"{total_category_spent:.2f}",
            "rate": last_rate,
            "as_of": as_of if as_of else "N/A"
        })
        
    response_data = {
        "base_currency": base_currency,
        "categories": categories_summary
    }
    return Response(response_data)


# --- Authentication Views ---

@api_view(["POST"])
@permission_classes([AllowAny])
def register_user(request):
    username = request.data.get("username")
    password = request.data.get("password")
    email = request.data.get("email", "")

    if not username or not password:
        return Response(
            {"detail": "Username and password are required."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if User.objects.filter(username=username).exists():
        return Response(
            {"detail": "Username already exists."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    user = User.objects.create_user(username=username, password=password, email=email)
    token, _ = Token.objects.get_or_create(user=user)
    return Response(
        {"token": token.key, "username": user.username},
        status=status.HTTP_201_CREATED,
    )


@api_view(["POST"])
def logout_user(request):
    try:
        request.user.auth_token.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
    except Exception:
        return Response(
            {"detail": "Invalid token or user not logged in."},
            status=status.HTTP_400_BAD_REQUEST,
        )
