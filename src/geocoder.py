"""
네이버 Maps API 기반 지오코딩 유틸리티
"""

import math
import requests


def geocode(address: str, client_id: str, client_secret: str) -> dict:
    """
    주소를 좌표 및 행정구역 정보로 변환 (네이버 클라우드 Geocoding API)

    Returns:
        {
            "lat": float, "lng": float,
            "sido": str,          # 시/도  (예: 서울특별시)
            "sigungu": str,       # 시/군/구 (예: 강남구)
            "eupmyeondong": str,  # 읍/면/동 (예: 역삼동)
            "full_address": str,
        }
    """
    url = "https://maps.apigw.ntruss.com/map-geocode/v2/geocode"
    headers = {
        "X-NCP-APIGW-API-KEY-ID": client_id,
        "X-NCP-APIGW-API-KEY": client_secret,
    }
    params = {"query": address}

    resp = requests.get(url, headers=headers, params=params, timeout=10)
    resp.raise_for_status()
    data = resp.json()

    addresses = data.get("addresses", [])
    if not addresses:
        raise ValueError(f"주소를 찾을 수 없습니다: {address}")

    doc = addresses[0]

    # addressElements에서 행정구역 파싱
    elements = {
        elem["types"][0]: elem["longName"]
        for elem in doc.get("addressElements", [])
        if elem.get("types")
    }

    return {
        "lat": float(doc["y"]),
        "lng": float(doc["x"]),
        "sido": elements.get("SIDO", ""),
        "sigungu": elements.get("SIGUGUN", ""),
        "eupmyeondong": elements.get("DONGMYUN", ""),
        "full_address": doc.get("roadAddress") or doc.get("jibunAddress") or address,
    }


def haversine(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """두 좌표 간 직선 거리 (미터)"""
    R = 6_371_000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def boundary_point(lat: float, lng: float, radius_m: float, bearing_deg: float):
    """중심 좌표에서 bearing 방향으로 radius_m 이동한 좌표 반환"""
    R = 6_371_000
    b = math.radians(bearing_deg)
    lat1 = math.radians(lat)
    lon1 = math.radians(lng)
    d = radius_m / R
    lat2 = math.asin(
        math.sin(lat1) * math.cos(d) + math.cos(lat1) * math.sin(d) * math.cos(b)
    )
    lon2 = lon1 + math.atan2(
        math.sin(b) * math.sin(d) * math.cos(lat1),
        math.cos(d) - math.sin(lat1) * math.sin(lat2),
    )
    return math.degrees(lat2), math.degrees(lon2)


def reverse_geocode(lat: float, lng: float, client_id: str, client_secret: str) -> dict:
    """
    좌표 → 행정구역 정보 변환 (네이버 클라우드 Reverse Geocoding API)

    Returns:
        {"sido": str, "sigungu": str}  # 예: {"sido": "경기도", "sigungu": "용인시 수지구"}
    """
    url = "https://maps.apigw.ntruss.com/map-reversegeocode/v2/gc"
    headers = {
        "X-NCP-APIGW-API-KEY-ID": client_id,
        "X-NCP-APIGW-API-KEY": client_secret,
    }
    params = {"coords": f"{lng},{lat}", "orders": "admcode", "output": "json"}

    resp = requests.get(url, headers=headers, params=params, timeout=10)
    resp.raise_for_status()
    data = resp.json()

    results = data.get("results", [])
    if not results:
        return {"sido": "", "sigungu": ""}

    region = results[0].get("region", {})
    sido    = region.get("area1", {}).get("name", "")
    area2   = region.get("area2", {}).get("name", "")  # 시/군
    area3   = region.get("area3", {}).get("name", "")  # 구 (광역시·특례시)

    # 수원시 영통구 / 용인시 수지구 처럼 area2+area3 조합이 필요한 경우
    if area3 and any(area3.endswith(s) for s in ("구", "군")):
        sigungu = f"{area2} {area3}"
    else:
        sigungu = area2

    return {"sido": sido, "sigungu": sigungu}
