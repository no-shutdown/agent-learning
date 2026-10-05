from functools import partial
import json
import re
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import JsonResponse, HttpResponseNotAllowed
from django.middleware.csrf import get_token
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_GET, require_POST
from .models import Address, Order, Product, Operation
from . import services as s
from .agent_proxy import proxy_agent


def csrf_failure(request, reason=""):
    if request.path.startswith("/api/"):
        return JsonResponse(
            {"error": {"code": "csrf_failed", "message": "登录或提交前请取得当前 CSRF token"}},
            status=403,
        )
    return render(
        request, "shop/error.html", {"error": "页面会话已过期，请刷新后重试。"}, status=403
    )


def paged(request, qs):
    return Paginator(qs, 20).get_page(request.GET.get("page", 1))


def order_filter(request, qs):
    status = request.GET.get("status", "")
    q = request.GET.get("q", "").strip()
    if status:
        if status not in Order.Status.values:
            raise s.BusinessError("invalid_input", "未知订单状态")
        qs = qs.filter(status=status)
    if q:
        number = q.upper().removeprefix("ORD-")
        if number.isdigit():
            qs = qs.filter(pk=int(number))
        else:
            qs = qs.filter(Q(items__name__icontains=q) | Q(note__icontains=q)).distinct()
    return qs


@require_GET
@login_required
def home(request):
    orders = Order.objects.filter(owner=request.user)
    return render(
        request,
        "shop/home.html",
        {
            "order_count": orders.count(),
            "paid_count": orders.filter(status="paid").count(),
            "address_count": Address.objects.filter(owner=request.user).count(),
            "recent": orders[:5],
        },
    )


def login_page(request):
    if request.method not in ("GET", "POST"):
        return HttpResponseNotAllowed(["GET", "POST"])
    if request.method == "POST":
        user = authenticate(
            request,
            username=request.POST.get("username", ""),
            password=request.POST.get("password", ""),
        )
        if user:
            login(request, user)
            return redirect("/")
        messages.error(request, "用户名或密码错误")
    return render(request, "shop/login.html")


@require_POST
def logout_page(request):
    logout(request)
    return redirect("/login/")


@require_GET
@login_required
def products_page(request):
    qs = Product.objects.filter(active=True).order_by("id")
    if request.GET.get("q"):
        qs = qs.filter(name__icontains=request.GET["q"])
    return render(
        request,
        "shop/products.html",
        {"page": paged(request, qs), "addresses": Address.objects.filter(owner=request.user)},
    )


@require_GET
@login_required
def orders_page(request):
    try:
        qs = order_filter(request, Order.objects.filter(owner=request.user))
    except s.BusinessError as e:
        messages.error(request, e.message)
        qs = Order.objects.none()
    return render(
        request, "shop/orders.html", {"page": paged(request, qs), "statuses": Order.Status.choices}
    )


@require_GET
@login_required
def order_page(request, pk):
    o = get_object_or_404(Order.objects.prefetch_related("items"), pk=pk, owner=request.user)
    return render(
        request,
        "shop/order.html",
        {"order": o, "addresses": Address.objects.filter(owner=request.user)},
    )


@require_GET
@login_required
def addresses_page(request):
    return render(
        request,
        "shop/addresses.html",
        {"addresses": Address.objects.filter(owner=request.user).order_by("id")},
    )


@require_GET
@login_required
def operations_page(request):
    return render(
        request,
        "shop/operations.html",
        {"page": paged(request, Operation.objects.filter(actor=request.user).defer("result"))},
    )


@require_GET
@login_required
def manage_products(request):
    if not request.user.is_staff:
        return render(request, "shop/error.html", {"error": "需要管理员权限"}, status=403)
    return render(
        request,
        "shop/manage_products.html",
        {"page": paged(request, Product.objects.order_by("id"))},
    )


@require_GET
@login_required
def manage_orders(request):
    if not request.user.is_staff:
        return render(request, "shop/error.html", {"error": "需要管理员权限"}, status=403)
    return render(
        request,
        "shop/manage_orders.html",
        {"page": paged(request, Order.objects.filter(status="paid").select_related("owner"))},
    )


@require_GET
@login_required
def assistant_page(request):
    return render(request, "shop/assistant.html")


def body(request):
    try:
        data = json.loads(request.body or b"{}")
    except (ValueError, UnicodeDecodeError):
        raise s.BusinessError("invalid_json", "请求应为 JSON 对象")
    if not isinstance(data, dict):
        raise s.BusinessError("invalid_json", "请求应为 JSON 对象")
    return data


def api_dispatch(request, route):
    try:
        return dispatch(request, route.strip("/"))
    except s.BusinessError as e:
        return JsonResponse({"error": {"code": e.code, "message": e.message}}, status=e.status)


def dispatch(request, route):
    method, actor = request.method, request.user
    if method not in ("GET", "POST", "PUT"):
        raise s.BusinessError("method_not_allowed", "仅支持 GET / POST / PUT", 405)
    if route == "health" and method == "GET":
        return JsonResponse({"status": "ok", "service": "business-demo"})
    if route == "auth/csrf" and method == "GET":
        return JsonResponse({"csrf_token": get_token(request)})
    if route == "auth/login" and method == "POST":
        data = body(request)
        s.fields(data, ("username", "password"), ("username", "password"))
        username = s.text(data["username"], "username", 150)
        password = s.text(data["password"], "password", 200)
        user = authenticate(request, username=username, password=password)
        if not user:
            raise s.BusinessError("unauthenticated", "用户名或密码错误", 401)
        login(request, user)
        return JsonResponse({"username": user.username, "csrf_token": get_token(request)})
    if not actor.is_authenticated:
        raise s.BusinessError("unauthenticated", "请先登录", 401)
    if route == "auth/logout" and method == "POST":
        logout(request)
        return JsonResponse({"status": "logged_out"})
    if route == "me" and method == "GET":
        return JsonResponse({"username": actor.username, "is_staff": actor.is_staff})
    if route in ("assistant/chat", "assistant/confirm") and method == "POST":
        return proxy_agent(request, body(request), confirm=route.endswith("/confirm"))
    if method == "GET":
        if route in ("products", "manage/products"):
            if route.startswith("manage"):
                s.require_staff(actor)
            qs = Product.objects.order_by("id")
            if route == "products":
                qs = qs.filter(active=True)
            if request.GET.get("q"):
                qs = qs.filter(name__icontains=request.GET["q"])
            return list_response(request, qs, s.product_json)
        if m := re.fullmatch(r"products/(\d+)", route):
            p = Product.objects.filter(pk=m[1], active=True).first()
            if not p:
                raise s.BusinessError("not_found", "商品不存在或已下架", 404)
            return JsonResponse(s.product_json(p))
        if route == "addresses":
            return list_response(
                request, Address.objects.filter(owner=actor).order_by("id"), s.address_json
            )
        if route in ("orders", "manage/orders"):
            qs = Order.objects.prefetch_related("items")
            if route.startswith("manage"):
                s.require_staff(actor)
            else:
                qs = qs.filter(owner=actor)
            return list_response(request, order_filter(request, qs), s.order_json)
        if m := re.fullmatch(r"orders/(\d+)", route):
            return JsonResponse(s.order_json(s.own_order(actor, m[1])))
        if route == "operations":
            return list_response(
                request,
                Operation.objects.filter(actor=actor),
                lambda o: {
                    "key": o.key,
                    "action": o.action,
                    "target": o.target,
                    "created_at": o.created_at.isoformat(),
                },
            )
        if route.startswith("operations/"):
            op = Operation.objects.filter(actor=actor, key=route.split("/", 1)[1]).first()
            if not op:
                raise s.BusinessError(
                    "not_found", "未找到已提交的操作；可能尚未完成，请保持原编号核实或重试", 404
                )
            return JsonResponse(
                {"key": op.key, "action": op.action, "result": op.result, "committed": True}
            )
    handler = None
    if method == "POST" and route == "addresses":
        data = body(request)
        handler = partial(s.create_address, actor, data)
    elif method == "PUT" and (m := re.fullmatch(r"addresses/(\d+)", route)):
        data = body(request)
        pk = int(m[1])
        handler = partial(s.edit_address, actor, pk, data)
    elif method == "POST" and route == "orders":
        data = body(request)
        handler = partial(s.create_order, actor, data)
    elif method == "POST" and (m := re.fullmatch(r"orders/(\d+)/(pay|cancel|address|ship)", route)):
        data = body(request)
        pk, action = int(m[1]), m[2]
        handler = partial(s.order_action, actor, pk, action, data)
    elif method == "POST" and route == "manage/products":
        data = body(request)
        handler = partial(s.save_product, actor, None, data)
    elif method == "PUT" and (m := re.fullmatch(r"manage/products/(\d+)", route)):
        data = body(request)
        pk = int(m[1])
        handler = partial(s.save_product, actor, pk, data)
    if handler:
        result, replayed = s.perform(
            actor, request.headers.get("Idempotency-Key", ""), route, data, handler
        )
        return JsonResponse({"data": result, "replayed": replayed})
    raise s.BusinessError("not_found", "接口或请求方法不存在", 404)


def list_response(request, qs, serializer):
    page = s.integer(request.GET.get("page", 1), "page")
    size = s.integer(request.GET.get("page_size", 20), "page_size", high=100)
    count = qs.count()
    return JsonResponse(
        {
            "count": count,
            "page": page,
            "page_size": size,
            "results": [serializer(x) for x in qs[(page - 1) * size : page * size]],
        }
    )


@require_GET
@login_required
def product_page(request, pk):
    p = get_object_or_404(Product, pk=pk, active=True)
    return render(
        request,
        "shop/product_detail.html",
        {"product": p, "addresses": Address.objects.filter(owner=request.user)},
    )
