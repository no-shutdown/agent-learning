"""business-demo API 客户端及通用 POJO 类型。"""

from .business_api import BusinessApiClient
from .pojo import ApiRequest, ApiResponse

__all__ = ["ApiRequest", "ApiResponse", "BusinessApiClient"]
