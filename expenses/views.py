from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework.authtoken.models import Token
from django.db.models import Sum
from django.contrib.auth.models import User

from .models import Category, Expense
from .serializers import CategorySerializer, ExpenseSerializer


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
    # Save expense associated with the logged-in user
    serializer.save(user=request.user)
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
        serializer.save()
        return Response(serializer.data)

    expense.delete()
    return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(["GET"])
def expense_summary(request):
    # Only summarize expenses belonging to the authenticated user
    summary = (
        Expense.objects.filter(user=request.user)
        .values("category__name")
        .annotate(total=Sum("amount"))
        .order_by("category__name")
    )
    return Response(list(summary))


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
