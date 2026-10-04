from django.urls import path
from shop import views

urlpatterns = [
    path("products/<int:pk>/", views.product_page),
    path("", views.home),
    path("login/", views.login_page),
    path("logout/", views.logout_page),
    path("products/", views.products_page),
    path("orders/", views.orders_page),
    path("orders/<int:pk>/", views.order_page),
    path("addresses/", views.addresses_page),
    path("operations/", views.operations_page),
    path("manage/products/", views.manage_products),
    path("manage/orders/", views.manage_orders),
    path("assistant/", views.assistant_page),
    path("api/v1/<path:route>", views.api_dispatch),
]
