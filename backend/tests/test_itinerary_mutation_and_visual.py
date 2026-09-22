"""测试行程画板交互拖拽突变、2-Opt 自愈与视觉感知图片透传引擎"""
import pytest
from fastapi.testclient import TestClient

from app.api.main import app
from app.services.poi_images import resolve_poi_image
from app.services.itinerary_mutator import mutate_itinerary_plan
from app.harness.session_store import harness_session_store


def test_resolve_poi_image_curated_and_photos():
    """测试知名地标图片与高德原生相册图库解析"""
    # 1. 核心知名地标命中精选知识库
    gugong_img = resolve_poi_image("故宫博物院")
    assert "wikimedia.org" in gugong_img or "unsplash.com" in gugong_img

    emei_img = resolve_poi_image("峨眉山金顶")
    assert "wikimedia.org" in emei_img or "unsplash.com" in emei_img

    # 2. 高德原生 photos 优先透传
    photos = [
        {"title": "实景1", "url": "https://amap-photos.autonavi.com/poi123.jpg"}
    ]
    amap_img = resolve_poi_image("某本地普通公园", photos=photos)
    assert amap_img == "https://amap-photos.autonavi.com/poi123.jpg"

    # 3. 分类兜底
    food_img = resolve_poi_image("张三老卤牛肉", category="美食小吃")
    assert "images.unsplash.com" in food_img


def test_mutate_itinerary_plan_recalc_and_2opt():
    """测试行程突变引擎的时序重排与 2-Opt 空间自愈"""
    base_plan = {
        "city": "北京",
        "version_id": 1,
        "lifestyle_profile": {
            "morning_person": True,
            "daily_walking_limit_km": 10.0,
        },
        "days": [
            {
                "day_index": 0,
                "date": "2026-10-01",
                "attractions": [
                    {"name": "故宫博物院", "lng": 116.397, "lat": 39.918, "price": 60.0},
                    {"name": "天坛公园", "lng": 116.411, "lat": 39.882, "price": 34.0},
                    {"name": "颐和园", "lng": 116.273, "lat": 39.999, "price": 30.0},
                ],
            }
        ],
    }

    # 1. recalc 模式测试 (保持用户手工排序，重算时钟与通行距离)
    # 用户将天坛拖拽至首位
    mutated_days = [
        {
            "day_index": 0,
            "date": "2026-10-01",
            "attractions": [
                {"name": "天坛公园", "lng": 116.411, "lat": 39.882, "price": 34.0},
                {"name": "故宫博物院", "lng": 116.397, "lat": 39.918, "price": 60.0},
                {"name": "颐和园", "lng": 116.273, "lat": 39.999, "price": 30.0},
            ],
        }
    ]

    res_recalc = mutate_itinerary_plan(base_plan, mutated_days, mode="recalc")
    assert res_recalc["version_id"] == 2
    day0 = res_recalc["days"][0]
    assert len(day0["attractions"]) == 3
    # 保持用户拖拽的天坛第一位
    assert day0["attractions"][0]["name"] == "天坛公园"
    assert day0["attractions"][0]["arrive_time"] == "08:30"
    assert day0["attractions"][0]["image_url"] != ""
    assert day0["attractions"][1]["name"] == "故宫博物院"
    assert day0["attractions"][1]["distance_km"] > 0
    assert day0["total_ticket"] == 124.0
    assert day0["telemetry"]["total_distance_km"] > 0
    # 故宫国庆实名预约预警自动核验触发
    assert "reservation_alert" in day0["attractions"][1]

    # 2. 2-opt 空间自愈模式测试 (mode="2opt")
    # 构造故意绕路交错的次序: 天坛(南) -> 颐和园(西北) -> 故宫(中) -> 圆明园(西北)
    crisscross_days = [
        {
            "day_index": 0,
            "date": "2026-10-01",
            "attractions": [
                {"name": "天坛公园", "lng": 116.411, "lat": 39.882, "price": 34.0},
                {"name": "颐和园", "lng": 116.273, "lat": 39.999, "price": 30.0},
                {"name": "故宫博物院", "lng": 116.397, "lat": 39.918, "price": 60.0},
                {"name": "圆明园", "lng": 116.299, "lat": 40.008, "price": 25.0},
            ],
        }
    ]

    # recalc 保持绕路次序
    res_raw = mutate_itinerary_plan(base_plan, crisscross_days, mode="recalc")
    dist_recalc = res_raw["days"][0]["telemetry"]["total_distance_km"]

    # 2opt 空间自愈解除交叉绕路
    res_2opt = mutate_itinerary_plan(base_plan, crisscross_days, mode="2opt")
    assert res_2opt["version_id"] == 2
    day0_2opt = res_2opt["days"][0]
    names_2opt = [a["name"] for a in day0_2opt["attractions"]]
    dist_2opt = day0_2opt["telemetry"]["total_distance_km"]

    # 验证 2-Opt 成功优化了路径并消除了严重交叉，总里程严格减少
    assert dist_2opt < dist_recalc
    # 验证地理相近的颐和园与圆明园被排在一起 (相邻)
    yhy_idx = names_2opt.index("颐和园")
    ymy_idx = names_2opt.index("圆明园")
    assert abs(yhy_idx - ymy_idx) == 1


def test_mutate_itinerary_api_endpoint():
    """测试 POST /api/session/mutate_itinerary 接口 (支持 recalc 与 2opt)"""
    client = TestClient(app)
    session_id = "test-mutate-session-001"

    # 先向 session_store 初始化一条记录
    harness_session_store.update(
        session_id=session_id,
        user_id="test_user",
        current_plan={
            "city": "北京",
            "version_id": 1,
            "days": [
                {
                    "day_index": 0,
                    "date": "2026-10-02",
                    "attractions": [
                        {"name": "景山公园", "lng": 116.399, "lat": 39.929, "price": 2.0},
                        {"name": "北海公园", "lng": 116.388, "lat": 39.928, "price": 10.0},
                    ],
                }
            ],
        },
    )

    # 调序突变
    payload = {
        "session_id": session_id,
        "user_id": "test_user",
        "days": [
            {
                "day_index": 0,
                "date": "2026-10-02",
                "attractions": [
                    {"name": "北海公园", "lng": 116.388, "lat": 39.928, "price": 10.0},
                    {"name": "景山公园", "lng": 116.399, "lat": 39.929, "price": 2.0},
                ],
            }
        ],
        "mode": "recalc",
    }

    resp = client.post("/api/session/mutate_itinerary", json=payload, headers={"X-User-Id": "test_user"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert data["updated_plan"]["version_id"] == 2
    day0 = data["updated_plan"]["days"][0]
    assert day0["attractions"][0]["name"] == "北海公园"
    assert day0["attractions"][0]["image_url"] != ""

    # 测试 2opt API 请求模式
    payload_2opt = {
        "session_id": session_id,
        "user_id": "test_user",
        "days": [
            {
                "day_index": 0,
                "date": "2026-10-02",
                "attractions": [
                    {"name": "天坛公园", "lng": 116.411, "lat": 39.882, "price": 34.0},
                    {"name": "颐和园", "lng": 116.273, "lat": 39.999, "price": 30.0},
                    {"name": "故宫博物院", "lng": 116.397, "lat": 39.918, "price": 60.0},
                ],
            }
        ],
        "mode": "2opt",
    }
    resp_2opt = client.post("/api/session/mutate_itinerary", json=payload_2opt, headers={"X-User-Id": "test_user"})
    assert resp_2opt.status_code == 200
    data_2opt = resp_2opt.json()
    assert data_2opt["status"] == "success"
    assert data_2opt["updated_plan"]["version_id"] == 3
    assert len(data_2opt["updated_plan"]["days"][0]["attractions"]) == 3

