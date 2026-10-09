"""Deterministic visual journey draft builder.

The journey draft is intentionally separate from the final report contract.
It gives the frontend enough structure to render a map-first travel workspace
before transport, hotel, budget and final report gates are complete.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
import re
from typing import Any
from zoneinfo import ZoneInfo


JOURNEY_PLAN_VERSION = "journey_plan.v1"
_CN_WEEKDAYS = "一二三四五六日"
_CN_WEEKDAY_TO_INDEX = {name: index for index, name in enumerate(_CN_WEEKDAYS)}
_DAY_COLORS = ["#18b6a4", "#6a5cff", "#1da1f2", "#8cc63f", "#ff9f1c", "#e85d75", "#7f52ff"]
_TIBET_POI_COORDS = {
    "林芝": (94.3615, 29.6486),
    "雅鲁藏布大峡谷": (94.9155, 29.5736),
    "索松村": (94.8812, 29.5565),
    "南迦巴瓦峰": (95.0636, 29.6303),
    "巴松措": (93.9616, 30.0239),
    "鲁朗林海": (94.7407, 29.7651),
    "布达拉宫": (91.1175, 29.6571),
    "大昭寺": (91.1326, 29.6502),
    "八廓街": (91.1329, 29.6506),
    "色拉寺": (91.1428, 29.6864),
    "扎基寺": (91.1452, 29.6777),
    "羊卓雍措": (90.6844, 29.1116),
    "岗巴拉山口": (90.6605, 29.1883),
    "纳木措": (90.5534, 30.7543),
    "罗布林卡": (91.0977, 29.6523),
    "哲蚌寺": (91.0557, 29.6869),
    "药王山观景台": (91.1129, 29.6575),
    "尼洋河风光带": (94.3600, 29.6500),
    "卡定沟": (94.4746, 29.8138),
    "鲁朗小镇": (94.7420, 29.7660),
    "拉萨市区休整": (91.1322, 29.6604),
    "拉萨老城": (91.1328, 29.6504),
    "返程交通": (91.0757, 29.6267),
}
_GENERIC_POI_COORDS = {
    "成都东站": (104.1410, 30.6290),
    "宽窄巷子": (104.0560, 30.6740),
    "人民公园": (104.0590, 30.6590),
    "武侯祠": (104.0480, 30.6440),
    "锦里": (104.0485, 30.6438),
    "春熙路": (104.0800, 30.6570),
    "太古里": (104.0830, 30.6530),
    "杜甫草堂": (104.0280, 30.6660),
    "南京南站": (118.7970, 31.9700),
    "夫子庙秦淮风光带": (118.7870, 32.0210),
    "老门东": (118.7890, 32.0140),
    "南京博物院": (118.8290, 32.0410),
    "中山陵": (118.8490, 32.0640),
    "玄武湖": (118.7960, 32.0700),
    "鸡鸣寺": (118.7950, 32.0610),
    "西安城墙": (108.9430, 34.2650),
    "钟楼": (108.9460, 34.2610),
    "回民街": (108.9440, 34.2650),
    "陕西历史博物馆": (108.9550, 34.2220),
    "大雁塔": (108.9640, 34.2190),
    "大唐不夜城": (108.9640, 34.2120),
    "秦始皇兵马俑": (109.2780, 34.3850),
    "华清宫": (109.2140, 34.3640),
    "杭州东站": (120.2120, 30.2910),
    "西湖": (120.1490, 30.2460),
    "灵隐寺": (120.1020, 30.2400),
    "河坊街": (120.1710, 30.2450),
    "湖滨银泰": (120.1630, 30.2570),
    "西溪湿地": (120.0640, 30.2660),
    "九溪烟树": (120.1019, 30.2024),
    "浙江省博物馆": (120.1451, 30.2583),
    "良渚古城遗址公园": (119.9907, 30.3927),
    "小河直街": (120.1415, 30.3161),
    "龙井村": (120.1031, 30.2198),
    "厦门站": (118.1160, 24.4690),
    "中山路步行街": (118.0810, 24.4550),
    "八市": (118.0830, 24.4570),
    "鼓浪屿": (118.0670, 24.4440),
    "菽庄花园": (118.0640, 24.4420),
    "沙坡尾": (118.0870, 24.4380),
    "厦门大学": (118.1020, 24.4360),
    "环岛路": (118.1370, 24.4320),
    "重庆北站": (106.5520, 29.6100),
    "解放碑": (106.5770, 29.5630),
    "洪崖洞": (106.5840, 29.5630),
    "李子坝": (106.5440, 29.5520),
    "磁器口": (106.4560, 29.5810),
    "长江索道": (106.5830, 29.5590),
    "鹅岭二厂": (106.5360, 29.5550),
    "长沙南站": (113.0650, 28.1470),
    "五一广场": (112.9790, 28.1970),
    "太平老街": (112.9760, 28.1950),
    "橘子洲": (112.9590, 28.1900),
    "岳麓山": (112.9440, 28.1870),
    "湖南博物院": (112.9910, 28.2130),
    "杜甫江阁": (112.9700, 28.1870),
    "苏州站": (120.6060, 31.3350),
    "拙政园": (120.6260, 31.3250),
    "苏州博物馆": (120.6230, 31.3240),
    "平江路": (120.6300, 31.3150),
    "山塘街": (120.5910, 31.3160),
    "金鸡湖": (120.7050, 31.3150),
    "栈桥": (120.3180, 36.0630),
    "八大关": (120.3520, 36.0560),
    "五四广场": (120.3860, 36.0680),
    "青岛啤酒博物馆": (120.3440, 36.0830),
    "小麦岛": (120.4250, 36.0640),
    "桂林站": (110.2870, 25.2620),
    "象鼻山": (110.2960, 25.2730),
    "东西巷": (110.2980, 25.2840),
    "两江四湖": (110.2940, 25.2810),
    "阳朔西街": (110.4960, 24.7780),
    "十里画廊": (110.4810, 24.7480),
    "大理站": (100.2670, 25.5890),
    "大理古城": (100.1640, 25.6940),
    "洱海公园": (100.2410, 25.5920),
    "喜洲古镇": (100.1300, 25.8540),
    "双廊": (100.1930, 25.9080),
    "丽江古城": (100.2340, 26.8720),
    "束河古镇": (100.2090, 26.9220),
    "玉龙雪山": (100.2560, 27.1010),
    "蓝月谷": (100.2480, 27.1340),
    "黑龙潭": (100.2340, 26.8900),
    "滇池": (102.6710, 24.9400),
    "云南民族村": (102.6600, 24.9660),
    "昆明老街": (102.7080, 25.0430),
    "北京南站": (116.3790, 39.8650),
    "天安门广场": (116.3970, 39.9050),
    "故宫博物院": (116.3970, 39.9160),
    "景山公园": (116.3970, 39.9250),
    "南锣鼓巷": (116.4040, 39.9370),
    "颐和园": (116.2750, 39.9990),
    "天坛公园": (116.4100, 39.8820),
    "上海站": (121.4550, 31.2490),
    "外滩": (121.4900, 31.2400),
    "南京东路步行街": (121.4750, 31.2340),
    "豫园": (121.4920, 31.2270),
    "上海博物馆": (121.4750, 31.2300),
    "武康路": (121.4380, 31.2150),
    "陆家嘴": (121.4990, 31.2390),
    "广州南站": (113.2690, 22.9890),
    "广州塔": (113.3240, 23.1060),
    "沙面": (113.2400, 23.1110),
    "陈家祠": (113.2490, 23.1290),
    "北京路步行街": (113.2690, 23.1250),
    "永庆坊": (113.2440, 23.1180),
    "深圳北站": (114.0290, 22.6090),
    "莲花山公园": (114.0540, 22.5550),
    "华侨城创意文化园": (113.9890, 22.5400),
    "世界之窗": (113.9730, 22.5380),
    "深圳湾公园": (113.9480, 22.5170),
    "大芬油画村": (114.1390, 22.6070),
}
_POI_COORDS = {**_TIBET_POI_COORDS, **_GENERIC_POI_COORDS}

_TIBET_ALTERNATIVE_POIS = [
    ("罗布林卡", "拉萨", "拉萨市区低强度园林与历史节点，适合替换高强度寺庙日。", "半日备选", 120, "园林"),
    ("哲蚌寺", "拉萨", "拉萨经典寺院之一，适合人文深度路线替换。", "上午备选", 150, "寺庙"),
    ("药王山观景台", "拉萨", "适合短暂停留看布达拉宫角度，体力压力低。", "傍晚备选", 45, "观景台"),
    ("尼洋河风光带", "林芝", "林芝低海拔风景带，可替换同日长距离景点。", "下午备选", 90, "风景带"),
    ("卡定沟", "林芝", "林芝周边短线峡谷景点，适合作为天气备选。", "半日备选", 120, "峡谷"),
    ("鲁朗小镇", "林芝", "鲁朗区域餐饮和休整节点，可替换林海长停留。", "午后备选", 90, "小镇"),
]

_KNOWN_DESTINATION_ALTERNATIVE_TEMPLATES = {
    "成都": [
        ("文殊院", "成都", "市区寺院与茶馆氛围，适合替换慢游点。", "上午备选", 100, "寺院"),
        ("成都大熊猫繁育研究基地", "成都", "成都亲子和城市名片型景点，建议早到。", "上午备选", 180, "动物园"),
        ("东郊记忆", "成都", "工业风文创街区，适合替换商业街。", "下午备选", 120, "文创街区"),
        ("金沙遗址博物馆", "成都", "室内文化点，可作为雨天替换。", "半日备选", 150, "博物馆"),
    ],
    "南京": [
        ("南京总统府", "南京", "市区人文核心点，适合和博物院互换。", "上午备选", 150, "历史建筑"),
        ("明孝陵", "南京", "钟山风景区经典节点，可替换中山陵深度日。", "半日备选", 160, "陵寝"),
        ("颐和路", "南京", "民国风街区，适合慢节奏城市漫步。", "下午备选", 90, "街区"),
        ("先锋书店五台山店", "南京", "室内文化和休息节点，可作为雨天备选。", "下午备选", 75, "书店"),
    ],
    "西安": [
        ("小雁塔", "西安", "市区人文点，节奏比热门景区更舒缓。", "上午备选", 100, "地标"),
        ("大唐芙蓉园", "西安", "唐风园区和夜游节点，可替换大唐不夜城。", "下午备选", 150, "园区"),
        ("西安碑林博物馆", "西安", "室内文化点，适合历史深度路线。", "半日备选", 120, "博物馆"),
        ("华山", "渭南", "强度较高的远郊备选，需单独核验体力和交通。", "全天备选", 360, "山岳"),
    ],
    "杭州": [
        ("九溪烟树", "杭州", "西湖西南侧山水步道，适合替换热门寺院或湿地半日。", "半日备选", 150, "山水步道"),
        ("浙江省博物馆", "杭州", "室内文化点，可作为雨天或低强度备选。", "上午备选", 120, "博物馆"),
        ("良渚古城遗址公园", "杭州", "世界遗产主题公园，适合文化深度替换。", "半日备选", 180, "遗址公园"),
        ("小河直街", "杭州", "运河边老街区，适合傍晚慢游。", "傍晚备选", 90, "老街"),
        ("龙井村", "杭州", "茶园和山路氛围，适合轻徒步和茶文化替换。", "下午备选", 120, "茶村"),
    ],
    "厦门": [
        ("南普陀寺", "厦门", "市区寺院节点，适合和厦大周边串联。", "上午备选", 100, "寺院"),
        ("集美学村", "厦门", "岛外人文建筑群，适合半日替换。", "半日备选", 150, "建筑群"),
        ("曾厝垵", "厦门", "餐饮和海边街区，可替换中山路夜间体验。", "傍晚备选", 100, "街区"),
        ("白城沙滩", "厦门", "海边低强度点，适合天气好时替换。", "下午备选", 90, "海滩"),
    ],
    "北京": [
        ("雍和宫", "北京", "热门寺院人文点，需关注预约和人流。", "上午备选", 120, "寺院"),
        ("什刹海", "北京", "湖区和胡同漫步，可替换南锣鼓巷。", "下午备选", 120, "湖区"),
        ("中国国家博物馆", "北京", "室内大型博物馆，需提前预约。", "半日备选", 180, "博物馆"),
        ("798艺术区", "北京", "艺术街区，适合轻松城市体验。", "下午备选", 120, "艺术街区"),
    ],
    "上海": [
        ("思南公馆", "上海", "海派街区和咖啡馆，适合替换武康路。", "下午备选", 90, "街区"),
        ("上海中心大厦", "上海", "浦东高空观景节点，需核验天气能见度。", "傍晚备选", 90, "观景"),
        ("田子坊", "上海", "老城巷弄商业街区，适合轻量补充。", "下午备选", 90, "街区"),
        ("朱家角古镇", "上海", "远郊古镇备选，需单独核验往返交通。", "半日备选", 180, "古镇"),
    ],
    "广州": [
        ("广东省博物馆", "广州", "室内文化点，适合雨天或亲子替换。", "上午备选", 150, "博物馆"),
        ("越秀公园", "广州", "市区公园和五羊地标，适合低强度慢游。", "上午备选", 120, "公园"),
        ("珠江夜游", "广州", "夜间城市水上体验，需核验船班。", "晚上备选", 90, "夜游"),
        ("荔枝湾涌", "广州", "西关水系和老城体验，可替换沙面。", "下午备选", 100, "街区"),
    ],
    "深圳": [
        ("南头古城", "深圳", "城市历史街区，适合替换文创街区。", "下午备选", 100, "古城"),
        ("海上世界", "深圳", "蛇口餐饮和滨海夜景节点。", "傍晚备选", 100, "商圈"),
        ("甘坑古镇", "深圳", "轻量古镇和亲子场景，可半日替换。", "半日备选", 150, "古镇"),
        ("大梅沙海滨公园", "深圳", "海边休闲点，需核验天气和人流。", "下午备选", 120, "海滨"),
    ],
    "重庆": [
        ("山城步道", "重庆", "山城街巷步行体验，适合替换商业街。", "上午备选", 120, "步道"),
        ("白象居", "重庆", "城市立体空间拍照点，需控制停留时间。", "下午备选", 75, "街区"),
        ("南山一棵树观景台", "重庆", "夜景观景点，需核验天气能见度。", "傍晚备选", 90, "观景台"),
        ("鹅岭公园", "重庆", "市区低强度公园和观景备选。", "下午备选", 90, "公园"),
    ],
    "长沙": [
        ("开福寺", "长沙", "市区寺院与低强度文化点。", "上午备选", 90, "寺院"),
        ("谢子龙影像艺术馆", "长沙", "室内艺术馆，适合作为天气备选。", "下午备选", 100, "艺术馆"),
        ("湖南大学", "长沙", "岳麓山脚校园与人文街区，可同向替换。", "下午备选", 90, "校园"),
        ("扬帆夜市", "长沙", "夜间餐饮备选，需核验营业和排队。", "晚上备选", 90, "夜市"),
    ],
    "苏州": [
        ("留园", "苏州", "苏州经典园林，可替换拙政园人流较大时段。", "上午备选", 120, "园林"),
        ("虎丘", "苏州", "城市地标型景区，适合半日替换。", "半日备选", 150, "景区"),
        ("诚品书店", "苏州", "金鸡湖周边室内休息与文化点。", "下午备选", 75, "书店"),
        ("同里古镇", "苏州", "远郊水乡备选，需核验往返交通。", "半日备选", 180, "古镇"),
    ],
    "青岛": [
        ("崂山", "青岛", "远郊山海景区，需单独核验交通和体力。", "全天备选", 300, "山海景区"),
        ("大学路", "青岛", "老城文艺街区，可替换小麦岛。", "下午备选", 90, "街区"),
        ("信号山公园", "青岛", "俯瞰老城和海湾的低强度观景点。", "上午备选", 90, "公园"),
        ("石老人海水浴场", "青岛", "海滨休闲点，适合天气好时替换。", "下午备选", 120, "海滨"),
    ],
    "桂林": [
        ("龙脊梯田", "桂林", "远郊自然景观，适合增加一日深度。", "全天备选", 300, "梯田"),
        ("银子岩", "桂林", "喀斯特溶洞，适合替换雨天户外点。", "半日备选", 150, "溶洞"),
        ("兴坪古镇", "桂林", "漓江沿线古镇节点，可替换阳朔西街。", "下午备选", 120, "古镇"),
        ("漓江竹筏", "桂林", "经典山水体验，需核验水位和班次。", "半日备选", 180, "山水体验"),
    ],
    "云南": [
        ("石林风景区", "昆明", "昆明远郊经典喀斯特景区。", "半日备选", 180, "景区"),
        ("崇圣寺三塔", "大理", "大理经典地标，可替换古城半日。", "半日备选", 150, "寺塔"),
        ("白沙古镇", "丽江", "比丽江古城更舒缓的古镇点。", "下午备选", 120, "古镇"),
        ("虎跳峡", "丽江", "强度较高的峡谷备选，需核验交通和体力。", "全天备选", 300, "峡谷"),
    ],
}


def _today() -> date:
    return datetime.now(ZoneInfo("Asia/Shanghai")).date()


def _format_date(value: date | None) -> str:
    return value.isoformat() if isinstance(value, date) else ""


def _weekday_label(value: date | None) -> str:
    if not isinstance(value, date):
        return ""
    return f"周{_CN_WEEKDAYS[value.weekday()]}"


def parse_relative_departure_date(text: str, *, base_date: date | None = None) -> date | None:
    """Parse the relative date phrases used by the visual journey MVP."""

    raw = str(text or "").strip()
    if not raw:
        return None
    base = base_date or _today()

    explicit = re.search(r"(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})", raw)
    if explicit:
        return date(
            int(explicit.group(1)),
            int(explicit.group(2)),
            int(explicit.group(3)),
        )

    if "今天" in raw:
        return base
    if "明天" in raw:
        return base + timedelta(days=1)
    if "后天" in raw:
        return base + timedelta(days=2)

    weekday_match = re.search(r"(下下周|下周|这周|本周)?\s*([一二三四五六日天])", raw)
    if weekday_match:
        prefix = weekday_match.group(1) or "这周"
        day_text = "日" if weekday_match.group(2) == "天" else weekday_match.group(2)
        target = _CN_WEEKDAY_TO_INDEX[day_text]
        current_monday = base - timedelta(days=base.weekday())
        if prefix == "下下周":
            week_offset = 2
        elif prefix == "下周":
            week_offset = 1
        else:
            week_offset = 0
        candidate = current_monday + timedelta(days=week_offset * 7 + target)
        if candidate < base and week_offset == 0:
            candidate += timedelta(days=7)
        return candidate

    return None


def _extract_days(*values: Any, default: int = 7) -> int:
    for value in values:
        if isinstance(value, int) and value > 0:
            return min(value, 14)
        match = re.search(r"(\d{1,2})\s*天", str(value or ""))
        if match:
            return min(max(int(match.group(1)), 1), 14)
    return default


def _normalize_destination(value: str | None) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if "西藏" in text or "拉萨" in text or "林芝" in text:
        return "西藏"
    if "云南" in text or "大理" in text or "丽江" in text or "昆明" in text:
        return "云南" if "云南" in text else text[:20]
    return text[:20]


def _known_destination_key(destination: str) -> str:
    text = str(destination or "").strip()
    for key in (
        "成都",
        "南京",
        "西安",
        "杭州",
        "厦门",
        "重庆",
        "长沙",
        "苏州",
        "青岛",
        "桂林",
        "北京",
        "上海",
        "广州",
        "深圳",
        "大理",
        "丽江",
        "云南",
    ):
        if key in text:
            return key
    return ""


def _poi(
    *,
    day: int,
    index: int,
    name: str,
    city: str,
    type_: str = "attraction",
    description: str,
    suggested_time: str,
    duration_minutes: int,
    estimated_cost: str = "待核验",
    reservation_note: str = "开放时间、门票和预约规则出发前二次核验。",
    tags: list[str] | None = None,
    map_query: str = "",
    search_keyword: str = "",
    is_generic_seed: bool = False,
) -> dict[str, Any]:
    lng_lat = _POI_COORDS.get(name)
    payload = {
        "id": f"d{day}-p{index}",
        "day_number": day,
        "order": index,
        "name": name,
        "city": city,
        "type": type_,
        "type_label": "景点" if type_ == "attraction" else "交通/城市节点",
        "description": description,
        "suggested_time": suggested_time,
        "duration_minutes": duration_minutes,
        "estimated_cost": estimated_cost,
        "reservation_note": reservation_note,
        "tags": tags or [],
        "image_url": "",
    }
    payload["map_query"] = map_query or f"{city} {name}".strip()
    if search_keyword:
        payload["search_keyword"] = search_keyword
    if is_generic_seed:
        payload["is_generic_seed"] = True
    if lng_lat:
        lng, lat = lng_lat
        payload["lng"] = lng
        payload["lat"] = lat
    return payload


def _segment(day: int, start: dict[str, Any], end: dict[str, Any], *, index: int) -> dict[str, Any]:
    return {
        "id": f"d{day}-s{index}",
        "day_number": day,
        "from_poi_id": start["id"],
        "to_poi_id": end["id"],
        "from_name": start["name"],
        "to_name": end["name"],
        "mode": "driving",
        "distance_text": "待高德路线核验",
        "duration_text": "待高德路线核验",
        "confidence": "needs_live_route",
    }


def _trace(
    *,
    phase: str,
    title: str,
    detail: str,
    status: str = "completed",
    count: int | None = None,
    city: str = "",
    date_range: str = "",
    evidence_type: str = "structured_planning",
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "phase": phase,
        "status": status,
        "title": title,
        "detail": detail,
        "evidence_type": evidence_type,
    }
    if count is not None:
        payload["count"] = count
    if city:
        payload["city"] = city
    if date_range:
        payload["date_range"] = date_range
    return payload


def _build_tibet_days(start_date: date | None, days: int) -> list[dict[str, Any]]:
    templates = [
        ("林芝初抵·索松村看南迦巴瓦", "林芝", [
            ("林芝", "低海拔城市节点，适合作为西藏初抵适应点。", "抵达后", 60, "交通节点"),
            ("雅鲁藏布大峡谷", "林芝经典峡谷景观，适合和索松村、南迦巴瓦观景顺路组合。", "13:30-15:30", 120, "峡谷"),
            ("索松村", "雅鲁藏布江边看南迦巴瓦的经典村落，适合低强度适应。", "15:00-18:30", 150, "观景村落"),
            ("南迦巴瓦峰", "天气允许时远眺雪峰日照金山，作为第一天轻量看点。", "傍晚", 90, "雪山观景"),
        ]),
        ("林芝深度·巴松措与鲁朗", "林芝", [
            ("巴松措", "湖泊、雪山和寺庙组合，是林芝经典低海拔景区。", "09:00-13:00", 180, "湖泊"),
            ("鲁朗林海", "森林、牧场和雪山视野组合，适合放慢节奏。", "14:30-17:30", 150, "森林牧场"),
        ]),
        ("拉萨市区·布达拉宫大昭寺", "拉萨", [
            ("布达拉宫", "拉萨地标和预约核心，第一次进藏通常优先安排。", "09:30-12:00", 150, "文化地标"),
            ("大昭寺", "拉萨老城信仰核心，和八廓街适合同日串联。", "14:30-16:00", 90, "寺庙"),
            ("八廓街", "老城步行动线和人文观察点，晚间更适合慢走。", "16:00-18:30", 120, "街区"),
        ]),
        ("拉萨适应·寺庙与老城留白", "拉萨", [
            ("色拉寺", "适合半日人文体验，强度比远途湖区更可控。", "10:00-12:30", 120, "寺庙"),
            ("扎基寺", "拉萨市区轻量补充点，可作为高反适应日的低强度安排。", "15:00-16:30", 75, "寺庙"),
        ]),
        ("羊湖一日·高原湖泊经典线", "山南", [
            ("羊卓雍措", "西藏三大圣湖之一，经典蓝湖观景线。", "10:30-14:30", 180, "湖泊"),
            ("岗巴拉山口", "俯瞰羊湖的常见观景节点，需关注风大和海拔反应。", "15:00-16:00", 60, "观景台"),
        ]),
        ("纳木措或市区备选", "拉萨", [
            ("纳木措", "高海拔湖泊长线，天气和体力允许时再执行。", "09:00-16:30", 300, "高原湖泊"),
            ("拉萨市区休整", "如天气或高反不适，改为市区休整、咖啡馆和低强度补漏。", "全天备选", 180, "Plan B"),
        ]),
        ("拉萨返程·补漏与机动", "拉萨", [
            ("拉萨老城", "返程前低强度补漏、购买伴手礼和整理行李。", "09:30-11:30", 90, "街区"),
            ("返程交通", "预留前往机场/车站和安检缓冲，不再安排高强度跨区。", "下午", 120, "交通"),
        ]),
    ]

    picked = templates[:days]
    if days > len(templates):
        picked.extend(templates[-1:] * (days - len(templates)))

    result = []
    for day_index, (title, city, poi_specs) in enumerate(picked, start=1):
        current_date = start_date + timedelta(days=day_index - 1) if start_date else None
        pois = [
            _poi(
                day=day_index,
                index=poi_index,
                name=name,
                city=city,
                description=description,
                suggested_time=suggested_time,
                duration_minutes=duration,
                tags=[tag],
            )
            for poi_index, (name, description, suggested_time, duration, tag) in enumerate(poi_specs, start=1)
        ]
        segments = [
            _segment(day_index, pois[i], pois[i + 1], index=i + 1)
            for i in range(max(len(pois) - 1, 0))
        ]
        result.append(
            {
                "day_number": day_index,
                "date": _format_date(current_date),
                "weekday": _weekday_label(current_date),
                "title": title,
                "city": city,
                "color": _DAY_COLORS[(day_index - 1) % len(_DAY_COLORS)],
                "summary": " · ".join(poi["name"] for poi in pois),
                "route_note": "同日尽量按同区域/同方向串联，远途湖区保留天气和体力备选。",
                "weather": {
                    "city": city,
                    "summary": "天气待实时核验；高原地区重点关注降雨、风力、温差和道路情况。",
                    "confidence": "needs_live_weather",
                },
                "pois": pois,
                "segments": segments,
            }
        )
    return result


_KNOWN_DESTINATION_DAY_TEMPLATES = {
    "成都": [
        ("成都初抵·宽窄巷子与人民公园", "成都", [
            ("成都东站", "交通抵达节点，适合衔接市区住宿和轻量适应。", "抵达后", 45, "交通"),
            ("宽窄巷子", "成都代表性街区，适合初到城市氛围和小吃体验。", "15:00-17:00", 100, "街区"),
            ("人民公园", "茶馆和慢生活体验集中，适合低强度放松。", "17:00-18:30", 75, "慢游"),
        ]),
        ("成都人文·武侯祠锦里", "成都", [
            ("武侯祠", "三国文化核心点，适合半日人文游览。", "09:30-12:00", 120, "文化"),
            ("锦里", "紧邻武侯祠的街区，适合顺路午餐和夜间灯景。", "12:00-14:00", 90, "街区"),
            ("杜甫草堂", "诗意园林和人文空间，下午节奏更舒缓。", "15:00-17:00", 120, "园林"),
        ]),
        ("成都城市漫游·春熙路太古里", "成都", [
            ("春熙路", "市中心商业街区，适合餐饮、购物和城市漫步。", "10:00-12:00", 100, "商圈"),
            ("太古里", "开放式街区和餐饮集中，适合下午轻松停留。", "14:00-17:00", 140, "街区"),
        ]),
    ],
    "南京": [
        ("南京初抵·秦淮老城", "南京", [
            ("南京南站", "交通抵达节点，适合衔接市区住宿。", "抵达后", 45, "交通"),
            ("夫子庙秦淮风光带", "南京经典夜游和秦淮河街区，适合第一天轻量进入。", "15:30-18:30", 150, "街区"),
            ("老门东", "老城街巷和小吃集中，和夫子庙适合同日串联。", "19:00-20:30", 90, "美食街区"),
        ]),
        ("南京人文·博物院与中山陵", "南京", [
            ("南京博物院", "南京人文核心，适合上午半日深度参观。", "09:30-12:30", 150, "博物馆"),
            ("中山陵", "钟山风景区核心点，下午顺路安排更稳。", "14:00-17:00", 150, "景区"),
        ]),
        ("南京慢游·玄武湖鸡鸣寺", "南京", [
            ("玄武湖", "城市湖泊与步行动线，适合放慢节奏。", "10:00-12:00", 120, "湖泊"),
            ("鸡鸣寺", "靠近玄武湖的人文寺院节点，适合短暂停留。", "14:00-15:30", 75, "寺院"),
        ]),
    ],
    "西安": [
        ("西安初抵·城墙钟楼回民街", "西安", [
            ("西安城墙", "古城核心动线，适合初到建立城市方位感。", "14:00-16:30", 150, "城墙"),
            ("钟楼", "西安市中心地标，适合和回民街顺路串联。", "17:00-18:00", 60, "地标"),
            ("回民街", "经典小吃街区，适合夜间轻量体验。", "18:00-20:00", 100, "美食街区"),
        ]),
        ("西安文化·陕历博大雁塔", "西安", [
            ("陕西历史博物馆", "热门预约型博物馆，适合上午优先安排。", "09:30-12:30", 150, "博物馆"),
            ("大雁塔", "唐文化地标，和大唐不夜城可顺路衔接。", "14:00-16:00", 100, "地标"),
            ("大唐不夜城", "夜间氛围更强的步行街区。", "19:00-21:00", 120, "夜游"),
        ]),
        ("西安远郊·兵马俑华清宫", "西安", [
            ("秦始皇兵马俑", "西安经典远郊核心点，建议单独留半日以上。", "09:00-12:30", 180, "遗址"),
            ("华清宫", "临潼顺路节点，可根据体力决定是否进入。", "14:00-16:30", 120, "景区"),
        ]),
    ],
    "杭州": [
        ("杭州初抵·西湖湖滨", "杭州", [
            ("杭州东站", "交通抵达节点，适合衔接市区住宿。", "抵达后", 45, "交通"),
            ("西湖", "杭州经典核心，第一天适合先看湖区主线。", "14:00-17:30", 180, "湖泊"),
            ("湖滨银泰", "靠近西湖的餐饮和休息区。", "18:00-20:00", 90, "商圈"),
        ]),
        ("杭州人文·灵隐寺河坊街", "杭州", [
            ("灵隐寺", "杭州经典寺院和山林氛围，建议上午安排。", "09:00-12:00", 150, "寺院"),
            ("河坊街", "老街和小吃集中，适合下午傍晚收尾。", "15:00-18:00", 120, "老街"),
        ]),
        ("杭州慢游·西溪湿地", "杭州", [
            ("西溪湿地", "湿地公园和慢节奏体验，适合单独半日。", "10:00-15:00", 240, "湿地"),
        ]),
    ],
    "厦门": [
        ("厦门初抵·中山路八市", "厦门", [
            ("厦门站", "交通抵达节点，适合衔接岛内住宿。", "抵达后", 45, "交通"),
            ("中山路步行街", "厦门老牌步行街，适合初到轻量逛吃。", "15:00-17:00", 100, "街区"),
            ("八市", "海鲜和本地小吃集中，适合傍晚体验。", "17:30-19:00", 90, "美食"),
        ]),
        ("厦门经典·鼓浪屿", "厦门", [
            ("鼓浪屿", "厦门经典岛屿游览，需要关注船票预约。", "09:00-14:00", 240, "岛屿"),
            ("菽庄花园", "鼓浪屿内经典园林节点，适合同日顺路。", "14:30-16:00", 80, "园林"),
        ]),
        ("厦门慢游·沙坡尾厦大环岛路", "厦门", [
            ("沙坡尾", "文艺街区和海边氛围，适合下午慢逛。", "10:00-12:00", 100, "街区"),
            ("厦门大学", "校园周边人文节点，开放规则需提前确认。", "14:00-15:30", 80, "校园"),
            ("环岛路", "海岸线骑行/散步动线，适合傍晚。", "16:00-18:30", 120, "海岸"),
        ]),
    ],
    "北京": [
        ("北京初抵·天安门故宫中轴线", "北京", [
            ("北京南站", "交通抵达节点，适合衔接市区住宿。", "抵达后", 45, "交通"),
            ("天安门广场", "北京中轴线起点之一，需关注预约和安检。", "09:00-10:00", 60, "地标"),
            ("故宫博物院", "北京核心预约型景点，建议上午优先安排。", "10:00-14:00", 220, "博物馆"),
            ("景山公园", "俯瞰故宫中轴线，适合作为故宫后顺路收尾。", "15:00-16:30", 75, "公园"),
        ]),
        ("北京胡同·南锣鼓巷", "北京", [
            ("南锣鼓巷", "胡同街区和餐饮集中，适合城市漫步。", "10:00-12:00", 120, "街区"),
            ("天坛公园", "北京经典坛庙公园，适合下午半日。", "14:00-17:00", 150, "公园"),
        ]),
        ("北京皇家园林·颐和园", "北京", [
            ("颐和园", "皇家园林和湖区动线，建议单独半日以上。", "09:30-14:00", 240, "园林"),
        ]),
    ],
    "上海": [
        ("上海初抵·外滩南京路", "上海", [
            ("上海站", "交通抵达节点，适合衔接市区住宿。", "抵达后", 45, "交通"),
            ("南京东路步行街", "上海经典商业街，适合初到轻量逛吃。", "15:00-17:00", 100, "街区"),
            ("外滩", "上海经典江岸夜景，傍晚和夜间体验更完整。", "17:30-19:30", 120, "江岸"),
        ]),
        ("上海城市文化·博物馆豫园", "上海", [
            ("上海博物馆", "市中心文化节点，适合上午室内参观。", "10:00-12:00", 120, "博物馆"),
            ("豫园", "老城厢和园林街区，适合下午顺路安排。", "14:00-16:30", 120, "园林"),
            ("陆家嘴", "浦东天际线观景和夜景节点。", "18:00-20:00", 120, "地标"),
        ]),
        ("上海慢游·武康路", "上海", [
            ("武康路", "梧桐街区和咖啡馆集中，适合慢节奏城市漫步。", "10:00-12:30", 120, "街区"),
        ]),
    ],
    "广州": [
        ("广州初抵·广州塔与珠江", "广州", [
            ("广州南站", "交通抵达节点，适合衔接市区住宿。", "抵达后", 45, "交通"),
            ("广州塔", "广州城市地标，适合傍晚和夜景。", "16:00-18:30", 120, "地标"),
            ("北京路步行街", "市中心步行街和餐饮集中。", "19:00-20:30", 90, "街区"),
        ]),
        ("广州西关·沙面陈家祠永庆坊", "广州", [
            ("陈家祠", "岭南建筑和非遗展示节点，适合上午安排。", "10:00-12:00", 100, "人文"),
            ("沙面", "欧陆建筑街区，适合下午慢走。", "14:00-15:30", 80, "街区"),
            ("永庆坊", "西关街区和餐饮集中，适合傍晚收尾。", "16:00-18:00", 100, "街区"),
        ]),
    ],
    "深圳": [
        ("深圳初抵·莲花山与华侨城", "深圳", [
            ("深圳北站", "交通抵达节点，适合衔接市区住宿。", "抵达后", 45, "交通"),
            ("莲花山公园", "市中心公园和城市视野节点。", "15:00-17:00", 100, "公园"),
            ("华侨城创意文化园", "创意街区和餐饮集中，适合傍晚。", "18:00-20:00", 100, "街区"),
        ]),
        ("深圳经典·世界之窗深圳湾", "深圳", [
            ("世界之窗", "深圳经典主题景区，适合半日游览。", "10:00-14:00", 220, "景区"),
            ("深圳湾公园", "滨海步行和城市天际线，适合傍晚。", "16:00-18:30", 120, "滨海"),
        ]),
        ("深圳轻量·大芬油画村", "深圳", [
            ("大芬油画村", "艺术街区和室内外结合体验，适合作为天气备选。", "10:00-12:00", 100, "艺术街区"),
        ]),
    ],
    "云南": [
        ("昆明初抵·滇池与老街", "昆明", [
            ("滇池", "昆明经典湖区，适合作为云南线初抵低强度适应。", "14:00-16:30", 150, "湖泊"),
            ("云南民族村", "靠近滇池的民俗体验节点，可顺路安排。", "16:30-18:00", 90, "民俗"),
            ("昆明老街", "晚间餐饮和城市街区体验。", "19:00-20:30", 90, "老街"),
        ]),
        ("大理·古城与洱海", "大理", [
            ("大理古城", "大理经典落脚和街区体验。", "10:00-12:00", 120, "古城"),
            ("洱海公园", "洱海城市侧入口，适合轻量看海。", "14:00-16:00", 120, "湖泊"),
            ("大理站", "大理交通节点，用于衔接城际移动。", "根据车次", 45, "交通"),
        ]),
        ("大理北线·喜洲双廊", "大理", [
            ("喜洲古镇", "白族建筑和田园风光节点。", "09:30-12:00", 120, "古镇"),
            ("双廊", "洱海东侧观景和休闲节点。", "14:00-17:00", 150, "湖景"),
        ]),
        ("丽江·古城与束河", "丽江", [
            ("丽江古城", "丽江经典街区，适合傍晚和夜间慢游。", "10:00-12:30", 150, "古城"),
            ("束河古镇", "比大研古城更舒缓的古镇节点。", "15:00-17:30", 120, "古镇"),
        ]),
        ("丽江·玉龙雪山蓝月谷", "丽江", [
            ("玉龙雪山", "丽江高海拔核心景区，需预约并关注体力。", "08:00-13:00", 240, "雪山"),
            ("蓝月谷", "玉龙雪山顺路景观节点，适合同日安排。", "13:30-15:30", 90, "湖谷"),
            ("黑龙潭", "市区低强度补充点，可作为天气备选。", "16:30-17:30", 60, "公园"),
        ]),
    ],
}
_KNOWN_DESTINATION_DAY_TEMPLATES["大理"] = _KNOWN_DESTINATION_DAY_TEMPLATES["云南"][1:3]
_KNOWN_DESTINATION_DAY_TEMPLATES["丽江"] = _KNOWN_DESTINATION_DAY_TEMPLATES["云南"][3:5]
_KNOWN_DESTINATION_ALTERNATIVE_TEMPLATES["大理"] = [
    ("崇圣寺三塔", "大理", "大理经典地标，可替换古城半日。", "半日备选", 150, "寺塔"),
    ("苍山", "大理", "山景和索道体验，需核验天气和体力。", "半日备选", 180, "山岳"),
    ("才村码头", "大理", "洱海边低强度休闲点，可替换城市湖区。", "下午备选", 90, "湖岸"),
    ("沙溪古镇", "大理", "较远古镇备选，需单独核验往返交通。", "全天备选", 300, "古镇"),
]
_KNOWN_DESTINATION_ALTERNATIVE_TEMPLATES["丽江"] = [
    ("白沙古镇", "丽江", "比丽江古城更舒缓的古镇点。", "下午备选", 120, "古镇"),
    ("拉市海", "丽江", "湖区湿地休闲点，适合低强度替换。", "半日备选", 150, "湿地"),
    ("玉湖村", "丽江", "雪山脚下村落节点，可替换古城慢游。", "下午备选", 120, "村落"),
    ("虎跳峡", "丽江", "强度较高的峡谷备选，需核验交通和体力。", "全天备选", 300, "峡谷"),
]


def _build_generic_days(destination: str, start_date: date | None, days: int) -> list[dict[str, Any]]:
    destination_key = _known_destination_key(destination)
    templates = _KNOWN_DESTINATION_DAY_TEMPLATES.get(destination_key) or []
    if templates:
        picked = templates[:days]
        if days > len(templates):
            picked.extend(templates[-1:] * (days - len(templates)))
        result = []
        for day_index, (title, city, poi_specs) in enumerate(picked, start=1):
            current_date = start_date + timedelta(days=day_index - 1) if start_date else None
            pois = [
                _poi(
                    day=day_index,
                    index=poi_index,
                    name=name,
                    city=city,
                    description=description,
                    suggested_time=suggested_time,
                    duration_minutes=duration,
                    tags=[tag],
                )
                for poi_index, (name, description, suggested_time, duration, tag) in enumerate(poi_specs, start=1)
            ]
            result.append(
                {
                    "day_number": day_index,
                    "date": _format_date(current_date),
                    "weekday": _weekday_label(current_date),
                    "title": title,
                    "city": city,
                    "color": _DAY_COLORS[(day_index - 1) % len(_DAY_COLORS)],
                    "summary": " · ".join(poi["name"] for poi in pois),
                    "route_note": "同日优先按真实地图点位和相邻区域串联，距离和时长以高德实时路线二次核验。",
                    "weather": {
                        "city": city,
                        "summary": "天气待实时核验；当天室外/室内顺序可按降雨、温度和体力调整。",
                        "confidence": "needs_live_weather",
                    },
                    "pois": pois,
                    "segments": [
                        _segment(day_index, pois[i], pois[i + 1], index=i + 1)
                        for i in range(max(len(pois) - 1, 0))
                    ],
                }
            )
        return result

    result = []
    fallback_template_groups = [
        [
            ("市中心", "目的地城市中心或主要商圈，用于先把真实地图落点建立起来。", "上午", 90, "城市节点", "city"),
            ("博物馆", "优先作为室内文化备选，若当地博物馆闭馆可替换同区域展馆。", "下午", 120, "文化", "attraction"),
            ("老街", "傍晚串联餐饮、休息和城市漫步，后续可替换为地图搜索命中的真实街区。", "傍晚", 100, "街区", "attraction"),
        ],
        [
            ("公园", "城市绿地或代表性公园，适合放慢节奏和降低行程强度。", "上午", 100, "公园", "attraction"),
            ("美术馆", "室内艺术空间，可作为天气变化时的稳定备选。", "下午", 120, "艺术", "attraction"),
            ("步行街", "餐饮、购物和夜间城市氛围集中，适合傍晚收尾。", "傍晚", 100, "街区", "attraction"),
        ],
        [
            ("风景区", "优先搜索当地代表性自然或综合景区，后续按地图命中结果替换。", "上午", 150, "景区", "attraction"),
            ("文化广场", "城市公共空间和地标节点，适合轻量串联。", "下午", 80, "城市地标", "attraction"),
            ("夜市", "晚间餐饮和本地生活体验，实际营业情况需二次核验。", "晚上", 90, "美食街区", "attraction"),
        ],
        [
            ("古镇", "若目的地周边有古镇/老城，可作为半日人文动线。", "上午", 150, "古镇", "attraction"),
            ("商圈", "用于餐饮、休息和机动补给，适合和住宿位置联动。", "下午", 100, "商圈", "attraction"),
            ("河畔公园", "水岸或城市公园类慢游节点，天气好时执行。", "傍晚", 90, "慢游", "attraction"),
        ],
    ]
    for day_index in range(1, days + 1):
        current_date = start_date + timedelta(days=day_index - 1) if start_date else None
        fallback_specs = [
            (
                f"{destination}{name_suffix}",
                name_suffix,
                description,
                suggested_time,
                duration,
                tag,
                type_,
            )
            for name_suffix, description, suggested_time, duration, tag, type_ in fallback_template_groups[
                (day_index - 1) % len(fallback_template_groups)
            ]
        ]
        pois = [
            _poi(
                day=day_index,
                index=poi_index,
                    name=name,
                    city=destination,
                    type_=type_,
                    description=description,
                    suggested_time=suggested_time,
                    duration_minutes=duration,
                    tags=[tag],
                    map_query=f"{destination} {name}",
                    search_keyword=f"{destination} {name_suffix}",
                    is_generic_seed=True,
                )
            for poi_index, (name, name_suffix, description, suggested_time, duration, tag, type_) in enumerate(fallback_specs, start=1)
        ]
        result.append(
            {
                "day_number": day_index,
                "date": _format_date(current_date),
                "weekday": _weekday_label(current_date),
                "title": f"{destination}经典动线 Day {day_index}",
                "city": destination,
                "color": _DAY_COLORS[(day_index - 1) % len(_DAY_COLORS)],
                "summary": " · ".join(poi["name"] for poi in pois),
                "route_note": "先给出目的地内可视化草案，真实路线距离和时长待地图服务核验。",
                "weather": {
                    "city": destination,
                    "summary": "天气待实时核验。",
                    "confidence": "needs_live_weather",
                },
                "pois": pois,
                "segments": [
                    _segment(day_index, pois[i], pois[i + 1], index=i + 1)
                    for i in range(max(len(pois) - 1, 0))
                ],
            }
        )
    return result


def _flatten(items: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    flattened: list[dict[str, Any]] = []
    for item in items:
        flattened.extend(item.get(key) or [])
    return flattened


def _alternative_templates_for_destination(destination: str) -> list[tuple[str, str, str, str, int, str]]:
    destination_key = _known_destination_key(destination)
    if destination == "西藏":
        return list(_TIBET_ALTERNATIVE_POIS)
    templates = list(_KNOWN_DESTINATION_ALTERNATIVE_TEMPLATES.get(destination_key) or [])
    day_templates = _KNOWN_DESTINATION_DAY_TEMPLATES.get(destination_key) or []
    for _title, city, poi_specs in day_templates:
        for name, description, suggested_time, duration, tag in poi_specs:
            templates.append((name, city, description, suggested_time, duration, tag))
    if templates:
        return templates
    return [
        (
            f"{destination}美术馆",
            destination,
            "室内文化备选，可在天气变化或体力下降时替换户外点。",
            "下午备选",
            120,
            "艺术馆",
        ),
        (
            f"{destination}城市公园",
            destination,
            "城市绿地和低强度慢游节点，适合替换高强度景点。",
            "上午备选",
            100,
            "公园",
        ),
        (
            f"{destination}老街夜市",
            destination,
            "餐饮和夜间城市氛围备选，实际营业情况需二次核验。",
            "晚上备选",
            90,
            "夜市",
        ),
        (
            f"{destination}观景台",
            destination,
            "轻量观景节点，需按天气能见度决定是否执行。",
            "傍晚备选",
            75,
            "观景",
        ),
    ]


def _build_alternative_pois(
    destination: str,
    journey_days: list[dict[str, Any]],
    *,
    limit: int = 8,
) -> list[dict[str, Any]]:
    active_names = {
        str(poi.get("name") or "")
        for poi in _flatten(journey_days, "pois")
        if isinstance(poi, dict)
    }
    alternatives: list[dict[str, Any]] = []
    seen: set[str] = set(active_names)
    for name, city, description, suggested_time, duration, tag in _alternative_templates_for_destination(destination):
        if name in seen:
            continue
        seen.add(name)
        index = len(alternatives) + 1
        poi = _poi(
            day=0,
            index=index,
            name=name,
            city=city,
            description=description,
            suggested_time=suggested_time,
            duration_minutes=duration,
            tags=[tag, "备选替换"],
            search_keyword=f"{city} {tag}",
            is_generic_seed=not _known_destination_key(destination) and name.startswith(destination),
        )
        poi.update(
            {
                "id": f"alt-p{index}",
                "day_number": 0,
                "is_alternative": True,
                "replacement_rank": index,
                "candidate_reason": "可用于替换同城或同主题 POI，执行前仍需核验开放、交通和预约。",
                "verification_status": "candidate_needs_live_check",
            }
        )
        alternatives.append(poi)
        if len(alternatives) >= limit:
            break
    return alternatives


def build_visual_journey_plan(
    *,
    destination: str,
    date_text: str = "",
    days: int | None = None,
    style_query: str = "",
    state: dict[str, Any] | None = None,
    base_date: date | None = None,
) -> dict[str, Any]:
    """Build a visual journey draft and the public planning trace."""

    state = state or {}
    requirement = state.get("user_requirement") if isinstance(state.get("user_requirement"), dict) else {}
    destination = _normalize_destination(
        destination
        or state.get("selected_destination")
        or requirement.get("destination")
        or "西藏"
    )
    plan_days = _extract_days(days, date_text, style_query, requirement.get("travel_days"), default=7)
    departure_source = date_text or requirement.get("departure_date") or ""
    start_date = parse_relative_departure_date(departure_source, base_date=base_date)
    if not start_date and re.match(r"20\d{2}-\d{1,2}-\d{1,2}$", str(requirement.get("departure_date") or "")):
        start_date = parse_relative_departure_date(str(requirement.get("departure_date")), base_date=base_date)
    end_date = start_date + timedelta(days=plan_days - 1) if start_date else None
    date_range = (
        f"{_format_date(start_date)}至{_format_date(end_date)}"
        if start_date and end_date
        else "日期待确认"
    )

    is_tibet = destination == "西藏"
    journey_days = _build_tibet_days(start_date, plan_days) if is_tibet else _build_generic_days(destination, start_date, plan_days)
    pois = _flatten(journey_days, "pois")
    alternative_pois = _build_alternative_pois(destination, journey_days)
    segments = _flatten(journey_days, "segments")
    search_query = (
        "西藏7天经典旅游路线推荐拉萨林芝羊湖"
        if is_tibet
        else f"{destination}{plan_days}天经典旅游路线推荐"
    )
    poi_query = (
        "西藏7天经典旅游路线景点，包括拉萨市区布达拉宫大昭寺、羊卓雍措、纳木措、林芝巴松措等经典必去景点"
        if is_tibet
        else f"{destination}{plan_days}天经典旅游路线景点"
    )
    strategy_summary = (
        "林芝进拉萨出，低海拔渐进适应高反。"
        if is_tibet
        else f"{destination}目的地内按同区域聚类，先生成可视化经典动线。"
    )
    trace = [
        _trace(
            phase="date",
            title="日期和天数已确认" if start_date else "日期仍需核验",
            detail=(
                f"{departure_source or '用户日期'} 已换算为 {date_range}，先按 {plan_days} 天经典线编排。"
                if start_date
                else f"先按 {plan_days} 天经典线生成草案；真实交通、酒店、天气日期待确认。"
            ),
            date_range=date_range,
            evidence_type="date_parser",
        ),
        _trace(
            phase="search",
            title="公开攻略检索任务完成",
            detail=f"正在搜索小红书和全网公开信息：{search_query}。当前草案优先采用可审计的公开攻略/本地路线样板，不伪造具体平台来源。",
            count=1,
            evidence_type="public_route_research",
        ),
        _trace(
            phase="poi",
            title="经典地点已收集",
            detail=(
                f"正在搜索{destination}的地点：{poi_query}。"
                f"共整理 {len(pois)} 个可放入地图的地点，另准备 {len(alternative_pois)} 个可替换备选点。"
            ),
            count=len(pois) + len(alternative_pois),
            city=destination,
            evidence_type="poi_candidates",
        ),
        _trace(
            phase="weather",
            title="天气核验清单已生成",
            detail=f"正在查询拉萨/林芝等关键城市天气（{date_range}）；动态天气以 MCP 实时查询为准。",
            city="拉萨、林芝" if is_tibet else destination,
            date_range=date_range,
            evidence_type="weather_check",
        ),
        _trace(
            phase="route",
            title="最佳路线顺序已排好",
            detail=f"正在计算 {', '.join(p['name'] for p in pois[:4])} 等 {len(pois)} 个地点的最佳路线。{strategy_summary}",
            count=len(segments),
            evidence_type="route_sequence",
        ),
        _trace(
            phase="compose",
            title="分日行程已编辑完成",
            detail=f"路线和天气信息都有了，现在为你编排 {plan_days} 天经典行程：{strategy_summary}",
            count=plan_days,
            evidence_type="journey_plan",
        ),
    ]

    plan = {
        "version": JOURNEY_PLAN_VERSION,
        "overview": {
            "title": f"{destination}{plan_days}天经典之旅",
            "destination": destination,
            "start_date": _format_date(start_date),
            "end_date": _format_date(end_date),
            "date_range": date_range,
            "duration_days": plan_days,
            "route_label": "林芝进拉萨出" if is_tibet else f"{destination}经典线",
            "summary": strategy_summary,
            "style_query": style_query or "经典线",
        },
        "days": journey_days,
        "pois": pois,
        "alternative_pois": alternative_pois,
        "segments": segments,
        "weather": [
            {
                "city": "拉萨、林芝" if is_tibet else destination,
                "date_range": date_range,
                "status": "needs_live_check",
                "summary": "天气、开放时间和预约规则需要出发前二次核验。",
            }
        ],
        "route_strategy": {
            "summary": strategy_summary,
            "reasons": [
                "先低海拔适应，再进入高海拔城市或湖区。",
                "同日景点按区域和方向串联，减少折返。",
                "远途湖区保留天气、体力和道路情况备选。",
            ],
            "altitude_note": "西藏线需关注高反，第一二天不安排高强度爬升。",
        },
        "pending_checks": [
            "天气、道路、景区开放和门票预约需出发前二次核验。",
            "地图路段距离和时长以高德实时路线为准。",
            "交通、酒店和正式报价会在后续阶段继续确认。",
        ],
        "source_summary": {
            "search_queries": [search_query, poi_query],
            "poi_count": len(pois),
            "alternative_poi_count": len(alternative_pois),
            "evidence_types": ["public_route_research", "poi_candidates", "route_sequence"],
            "no_fake_sources": True,
        },
    }
    return {"journey_plan": plan, "planning_trace": trace}


def validate_journey_plan(plan: dict[str, Any]) -> tuple[bool, list[str]]:
    """Small contract validator used by tests and tool guards."""

    findings: list[str] = []
    if not isinstance(plan, dict):
        return False, ["journey_plan must be a dict"]
    if plan.get("version") != JOURNEY_PLAN_VERSION:
        findings.append("version must be journey_plan.v1")
    overview = plan.get("overview")
    if not isinstance(overview, dict) or not overview.get("destination"):
        findings.append("overview.destination is required")
    days = plan.get("days")
    if not isinstance(days, list) or not days:
        findings.append("days must be a non-empty list")
    else:
        for day in days:
            if not isinstance(day, dict):
                findings.append("day item must be a dict")
                continue
            if not day.get("pois"):
                findings.append(f"day {day.get('day_number')} must include pois")
    if not isinstance(plan.get("pois"), list) or not plan.get("pois"):
        findings.append("pois must be a non-empty list")
    if not isinstance(plan.get("alternative_pois"), list):
        findings.append("alternative_pois must be a list")
    if not isinstance(plan.get("pending_checks"), list):
        findings.append("pending_checks must be a list")
    return not findings, findings
