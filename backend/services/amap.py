import logging

import httpx

from config import settings

logger = logging.getLogger(__name__)

AMAP_BASE_URL = "https://restapi.amap.com"
AMAP_SUCCESS_STATUS = "1"
POI_RADIUS_METERS = 3000
POI_LIMIT = 3


class SearchError(Exception):
    def __init__(self, user_message: str, log_message: str) -> None:
        self.user_message = user_message
        self.log_message = log_message
        super().__init__(log_message)


def _get_api_key() -> str:
    api_key = settings.get("AMAP_API_KEY", "").strip()
    if not api_key:
        raise SearchError(
            "地图服务未配置，请联系管理员。",
            "Search 失败：backend/.env 中未配置 AMAP_API_KEY。",
        )
    return api_key


def _parse_location(location: str) -> tuple[float, float]:
    lng_str, lat_str = location.split(",", maxsplit=1)
    return float(lng_str), float(lat_str)


def _format_poi_address(poi: dict) -> str:
    address = (poi.get("address") or "").strip()
    if address:
        return address

    parts = [
        poi.get("pname"),
        poi.get("cityname"),
        poi.get("adname"),
        poi.get("name"),
    ]
    return "".join(part for part in parts if part) or "地址不详"


async def _amap_get(
    client: httpx.AsyncClient,
    api_key: str,
    path: str,
    params: dict,
) -> dict:
    try:
        response = await client.get(
            f"{AMAP_BASE_URL}{path}",
            params={**params, "key": api_key},
        )
    except httpx.RequestError as exc:
        raise SearchError(
            "地图服务暂时不可用，请稍后重试。",
            f"Search 失败：高德网络请求异常 - {exc}",
        ) from exc

    if response.status_code != 200:
        raise SearchError(
            "地图服务暂时不可用，请稍后重试。",
            (
                f"Search 失败：高德 HTTP 状态码 {response.status_code}，"
                f"响应体：{response.text[:500]}"
            ),
        )

    try:
        payload = response.json()
    except ValueError as exc:
        raise SearchError(
            "地图服务暂时不可用，请稍后重试。",
            f"Search 失败：高德响应不是合法 JSON - {response.text[:500]}",
        ) from exc

    if str(payload.get("status")) != AMAP_SUCCESS_STATUS:
        raise SearchError(
            "地图服务调用失败，请稍后重试。",
            (
                f"Search 失败：高德 API status 非成功值，"
                f"status={payload.get('status')} info={payload.get('info')} "
                f"响应={payload}"
            ),
        )

    return payload


async def _geocode_address(
    client: httpx.AsyncClient,
    api_key: str,
    address: str,
    field_name: str,
    field_label: str,
) -> tuple[float, float]:
    payload = await _amap_get(
        client,
        api_key,
        "/v3/geocode/geo",
        {"address": address},
    )

    count = int(payload.get("count") or 0)
    if count == 0:
        if field_name == "address_a":
            user_message = "您的位置没识别出来，换个说法再说说。"
        else:
            user_message = "朋友的位置没识别出来，换个说法再说说。"
        raise SearchError(
            user_message,
            (
                f"Search 失败：{field_name}（{field_label}「{address}」）"
                f"地理编码 count 为 0。"
            ),
        )

    geocodes = payload.get("geocodes") or []
    if not geocodes or not geocodes[0].get("location"):
        raise SearchError(
            "有一个地址没识别出来，换个说法再说说。",
            (
                f"Search 失败：{field_name}（{field_label}「{address}」）"
                f"未返回有效坐标。"
            ),
        )

    return _parse_location(geocodes[0]["location"])


async def _search_nearby_pois(
    client: httpx.AsyncClient,
    api_key: str,
    lng: float,
    lat: float,
    category: str,
) -> list[dict[str, str]]:
    payload = await _amap_get(
        client,
        api_key,
        "/v3/place/around",
        {
            "location": f"{lng},{lat}",
            "keywords": category,
            "radius": POI_RADIUS_METERS,
            "offset": POI_LIMIT,
            "page": 1,
        },
    )

    pois = payload.get("pois") or []
    if not pois:
        raise SearchError(
            f"中点附近找不到合适的{category}，换个类型或地址试试。",
            (
                f"Search 失败：中点周边 POI 列表为空，"
                f"category={category} midpoint=({lng},{lat})。"
            ),
        )

    places: list[dict[str, str]] = []
    for poi in pois[:POI_LIMIT]:
        name = (poi.get("name") or "").strip()
        if not name:
            continue
        places.append(
            {
                "name": name,
                "address": _format_poi_address(poi),
            }
        )

    if not places:
        raise SearchError(
            f"中点附近找不到合适的{category}，换个类型或地址试试。",
            (
                f"Search 失败：中点周边 POI 无有效名称，"
                f"category={category} midpoint=({lng},{lat})。"
            ),
        )

    return places


async def search_meetup_places(
    address_a: str,
    address_b: str,
    category: str,
) -> dict:
    cleaned_a = address_a.strip()
    cleaned_b = address_b.strip()
    cleaned_category = category.strip() or "咖啡店"

    if not cleaned_a or not cleaned_b:
        raise SearchError(
            "地址信息不完整，请分别说出您和朋友的位置。",
            "Search 失败：address_a 或 address_b 为空。",
        )

    api_key = _get_api_key()

    async with httpx.AsyncClient(trust_env=False, timeout=30.0) as client:
        lng_a, lat_a = await _geocode_address(
            client,
            api_key,
            cleaned_a,
            "address_a",
            "我的地址",
        )
        lng_b, lat_b = await _geocode_address(
            client,
            api_key,
            cleaned_b,
            "address_b",
            "朋友地址",
        )

        mid_lng = (lng_a + lng_b) / 2
        mid_lat = (lat_a + lat_b) / 2
        places = await _search_nearby_pois(
            client,
            api_key,
            mid_lng,
            mid_lat,
            cleaned_category,
        )

    logger.info(
        "【Search】审核通过：midpoint=(%f,%f) places=%d",
        mid_lng,
        mid_lat,
        len(places),
    )
    return {
        "midpoint": {"lng": mid_lng, "lat": mid_lat},
        "places": places,
    }
