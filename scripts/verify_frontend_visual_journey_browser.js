const fs = require("fs");
const path = require("path");
const { pathToFileURL } = require("url");

const repoRoot = path.resolve(__dirname, "..");
const frontendHtmlPath = path.join(repoRoot, "frontend", "zhixing.html");
const frontendStylesText = [
  "styles.css",
  "chat.css",
]
  .map((name) => fs.readFileSync(path.join(repoRoot, "frontend", name), "utf8"))
  .join("\n");
const runtimeDir = path.join(repoRoot, ".runtime");
const runningInCi = ["1", "true"].includes(String(process.env.CI || "").toLowerCase());
const strictMissingBrowser =
  process.env.ZHIXING_FRONTEND_BROWSER_STRICT === "1" || runningInCi;

function finishMissingDependency(message, details = []) {
  const header = strictMissingBrowser
    ? "frontend-visual-journey-browser-dependency-missing"
    : "frontend-visual-journey-browser-skip";
  const text = [header, message, ...details].filter(Boolean).join("\n");
  if (strictMissingBrowser) {
    console.error(text);
    process.exit(1);
  }
  console.warn(text);
  process.exit(0);
}

function loadPlaywright() {
  try {
    return require("playwright");
  } catch (error) {
    finishMissingDependency("Playwright is not installed in this checkout.", [
      "Install local browser test dependencies with: npm install",
      "Then install Chromium if needed with: npx playwright install chromium",
      "CI and ZHIXING_FRONTEND_BROWSER_STRICT=1 treat this as a failed gate.",
    ]);
  }
}

const playwright = loadPlaywright();

const viewports = [
  { name: "desktop", width: 1440, height: 1000, isMobile: false },
  { name: "mobile", width: 390, height: 900, isMobile: true },
];

const readinessPayload = {
  status: "ready",
  environment: "visual-journey-browser-regression",
  startup_complete: true,
  missing_required: [],
  degraded_optional: [],
  services: {
    checkpointer: { status: "ready", ready: true },
    store: { status: "ready", ready: true },
    mcp: { status: "ready", ready: true },
  },
};

const tinyPng = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII=",
  "base64"
);

const hzPois = [
  {
    id: "hz-d1-p1",
    name: "西湖",
    city: "杭州",
    type: "attraction",
    type_label: "景点",
    suggested_time: "09:30-11:30",
    duration_minutes: 120,
    description: "先用湖区步行把城市节奏放慢，适合第一天快速建立方位感。",
    estimated_cost: "免费，游船待核验",
    reservation_note: "节假日游船排队时间需二次核验。",
    map_verified: true,
    verification_status: "amap_verified",
    verification_note: "高德地点已核验。",
    address: "杭州市西湖区龙井路1号",
    amap_type: "风景名胜",
    lng: 120.1489,
    lat: 30.2596,
  },
  {
    id: "hz-d1-p2",
    name: "断桥残雪",
    city: "杭州",
    type: "attraction",
    type_label: "景点",
    suggested_time: "11:40-12:20",
    duration_minutes: 40,
    description: "经典西湖视角，适合串联白堤与湖滨。",
    estimated_cost: "免费",
    map_verified: true,
    verification_status: "amap_verified",
    address: "杭州市西湖区北山街",
    amap_type: "风景名胜",
    lng: 120.1482,
    lat: 30.2631,
  },
  {
    id: "hz-d1-p3",
    name: "雷峰塔",
    city: "杭州",
    type: "attraction",
    type_label: "景点",
    suggested_time: "15:00-17:00",
    duration_minutes: 120,
    description: "下午登塔看湖面和城市天际线，门票与开放时间出发前核验。",
    estimated_cost: "门票参考价待核验",
    map_verified: true,
    verification_status: "amap_verified",
    address: "杭州市西湖区南山路15号",
    amap_type: "风景名胜",
    lng: 120.1485,
    lat: 30.2371,
  },
  {
    id: "hz-d2-p1",
    name: "灵隐寺",
    city: "杭州",
    type: "attraction",
    type_label: "景点",
    suggested_time: "08:30-11:30",
    duration_minutes: 180,
    description: "第二天放到西湖西侧，减少穿城折返，适合上午人流稍少时进入。",
    estimated_cost: "门票/香花券待核验",
    reservation_note: "节假日建议提前看预约与限流规则。",
    map_verified: true,
    verification_status: "amap_verified",
    verification_note: "高德地点已核验，开放规则待二次确认。",
    address: "杭州市西湖区法云弄1号",
    amap_type: "宗教场所",
    lng: 120.1013,
    lat: 30.2401,
  },
  {
    id: "hz-d2-p2",
    name: "飞来峰",
    city: "杭州",
    type: "attraction",
    type_label: "景点",
    suggested_time: "11:30-13:00",
    duration_minutes: 90,
    description: "和灵隐寺相邻，合并安排更省路。",
    estimated_cost: "门票待核验",
    map_verified: true,
    verification_status: "amap_verified",
    address: "杭州市西湖区灵隐路",
    amap_type: "风景名胜",
    lng: 120.1034,
    lat: 30.2418,
  },
  {
    id: "hz-d2-p3",
    name: "龙井村",
    city: "杭州",
    type: "neighborhood",
    type_label: "街区",
    suggested_time: "15:00-17:30",
    duration_minutes: 150,
    description: "下午顺路去茶村，作为从寺庙景区到轻松晚餐的缓冲。",
    estimated_cost: "餐饮/茶饮自理",
    coordinate_estimated: true,
    verification_status: "coordinate_estimated",
    verification_note: "暂按同区域落点展示，具体茶馆需后续核验。",
    address: "杭州市西湖区龙井村",
    amap_type: "村庄",
    lng: 120.1031,
    lat: 30.2198,
  },
  {
    id: "hz-d3-p1",
    name: "良渚古城遗址公园",
    city: "杭州",
    type: "attraction",
    type_label: "景点",
    suggested_time: "09:00-12:30",
    duration_minutes: 210,
    description: "第三天走城市北线，文化深度更强，适合和运河片区拆开西湖人流。",
    estimated_cost: "门票/预约待核验",
    map_verified: true,
    verification_status: "amap_verified",
    address: "杭州市余杭区瓶窑镇",
    amap_type: "遗址公园",
    lng: 119.9907,
    lat: 30.3927,
  },
  {
    id: "hz-d3-p2",
    name: "京杭大运河杭州段",
    city: "杭州",
    type: "attraction",
    type_label: "景点",
    suggested_time: "15:00-16:30",
    duration_minutes: 90,
    description: "从良渚回城后转入运河水系，节奏比继续跑景点更舒服。",
    estimated_cost: "游船待核验",
    coordinate_estimated: true,
    verification_status: "coordinate_estimated",
    verification_note: "运河为线性景区，当前用拱宸桥附近代表点展示。",
    address: "杭州市拱墅区拱宸桥",
    amap_type: "风景名胜",
    lng: 120.1428,
    lat: 30.3203,
  },
  {
    id: "hz-d3-p3",
    name: "小河直街",
    city: "杭州",
    type: "neighborhood",
    type_label: "街区",
    suggested_time: "17:00-19:30",
    duration_minutes: 150,
    description: "晚间以步行和餐饮收束，避免再跨区。",
    estimated_cost: "餐饮自理",
    map_verified: true,
    verification_status: "amap_verified",
    address: "杭州市拱墅区小河直街",
    amap_type: "特色街区",
    lng: 120.1415,
    lat: 30.3161,
  },
  {
    id: "hz-d4-p1",
    name: "浙江省博物馆",
    city: "杭州",
    type: "museum",
    type_label: "博物馆",
    suggested_time: "10:00-12:00",
    duration_minutes: 120,
    description: "最后一天安排室内内容，天气不好也能保底。",
    estimated_cost: "免费预约待核验",
    map_verified: true,
    verification_status: "amap_verified",
    address: "杭州市西湖区孤山路25号",
    amap_type: "博物馆",
    lng: 120.1451,
    lat: 30.2583,
  },
  {
    id: "hz-d4-p2",
    name: "湖滨步行街",
    city: "杭州",
    type: "shopping",
    type_label: "街区",
    suggested_time: "14:00-16:00",
    duration_minutes: 120,
    description: "返程前留给采购、咖啡和机动调整。",
    estimated_cost: "消费自理",
    map_verified: true,
    verification_status: "amap_verified",
    address: "杭州市上城区湖滨路",
    amap_type: "商业街",
    lng: 120.1632,
    lat: 30.2566,
  },
  {
    id: "hz-alt-p1",
    name: "九溪烟树",
    city: "杭州",
    type: "attraction",
    type_label: "景点",
    suggested_time: "机动替换",
    duration_minutes: 120,
    description: "同属西湖西侧，适合作为灵隐片区的轻户外备选点。",
    estimated_cost: "免费，交通待核验",
    reservation_note: "雨天和山路通行情况需出发前核验。",
    map_verified: true,
    verification_status: "amap_verified",
    verification_note: "高德地点已核验，作为可替换备选点。",
    address: "杭州市西湖区九溪十八涧",
    amap_type: "风景名胜",
    tags: ["备选点", "轻徒步"],
    lng: 120.1019,
    lat: 30.2024,
  },
  {
    id: "hz-alt-p2",
    name: "满觉陇",
    city: "杭州",
    type: "attraction",
    type_label: "景点",
    suggested_time: "机动替换",
    duration_minutes: 90,
    description: "西湖西南侧的桂花山谷和茶村街巷，适合作为轻量备选点。",
    estimated_cost: "免费，交通待核验",
    reservation_note: "季节花期和道路拥堵需出发前核验。",
    map_verified: true,
    verification_status: "amap_verified",
    verification_note: "高德地点已核验，适合作为西湖西南片区备选点。",
    address: "杭州市西湖区满觉陇路",
    amap_type: "风景名胜",
    tags: ["备选点", "茶村"],
    lng: 120.1058,
    lat: 30.2135,
  },
];

const dayDefinitions = [
  {
    day_number: 1,
    date: "2026-05-27",
    weekday: "周三",
    title: "西湖初见",
    summary: "湖区轻量进入，先建立杭州方位感。",
    city: "杭州",
    poiIds: ["hz-d1-p1", "hz-d1-p2", "hz-d1-p3"],
    segments: [
      {
        from: "西湖",
        to: "断桥残雪",
        distance_text: "1.1公里",
        duration_text: "步行18分钟",
        confidence: "amap_driving",
        source: "amap_driving",
        verification_note: "高德路线已核验。",
      },
      {
        from: "断桥残雪",
        to: "雷峰塔",
        distance_text: "4.8公里",
        duration_text: "约24分钟",
        confidence: "estimated_straight_line",
        source: "estimated",
        verification_note: "跨湖动线按估算展示，实时路线待核验。",
      },
    ],
  },
  {
    day_number: 2,
    date: "2026-05-28",
    weekday: "周四",
    title: "灵隐飞来峰与龙井",
    summary: "西湖西侧集中安排，减少跨城折返。",
    city: "杭州",
    poiIds: ["hz-d2-p1", "hz-d2-p2", "hz-d2-p3"],
    segments: [
      {
        from: "灵隐寺",
        to: "飞来峰",
        distance_text: "0.7公里",
        duration_text: "步行12分钟",
        confidence: "amap_driving",
        source: "amap_driving",
        verification_note: "高德路线已核验。",
      },
      {
        from: "飞来峰",
        to: "龙井村",
        distance_text: "5.6公里",
        duration_text: "约26分钟",
        confidence: "estimated_straight_line",
        source: "estimated",
        verification_note: "山区道路耗时需按当天路况核验。",
      },
    ],
  },
  {
    day_number: 3,
    date: "2026-05-29",
    weekday: "周五",
    title: "良渚与运河",
    summary: "北线文化日，上午遗址公园，下午运河街区。",
    city: "杭州",
    poiIds: ["hz-d3-p1", "hz-d3-p2", "hz-d3-p3"],
    segments: [
      {
        from: "良渚古城遗址公园",
        to: "京杭大运河杭州段",
        distance_text: "28.4公里",
        duration_text: "约55分钟",
        confidence: "estimated_straight_line",
        source: "estimated",
        verification_note: "跨区交通待高德实时路线二次核验。",
      },
      {
        from: "京杭大运河杭州段",
        to: "小河直街",
        distance_text: "0.8公里",
        duration_text: "步行13分钟",
        confidence: "amap_driving",
        source: "amap_driving",
        verification_note: "高德路线已核验。",
      },
    ],
  },
  {
    day_number: 4,
    date: "2026-05-30",
    weekday: "周六",
    title: "博物馆与湖滨收束",
    summary: "返程日前半天保留室内和采购机动。",
    city: "杭州",
    poiIds: ["hz-d4-p1", "hz-d4-p2"],
    segments: [
      {
        from: "浙江省博物馆",
        to: "湖滨步行街",
        distance_text: "3.2公里",
        duration_text: "约18分钟",
        confidence: "amap_driving",
        source: "amap_driving",
        verification_note: "高德路线已核验。",
      },
    ],
  },
];

function sampleJourneyData() {
  const poiById = new Map(hzPois.map((poi) => [poi.id, poi]));
  const activePoiIds = new Set(dayDefinitions.flatMap((day) => day.poiIds));
  const days = dayDefinitions.map((day) => ({
    ...day,
    pois: day.poiIds.map((poiId) => poiById.get(poiId)).filter(Boolean),
  }));
  return {
    version: "journey_plan.v1",
    overview: {
      title: "杭州4天经典慢游",
      destination: "杭州",
      date_range: "2026-05-27至2026-05-30",
      duration_days: 4,
      route_label: "杭州进杭州出",
      summary:
        "先用西湖建立方位，再转灵隐、良渚和运河，按区域聚类减少折返；交通、酒店和预算后续继续核验。",
    },
    days,
    pois: hzPois.filter((poi) => activePoiIds.has(poi.id)),
    alternative_pois: hzPois.filter((poi) => !activePoiIds.has(poi.id)),
    route_strategy: {
      title: "区域聚类 + 轻强度节奏",
      rationale: "同日尽量控制在一个片区，跨区安排放到白天，晚上保留低强度街区。",
    },
    weather: [
      { city: "杭州", date: "2026-05-27", summary: "多云，待出发前核验" },
      { city: "杭州", date: "2026-05-28", summary: "阵雨概率，待出发前核验" },
    ],
    pending_checks: [
      "门票、预约、开放时间和实时路线时长需出发前二次核验。",
      "酒店区域和真实房价将在下一阶段继续查询。",
    ],
    source_summary: {
      live_enrichment: true,
      public_strategy: "全网公开攻略命中杭州经典慢游、灵隐西湖西线和良渚运河北线。",
    },
  };
}

function samplePlanningTrace() {
  return [
    {
      phase: "parse",
      status: "completed",
      title: "已解析基础信息",
      detail: "目的地杭州，4天，经典慢游；先生成可视化旅程草案。",
    },
    {
      phase: "search",
      status: "completed",
      title: "公开攻略检索任务完成",
      detail: "正在搜索小红书和全网公开信息：杭州4天经典旅游路线 西湖 灵隐 良渚 运河。",
      count: 8,
      evidence_type: "public_strategy_search",
    },
    {
      phase: "poi",
      status: "completed",
      title: "地图地点已收集",
      detail: "正在搜索杭州的地点：西湖、灵隐寺、良渚古城遗址公园、京杭大运河杭州段等经典景点。",
      count: 11,
      city: "杭州",
      evidence_type: "map_poi",
    },
    {
      phase: "weather",
      status: "completed",
      title: "天气已核验",
      detail: "正在查询杭州天气（2026-05-27至2026-05-30）。",
      city: "杭州",
      date_range: "2026-05-27至2026-05-30",
      evidence_type: "weather",
    },
    {
      phase: "route",
      status: "completed",
      title: "路线顺序已排好",
      detail: "正在计算西湖、灵隐寺、良渚古城遗址公园等11个地点的最佳路线。",
      count: 11,
      evidence_type: "route",
    },
    {
      phase: "compose",
      status: "completed",
      title: "分日行程已编排",
      detail: "正在编辑第1天至第4天行程，先输出可视化路线，再继续交通、酒店、预算和报告。",
    },
  ];
}

function sampleMapPreview() {
  const pointFromPoi = (poi, kind = "highlight") => ({
    name: poi.name,
    label: poi.name,
    address: poi.address || poi.city || "",
    lat: poi.lat,
    lng: poi.lng,
    kind,
    verification_status: poi.verification_status,
    verification_note: poi.verification_note,
  });
  const poiById = new Map(hzPois.map((poi) => [poi.id, poi]));
  const days = dayDefinitions.map((day) => ({
    key: `visual-day-${day.day_number}`,
    label: `${day.date.slice(5)} ${day.weekday}`,
    points: day.poiIds.map((poiId) => pointFromPoi(poiById.get(poiId), "day")),
    segments: day.segments,
  }));
  return {
    provider: "leaflet-osm",
    points: [
      pointFromPoi(hzPois[0], "origin"),
      pointFromPoi(hzPois[hzPois.length - 1], "destination"),
      pointFromPoi(hzPois[1], "stay"),
      ...hzPois.map((poi) => pointFromPoi(poi, "highlight")),
    ],
    days,
  };
}

function enhancedLeafletStub() {
  return `
    (() => {
      if (window.L) return;
      const style = document.createElement("style");
      style.textContent = [
        ".playwright-leaflet-map{position:relative;overflow:hidden;background:#eef5f4;}",
        ".playwright-leaflet-map::before{content:'';position:absolute;inset:0;background:linear-gradient(135deg,#e7f4f2 0%,#f8fbfb 48%,#dcebea 100%);}",
        ".playwright-leaflet-map::after{content:'真实地图预览';position:absolute;right:18px;top:18px;padding:7px 10px;border-radius:999px;background:rgba(255,255,255,.86);color:#0f766e;font-size:12px;font-weight:800;box-shadow:0 8px 18px rgba(18,52,58,.12);}",
        ".playwright-map-pane{position:absolute;inset:0;z-index:2;}",
        ".playwright-map-river{position:absolute;left:8%;right:5%;top:53%;height:42px;border-radius:999px;background:rgba(88,189,203,.2);transform:rotate(-7deg);z-index:1;}",
        ".playwright-map-road{position:absolute;width:78%;height:3px;background:rgba(18,52,58,.18);border-radius:999px;transform:rotate(-13deg);left:12%;top:42%;z-index:1;}",
        ".playwright-map-overlay{position:absolute;transform:translate(-50%,-50%);z-index:6;}",
        ".playwright-map-polyline{position:absolute;height:5px;min-width:120px;border-radius:999px;transform-origin:left center;opacity:.85;z-index:3;box-shadow:0 7px 16px rgba(18,52,58,.13);}",
        ".playwright-circle-marker{position:absolute;width:18px;height:18px;border-radius:50%;background:rgba(20,184,166,.42);border:2px solid #14b8a6;box-shadow:0 8px 18px rgba(18,52,58,.16);z-index:5;}",
        ".playwright-map-popup{position:absolute;left:50%;top:16%;transform:translateX(-50%);z-index:20;padding:10px 12px;border-radius:12px;background:rgba(255,255,255,.96);box-shadow:0 16px 34px rgba(18,52,58,.16);color:#12343a;font-size:12px;line-height:1.45;}",
        ".playwright-map-popup strong{display:block;font-size:13px;margin-bottom:2px;}",
        ".leaflet-control-zoom{position:absolute;right:14px;top:58px;z-index:12;display:grid;gap:6px;}",
        ".leaflet-control-zoom a{display:grid;place-items:center;width:32px;height:32px;border-radius:10px;background:rgba(255,255,255,.92);box-shadow:0 8px 18px rgba(18,52,58,.12);text-decoration:none;font-weight:900;}",
        ".leaflet-journey-segment-label,.leaflet-journey-day-badge{z-index:11;}",
        ".journey-live-marker{z-index:10;}",
      ].join("");
      document.head.appendChild(style);

      const positions = [
        [24, 58], [33, 47], [45, 59], [57, 42], [68, 56], [78, 43],
        [31, 72], [43, 34], [60, 70], [74, 64], [84, 52], [52, 28],
      ];
      const clamp = (value, min, max) => Math.max(min, Math.min(max, value));

      function project(latlng, index) {
        const lat = Number(Array.isArray(latlng) ? latlng[0] : 30.26);
        const lng = Number(Array.isArray(latlng) ? latlng[1] : 120.15);
        if (Number.isFinite(lat) && Number.isFinite(lng)) {
          return {
            x: clamp(50 + (lng - 120.12) * 280 + (index % 3) * 2, 12, 88),
            y: clamp(54 - (lat - 30.26) * 220 + (index % 2) * 3, 14, 82),
          };
        }
        const [x, y] = positions[index % positions.length];
        return { x, y };
      }

      function makePopup(layer, html) {
        layer._popupHtml = html;
        return layer;
      }

      function makeLayer(element, options = {}) {
        return {
          _element: element,
          _latlng: options.latlng || null,
          _latlngs: options.latlngs || null,
          _popupHtml: "",
          _map: null,
          addTo(map) {
            this._map = map;
            map._layers.add(this);
            if (this._element) {
              if (!this._element.style.left) {
                const point = project(this._latlng || this._latlngs?.[0], map._overlayIndex++);
                this._element.style.left = point.x + "%";
                this._element.style.top = point.y + "%";
              }
              map._pane.appendChild(this._element);
            }
            return this;
          },
          bindPopup(html) {
            return makePopup(this, html);
          },
          bindTooltip(html) {
            this._tooltipHtml = html;
            if (this._element) {
              const container = document.createElement("div");
              container.innerHTML = String(html || "");
              this._element.title = container.textContent || String(html || "");
            }
            return this;
          },
          openPopup() {
            if (!this._map || !this._popupHtml) return this;
            this._map._popup.innerHTML = this._popupHtml;
            this._map._popup.hidden = false;
            return this;
          },
          on(eventName, handler) {
            this._element?.addEventListener?.(eventName, handler);
            return this;
          },
          setStyle(style = {}) {
            if (!this._element) return this;
            if (style.color) this._element.style.background = style.color;
            if (typeof style.opacity === "number") this._element.style.opacity = String(style.opacity);
            if (typeof style.weight === "number") this._element.style.height = style.weight + "px";
            return this;
          },
          setOpacity(opacity) {
            if (this._element) this._element.style.opacity = String(opacity);
            return this;
          },
        };
      }

      function buildMarker(latlng, options = {}) {
        const icon = options.icon || {};
        const element = document.createElement("div");
        element.className = ((icon.className || "journey-live-marker") + " playwright-map-overlay").trim();
        element.innerHTML = icon.html || "<span>●</span>";
        return makeLayer(element, { latlng });
      }

      function buildCircle(latlng, options = {}) {
        const element = document.createElement("div");
        element.className = "playwright-circle-marker";
        element.style.borderColor = options.color || "#14b8a6";
        element.style.background = options.fillColor || "rgba(20,184,166,.42)";
        return makeLayer(element, { latlng });
      }

      function buildPolyline(latlngs = [], options = {}) {
        const element = document.createElement("div");
        element.className = "playwright-map-polyline";
        element.style.background = options.color || "#14b8a6";
        element.style.height = (options.weight || 4) + "px";
        element.style.opacity = String(options.opacity ?? 0.9);
        const start = project(latlngs[0], 0);
        const end = project(latlngs[latlngs.length - 1], 1);
        const dx = end.x - start.x;
        const dy = end.y - start.y;
        element.style.left = start.x + "%";
        element.style.top = start.y + "%";
        element.style.width = Math.max(80, Math.hypot(dx, dy) * 8) + "px";
        element.style.transform = "rotate(" + Math.atan2(dy, dx) + "rad)";
        return makeLayer(element, { latlngs });
      }

      window.L = {
        map(node) {
          node.innerHTML = "";
          node.classList.add("leaflet-container", "playwright-leaflet-map");
          const river = document.createElement("div");
          river.className = "playwright-map-river";
          const road = document.createElement("div");
          road.className = "playwright-map-road";
          const pane = document.createElement("div");
          pane.className = "playwright-map-pane";
          const popup = document.createElement("div");
          popup.className = "playwright-map-popup";
          popup.hidden = true;
          const zoom = document.createElement("div");
          zoom.className = "leaflet-control-zoom";
          zoom.innerHTML = "<a>+</a><a>-</a>";
          node.append(river, road, pane, popup, zoom);
          return {
            _node: node,
            _pane: pane,
            _popup: popup,
            _layers: new Set(),
            _overlayIndex: 0,
            hasLayer(layer) { return this._layers.has(layer); },
            removeLayer(layer) {
              this._layers.delete(layer);
              layer?._element?.remove?.();
              return this;
            },
            fitBounds() { return this; },
            flyToBounds() { return this; },
            flyTo() { return this; },
            setView() { return this; },
            getZoom() { return 10; },
            invalidateSize() { return this; },
          };
        },
        tileLayer() {
          const element = document.createElement("div");
          element.className = "playwright-map-tile-layer";
          return makeLayer(element);
        },
        marker: buildMarker,
        circleMarker: buildCircle,
        polyline: buildPolyline,
        divIcon(options) { return options || {}; },
        latLngBounds(points) {
          return {
            points,
            isValid() { return Array.isArray(points) && points.length > 0; },
          };
        },
      };
    })();
  `;
}

function responseJson(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "content-type": "application/json; charset=utf-8" },
  });
}

async function installNetworkStubs(context) {
  await context.route("**/health/ready", async (route) => {
    await route.fulfill(responseJson(readinessPayload));
  });
  await context.route("**/api/v1/users/me", async (route) => {
    await route.fulfill(responseJson({
      id: "visual-journey-browser-user",
      username: "visual-journey-browser",
      email: "visual-journey-browser@example.test",
      preferences: { role: "user" },
    }));
  });
  await context.route("**/api/v1/maps/config", async (route) => {
    await route.fulfill(responseJson({
      preferred_provider: "leaflet-osm",
      amap_web_js_key: "",
      amap_web_js_key_configured: false,
      fallback_provider: "leaflet-osm",
    }));
  });
  await context.route("**/api/v1/chat/journey/**", async (route) => {
    await route.fulfill(responseJson({
      status: "saved",
      journey_data: sampleJourneyData(),
    }));
  });
  await context.route("https://cdn.bootcdn.net/**", async (route) => {
    const url = route.request().url();
    if (url.endsWith("/leaflet.js")) {
      await route.fulfill({
        status: 200,
        contentType: "application/javascript; charset=utf-8",
        body: enhancedLeafletStub(),
      });
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: "text/css; charset=utf-8",
      body: ".fa,.fa-solid,.fa-regular{display:inline-block}.fa::before{content:''}",
    });
  });
  await context.route("https://images.unsplash.com/**", async (route) => {
    await route.fulfill({ status: 200, contentType: "image/png", body: tinyPng });
  });
  await context.addInitScript((payload) => {
    const originalFetch = window.fetch.bind(window);
    const json = (body, status = 200) =>
      new Response(JSON.stringify(body), {
        status,
        headers: { "content-type": "application/json; charset=utf-8" },
      });

    window.__visualJourneySavedDrafts = [];

    window.fetch = async (input, init) => {
      const rawUrl = typeof input === "string" ? input : input?.url || "";
      const url = String(rawUrl);
      if (url.includes("/health/ready")) return json(payload.readiness);
      if (url.includes("/api/v1/users/me")) {
        return json({
          id: "visual-journey-browser-user",
          username: "visual-journey-browser",
          email: "visual-journey-browser@example.test",
          preferences: { role: "user" },
        });
      }
      if (url.includes("/api/v1/conversations")) {
        return json({
          conversations: [
            {
              id: "visual-journey-browser-trip",
              title: "可视化旅程回归",
              created_at: "2026-05-18T13:00:00Z",
              updated_at: "2026-05-18T13:30:00Z",
            },
          ],
        });
      }
      if (url.includes("/api/v1/approvals/visual-journey-approval/events")) {
        return json({
          events: [
            {
              event_type: "created",
              actor: "visual-journey-browser",
              created_at: 1778508000,
              detail: "用于可视化旅程回归的记录型人工确认事件。",
            },
          ],
        });
      }
      if (url.includes("/api/v1/approvals?")) {
        return json({
          approvals: [
            {
              approval_id: "visual-journey-approval",
              action: "generate_visual_journey",
              label: "生成可视化旅程",
              reason: "验证旅程工作台治理记录渲染。",
              status: "none",
              requires_approval: false,
              created_at: 1778508000,
              expires_at: null,
            },
          ],
        });
      }
      if (url.endsWith("/api/v1/approvals")) {
        return json({
          approval_id: "visual-journey-approval",
          status: "none",
        });
      }
      if (url.includes("/api/v1/maps/config")) {
        return json({
          preferred_provider: "leaflet-osm",
          amap_web_js_key: "",
          amap_web_js_key_configured: false,
          fallback_provider: "leaflet-osm",
        });
      }
      if (url.includes("/api/v1/maps/preview")) {
        try {
          const requestPayload = JSON.parse(init?.body || "{}");
          const requestDays = Array.isArray(requestPayload?.days)
            ? requestPayload.days
            : [];
          if (requestDays.length) {
            const pointFromStop = (stop, kind = "day") => ({
              name: stop?.name || stop?.value || "地点",
              label: stop?.name || stop?.value || "地点",
              address: stop?.address || stop?.city || "",
              lat: Number.isFinite(Number(stop?.lat)) ? Number(stop.lat) : 30.26,
              lng: Number.isFinite(Number(stop?.lng)) ? Number(stop.lng) : 120.15,
              kind,
              verification_status: stop?.verification_status || "",
              verification_note: stop?.verification_note || "",
            });
            const days = requestDays.map((day, index) => {
              const stops = Array.isArray(day?.stops) ? day.stops : [];
              return {
                key: day?.key || `day-${index + 1}`,
                label: day?.label || `Day ${index + 1}`,
                points: stops.map((stop) => pointFromStop(stop, "day")),
                segments: Array.isArray(day?.segments) ? day.segments : [],
              };
            });
            const dayPoints = days.flatMap((day) => day.points || []);
            const recommendationStops = Array.isArray(requestPayload?.recommendations)
              ? requestPayload.recommendations
              : [];
            const recommendationPoints = recommendationStops.map((stop) =>
              pointFromStop(stop, "recommendation")
            );
            return json({
              provider: "leaflet-osm",
              points: [
                ...(dayPoints[0] ? [{ ...dayPoints[0], kind: "origin" }] : []),
                ...(dayPoints.at(-1) ? [{ ...dayPoints.at(-1), kind: "destination" }] : []),
                ...dayPoints.map((point) => ({ ...point, kind: "highlight" })),
                ...recommendationPoints,
              ],
              days,
            });
          }
        } catch (error) {}
        return json(payload.preview);
      }
      if (url.includes("/api/v1/chat/journey/")) {
        let requestPayload = {};
        try {
          requestPayload = JSON.parse(init?.body || "{}");
        } catch (error) {}
        if (requestPayload?.journeyData) {
          window.__visualJourneySavedDrafts.push(requestPayload.journeyData);
        }
        return json({
          status: "saved",
          journey_data: requestPayload.journeyData || payload.journeyData,
        });
      }
      return originalFetch(input, init);
    };
  }, {
    readiness: readinessPayload,
    preview: sampleMapPreview(),
    journeyData: sampleJourneyData(),
  });
}

async function createPage(browser, viewport) {
  const context = await browser.newContext({
    viewport: { width: viewport.width, height: viewport.height },
    deviceScaleFactor: viewport.isMobile ? 2 : 1,
    isMobile: viewport.isMobile,
    hasTouch: viewport.isMobile,
    acceptDownloads: true,
    reducedMotion: "reduce",
    locale: "zh-CN",
  });
  await installNetworkStubs(context);
  const page = await context.newPage();
  const consoleErrors = [];
  const pageErrors = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  page.on("requestfailed", (request) => {
    consoleErrors.push(`${request.url()} ${request.failure()?.errorText || "request failed"}`);
  });
  page.on("pageerror", (error) => pageErrors.push(error.message));
  return { context, page, consoleErrors, pageErrors };
}

async function seedLoggedInState(page) {
  await page.addInitScript(() => {
    window.localStorage.removeItem("token");
    window.localStorage.removeItem("user");
    window.localStorage.setItem("visual-journey-browser-session", "1");
  });
}

async function gotoFrontend(page) {
  await page.goto(pathToFileURL(frontendHtmlPath).href, {
    waitUntil: "domcontentloaded",
  });
  await page.waitForSelector("#chatMessages", { state: "attached", timeout: 5000 });
  await page.evaluate(() => {
    let bypassStyle = document.getElementById("visualJourneyRegressionOverlayBypass");
    if (!bypassStyle) {
      bypassStyle = document.createElement("style");
      bypassStyle.id = "visualJourneyRegressionOverlayBypass";
      bypassStyle.textContent = [
        "#introOverlay, #authOverlay {",
        "  display: none !important;",
        "  pointer-events: none !important;",
        "}",
        "body.intro-active { overflow: auto !important; }",
      ].join("\n");
      document.head.appendChild(bypassStyle);
    }
    document.getElementById("introOverlay")?.classList.add("hidden");
    document.getElementById("authOverlay")?.classList.add("hidden");
    document.body.classList.remove("intro-active");
  });
}

async function expectVisible(page, selector, label) {
  const locator = page.locator(selector).first();
  await locator.waitFor({ state: "visible", timeout: 6000 });
  const box = await locator.boundingBox();
  if (!box || box.width < 4 || box.height < 4) {
    throw new Error(`${label} is visible but has an empty box.`);
  }
  return box;
}

async function expectContainsText(page, selector, fragments, label) {
  const locator = page.locator(selector).first();
  await locator.waitFor({ state: "visible", timeout: 6000 });
  const text = (await locator.textContent()) || "";
  const missing = fragments.filter((fragment) => !text.includes(fragment));
  if (missing.length) {
    throw new Error(`${label} missing text: ${missing.join(", ")}`);
  }
}

async function expectNotContainsText(page, selector, fragments, label) {
  const locator = page.locator(selector).first();
  await locator.waitFor({ state: "visible", timeout: 6000 });
  const text = (await locator.evaluate((node) => node.innerText || node.textContent || "")) || "";
  const leaked = fragments.filter((fragment) => text.includes(fragment));
  if (leaked.length) {
    throw new Error(`${label} leaked text: ${leaked.join(", ")}`);
  }
}

async function expectInputValueContains(page, selector, fragments, label) {
  const locator = page.locator(selector).first();
  await locator.waitFor({ state: "visible", timeout: 6000 });
  const text = (await locator.inputValue()) || "";
  const missing = fragments.filter((fragment) => !text.includes(fragment));
  if (missing.length) {
    throw new Error(`${label} missing input value: ${missing.join(", ")}`);
  }
}

async function expectVisibleRouteLabelCount(page, expected, label) {
  await page.waitForSelector(".leaflet-journey-segment-label", {
    state: "attached",
    timeout: 6000,
  });
  const count = await page.evaluate(() =>
    Array.from(document.querySelectorAll(".leaflet-journey-segment-label")).filter(
      (item) => Number.parseFloat(item.style.opacity || "1") > 0.5
    ).length
  );
  if (count !== expected) {
    throw new Error(`${label} expected ${expected} visible route labels, got ${count}`);
  }
}

async function injectVisualJourney(page) {
  await page.evaluate(
    ({ journeyData, planningTrace }) => {
      const container = document.getElementById("chatMessages");
      container.innerHTML = "";
      window.addMessage(
        "assistant",
        "杭州4天经典慢游已经整理成可视化旅程草案，先看地图和分日路线。",
        {
          journeyData,
          planningTrace,
        }
      );
    },
    {
      journeyData: sampleJourneyData(),
      planningTrace: samplePlanningTrace(),
    }
  );
  await page.waitForSelector(".visual-journey-workbench", {
    state: "visible",
    timeout: 6000,
  });
  await page.waitForSelector('.journey-live-map[data-map-ready="1"]', {
    state: "visible",
    timeout: 6000,
  });
}

async function checkVisualJourneySurface(page, viewport) {
  await expectVisible(page, ".visual-journey-workbench", `${viewport.name} journey workbench`);
  await expectVisible(
    page,
    ".journey-live-map-shell--immersive",
    `${viewport.name} immersive map shell`
  );
  await expectVisible(page, ".journey-live-map.leaflet-container", `${viewport.name} map`);
  await expectVisible(page, ".journey-map-title-pill", `${viewport.name} map title pill`);
  await expectVisible(page, ".journey-map-sidebar-open", `${viewport.name} route explanation toggle`);
  await page.locator(".journey-map-sidebar-open").first().click();
  await expectVisible(page, ".journey-map-sidebar-routes", `${viewport.name} route explanation`);
  await expectContainsText(
    page,
    '[data-map-action="toggle-day-routes"]',
    ["展开分日路线"],
    `${viewport.name} day route toggle collapsed`
  );
  await page.locator('[data-map-action="toggle-day-routes"]').first().click();
  await page.waitForFunction(
    () => !document.querySelector(".journey-map-sidebar-routes")?.classList.contains("is-collapsed"),
    null,
    { timeout: 5000 }
  );
  await expectVisible(page, ".leaflet-journey-day-marker", `${viewport.name} numbered day markers`);
  await expectVisible(page, ".leaflet-journey-day-badge", `${viewport.name} day badges`);
  await expectVisible(
    page,
    ".leaflet-journey-segment-label",
    `${viewport.name} segment labels`
  );
  await expectContainsText(
    page,
    ".leaflet-journey-segment-label",
    ["05.27", "1.1公里"],
    `${viewport.name} route segment date labels`
  );
  await expectVisibleRouteLabelCount(
    page,
    4,
    `${viewport.name} overview route label density`
  );
  await page.locator('[data-map-action="toggle-tools"]').first().click();
  await expectContainsText(
    page,
    '[data-map-action="recommendations"]',
    ["推荐点"],
    `${viewport.name} recommendation toggle`
  );
  await page.locator('[data-map-action="recommendations"]').click();
  await expectVisible(page, ".journey-live-marker.kind-recommendation", `${viewport.name} map recommendation marker`);
  await expectContainsText(
    page,
    '[data-map-action="recommendations"]',
    ["隐藏推荐点"],
    `${viewport.name} recommendation toggle active`
  );
  await page.locator(".journey-live-marker.kind-recommendation").first().dispatchEvent("click");
  await page.waitForSelector(".journey-poi-bottom-sheet.show", {
    state: "hidden",
    timeout: 3000,
  });
  await page.locator(".leaflet-journey-day-marker").first().dispatchEvent("click");
  await expectVisible(page, ".journey-map-sidebar-place-chip.active", `${viewport.name} active route stop`);
  await expectContainsText(
    page,
    ".journey-map-sidebar-place-chip.active",
    ["西湖"],
    `${viewport.name} map marker reverse route highlight`
  );
  await page.waitForSelector(".journey-poi-bottom-sheet.show", {
    state: "hidden",
    timeout: 3000,
  });
  await expectContainsText(
    page,
    "#chatMessages",
    ["杭州4天经典慢游", "西湖", "良渚"],
    `${viewport.name} visual journey copy`
  );
  await expectNotContainsText(
    page,
    "#chatMessages",
    ["规划过程", "正在搜索小红书和全网公开信息"],
    `${viewport.name} visual journey internal copy`
  );
  await expectContainsText(
    page,
    ".visual-journey-workbench",
    ["路线预览", "4 天路线", "分日路线", "路线参考", "交通、酒店和预算后续继续核验"],
    `${viewport.name} journey workbench text`
  );

  await page
    .locator(
      '.journey-map-sidebar-routes .journey-map-day-btn[data-map-day="visual-day-2"]'
    )
    .first()
    .click();
  await page.waitForFunction(
    () =>
      document.querySelector(".journey-live-map-shell")?.dataset.activeDay ===
      "visual-day-2",
    null,
    { timeout: 5000 }
  );
  await expectVisibleRouteLabelCount(
    page,
    2,
    `${viewport.name} selected day route label density`
  );
  await page
    .locator('button.journey-map-stage-stop[data-map-day-stop="visual-day-2:0"]')
    .first()
    .click();
  await page.waitForSelector(".journey-poi-bottom-sheet.show", {
    state: "hidden",
    timeout: 3000,
  });
  await expectContainsText(
    page,
    ".journey-map-sidebar-routes",
    ["灵隐寺", "路线参考"],
    `${viewport.name} day route stays readable without POI sheet`
  );

  await page.locator(".journey-map-sidebar-toggle").first().click();
  await page.waitForSelector(".journey-map-sidebar-collapsed", {
    state: "attached",
    timeout: 5000,
  });
  await page.locator(".journey-map-sidebar-open").first().click();
  await expectVisible(page, ".journey-map-sidebar-routes", `${viewport.name} route explanation reopened`);
}

async function getVisualRouteDayNames(page, dayKey) {
  return (
    await page
      .locator(
        `.visual-route-day-card[data-journey-day-card="${dayKey}"] .visual-route-stop-main strong`
      )
      .allTextContents()
  )
    .map((item) => item.trim())
    .filter(Boolean);
}

async function checkVisualJourneyEditing(page, viewport) {
  const screenshots = [];
  await expectVisible(page, ".visual-route-editor", `${viewport.name} route editor`);
  await expectContainsText(
    page,
    ".visual-route-editor",
    ["路线编辑", "分日地点顺序"],
    `${viewport.name} route editor labels`
  );
  await expectContainsText(
    page,
    ".visual-route-editor",
    ["1.1公里", "步行18分钟", "已核验"],
    `${viewport.name} route segment metrics`
  );

  const day1Before = await getVisualRouteDayNames(page, "visual-day-1");
  if (day1Before.length < 2) {
    throw new Error(`${viewport.name} route editor needs at least two stops in day 1.`);
  }
  const firstStop = day1Before[0];

  await page
    .locator(
      '.visual-route-day-card[data-journey-day-card="visual-day-1"] [data-journey-edit-action="down"][data-map-day-stop="visual-day-1:0"]'
    )
    .click();
  await page.waitForFunction(
    (expectedSecond) => {
      const names = Array.from(
        document.querySelectorAll(
          '.visual-route-day-card[data-journey-day-card="visual-day-1"] .visual-route-stop-main strong'
        )
      ).map((node) => node.textContent.trim());
      return names[1] === expectedSecond;
    },
    firstStop,
    { timeout: 5000 }
  );
  await page.waitForFunction(
    (expectedSecond) => {
      const raw = document.querySelector(".journey-live-map-shell")?.dataset.dayPlans || "";
      try {
        const days = JSON.parse(decodeURIComponent(raw));
        const day = days.find((item) => item.key === "visual-day-1");
        return day?.stops?.[1]?.name === expectedSecond;
      } catch (error) {
        return false;
      }
    },
    firstStop,
    { timeout: 5000 }
  );
  await expectContainsText(
    page,
    ".visual-route-editor",
    ["待高德路线核验"],
    `${viewport.name} edited route segment pending metrics`
  );

  const day1AfterDown = await getVisualRouteDayNames(page, "visual-day-1");
  const movingStop = day1AfterDown[0];
  await page
    .locator(
      '.visual-route-day-card[data-journey-day-card="visual-day-1"] .visual-route-stop-row[data-map-day-stop="visual-day-1:0"] .visual-route-more-actions summary'
    )
    .click();
  await expectVisible(
    page,
    '.visual-route-day-card[data-journey-day-card="visual-day-1"] .visual-route-stop-row[data-map-day-stop="visual-day-1:0"] .visual-route-more-menu [data-journey-edit-action="next-day"]',
    `${viewport.name} route editor more action menu`
  );
  await page
    .locator(
      '.visual-route-day-card[data-journey-day-card="visual-day-1"] [data-journey-edit-action="next-day"][data-map-day-stop="visual-day-1:0"]'
    )
    .click();
  await page.waitForFunction(
    (movedName) => {
      const day1Names = Array.from(
        document.querySelectorAll(
          '.visual-route-day-card[data-journey-day-card="visual-day-1"] .visual-route-stop-main strong'
        )
      ).map((node) => node.textContent.trim());
      const day2Names = Array.from(
        document.querySelectorAll(
          '.visual-route-day-card[data-journey-day-card="visual-day-2"] .visual-route-stop-main strong'
        )
      ).map((node) => node.textContent.trim());
      return !day1Names.includes(movedName) && day2Names.includes(movedName);
    },
    movingStop,
    { timeout: 5000 }
  );

  await expectVisible(page, ".visual-route-planning-pool", `${viewport.name} route planning pool`);
  await expectContainsText(
    page,
    ".visual-route-planning-pool",
    ["待规划地点", "九溪烟树", "满觉陇"],
    `${viewport.name} route planning pool candidates`
  );
  if (viewport.isMobile) {
    const poolPath = path.join(
      runtimeDir,
      "frontend-visual-journey-mobile-planning-pool.png"
    );
    await page.locator(".visual-route-planning-pool").first().screenshot({
      path: poolPath,
    });
    screenshots.push(poolPath);
  }
  await page
    .locator(
      '.visual-route-planning-card[data-pending-poi-id="hz-alt-p1"] [data-journey-edit-action="add-pending"][data-journey-day-key="visual-day-1"]'
    )
    .click();
  await page.waitForFunction(
    () => {
      const names = Array.from(
        document.querySelectorAll(
          '.visual-route-day-card[data-journey-day-card="visual-day-1"] .visual-route-stop-main strong'
        )
      ).map((node) => node.textContent.trim());
      return names.includes("九溪烟树");
    },
    null,
    { timeout: 5000 }
  );
  await page
    .locator(
      '.visual-route-planning-card[data-pending-poi-id="hz-alt-p2"] [data-journey-edit-action="add-pending"][data-journey-day-key="visual-day-1"]'
    )
    .click();
  await page.waitForFunction(
    () => {
      const names = Array.from(
        document.querySelectorAll(
          '.visual-route-day-card[data-journey-day-card="visual-day-1"] .visual-route-stop-main strong'
        )
      ).map((node) => node.textContent.trim());
      return names.includes("九溪烟树") && names.includes("满觉陇");
    },
    null,
    { timeout: 5000 }
  );
  await page.waitForFunction(
    () => !document.querySelector('.visual-route-planning-card[data-pending-poi-id="hz-alt-p1"]'),
    null,
    { timeout: 5000 }
  );

  const day1FirstAfterAdds = (await getVisualRouteDayNames(page, "visual-day-1"))[0];
  await page
    .locator(
      '.visual-route-day-card[data-journey-day-card="visual-day-1"] .visual-route-stop-row[data-map-day-stop="visual-day-1:0"] .visual-route-more-actions summary'
    )
    .click();
  await page
    .locator(
      '.visual-route-day-card[data-journey-day-card="visual-day-1"] .visual-route-stop-row[data-map-day-stop="visual-day-1:0"] [data-journey-edit-action="toggle-lock"]'
    )
    .click();
  await page.waitForFunction(
    (lockedName) => {
      const raw = document.querySelector(".journey-live-map-shell")?.dataset.dayPlans || "";
      try {
        const days = JSON.parse(decodeURIComponent(raw));
        const day = days.find((item) => item.key === "visual-day-1");
        return day?.stops?.[0]?.name === lockedName && day?.stops?.[0]?.locked === true;
      } catch (error) {
        return false;
      }
    },
    day1FirstAfterAdds,
    { timeout: 5000 }
  );
  await page
    .locator(
      '.visual-route-day-card[data-journey-day-card="visual-day-1"] [data-journey-edit-action="optimize-day"][data-journey-day-key="visual-day-1"]'
    )
    .click();
  await page.waitForFunction(
    (lockedName) => {
      const raw = document.querySelector(".journey-live-map-shell")?.dataset.dayPlans || "";
      try {
        const days = JSON.parse(decodeURIComponent(raw));
        const day = days.find((item) => item.key === "visual-day-1");
        const names = (day?.stops || []).map((stop) => stop.name);
        return (
          day?.stops?.[0]?.name === lockedName &&
          day?.stops?.[0]?.locked === true &&
          names.includes("九溪烟树") &&
          names.includes("满觉陇")
        );
      } catch (error) {
        return false;
      }
    },
    day1FirstAfterAdds,
    { timeout: 5000 }
  );

  const editorOverflow = await page.evaluate(() => {
    const editor = document.querySelector(".visual-route-editor");
    if (!editor) return true;
    return editor.scrollWidth > editor.clientWidth + 3;
  });
  if (editorOverflow) {
    throw new Error(`${viewport.name} route editor overflows horizontally.`);
  }
  if (viewport.isMobile) {
    const compactActionMetrics = await page.evaluate(() => {
      const row = document.querySelector(".visual-route-stop-row");
      const actions = row?.querySelector(".visual-route-stop-actions");
      const visibleControls = Array.from(
        actions?.querySelectorAll(
          ".visual-route-action-primary, .visual-route-more-actions summary"
        ) || []
      ).filter((node) => {
        const rect = node.getBoundingClientRect();
        return rect.width > 0 && rect.height > 0;
      });
      return {
        visibleCount: visibleControls.length,
        rowHeight: row?.getBoundingClientRect().height || 0,
      };
    });
    if (compactActionMetrics.visibleCount !== 3) {
      throw new Error(
        `${viewport.name} route editor should expose 3 compact controls, found ${compactActionMetrics.visibleCount}.`
      );
    }
    if (compactActionMetrics.rowHeight > 160) {
      throw new Error(
        `${viewport.name} route editor stop row is too tall: ${Math.round(compactActionMetrics.rowHeight)}px.`
      );
    }
  }
  return screenshots;
}

async function checkLayoutHealth(page, viewport) {
  const metrics = await page.evaluate(() => {
    const box = (selector) => {
      const element = document.querySelector(selector);
      if (!element) return null;
      const rect = element.getBoundingClientRect();
      return {
        width: rect.width,
        height: rect.height,
        left: rect.left,
        right: rect.right,
        top: rect.top,
        bottom: rect.bottom,
        scrollWidth: element.scrollWidth,
        textLength: (element.textContent || "").trim().length,
      };
    };
    return {
      viewportWidth: window.innerWidth,
      viewportHeight: window.innerHeight,
      workbench: box(".visual-journey-workbench"),
      map: box(".journey-live-map"),
      routeExplanation: box(".journey-map-sidebar"),
      floatingPanel: box(".journey-map-floating-panel"),
      poiSheet: box(".journey-poi-bottom-sheet.show"),
    };
  });

  if (!metrics.workbench || !metrics.map || !metrics.routeExplanation || !metrics.floatingPanel) {
    throw new Error(`${viewport.name} visual journey layout elements were not measured.`);
  }
  const minWorkbenchWidth = viewport.isMobile ? 340 : 620;
  if (metrics.workbench.width < minWorkbenchWidth) {
    throw new Error(
      `${viewport.name} workbench is too narrow: ${Math.round(metrics.workbench.width)}px.`
    );
  }
  const minMapHeight = viewport.isMobile ? 500 : 560;
  if (metrics.map.height < minMapHeight) {
    throw new Error(
      `${viewport.name} map is too short: ${Math.round(metrics.map.height)}px.`
    );
  }
  if (metrics.routeExplanation.height > metrics.map.height + 180) {
    throw new Error(`${viewport.name} route explanation is disproportionate to the map.`);
  }
  if (metrics.floatingPanel.width > metrics.map.width - 16) {
    throw new Error(`${viewport.name} floating map controls overflow horizontally.`);
  }
  if (metrics.workbench.scrollWidth > metrics.workbench.width + 3) {
    throw new Error(`${viewport.name} visual journey workbench has horizontal overflow.`);
  }
  if (metrics.poiSheet && metrics.poiSheet.bottom > metrics.map.bottom + 4) {
    throw new Error(`${viewport.name} POI sheet escapes the map stage.`);
  }
}

async function captureScreenshots(page, viewport) {
  const workbenchPath = path.join(
    runtimeDir,
    `frontend-visual-journey-${viewport.name}-workbench.png`
  );
  await page.locator(".visual-journey-workbench").first().screenshot({
    path: workbenchPath,
  });
  const editorPath = path.join(
    runtimeDir,
    `frontend-visual-journey-${viewport.name}-editor.png`
  );
  await page.locator(".visual-route-editor").first().screenshot({
    path: editorPath,
  });
  let editorMenuPath = "";
  if (viewport.isMobile) {
    await page
      .locator(".visual-route-editor .visual-route-more-actions summary")
      .first()
      .click();
    await expectVisible(
      page,
      ".visual-route-editor .visual-route-more-menu",
      `${viewport.name} route editor expanded menu screenshot`
    );
    editorMenuPath = path.join(
      runtimeDir,
      "frontend-visual-journey-mobile-editor-menu.png"
    );
    await page.locator(".visual-route-editor").first().screenshot({
      path: editorMenuPath,
    });
  }

  const shellHtml = await page.evaluate(() => {
    const shell = document.querySelector(".journey-live-map-shell--immersive");
    if (!shell) throw new Error("visual journey map shell missing for screenshot");
    return shell.outerHTML;
  });
  const evidencePage = await page.context().newPage();
  await evidencePage.setContent(
    `<!DOCTYPE html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <style>
      ${frontendStylesText}
      body {
        margin: 0;
        min-height: 100vh;
        padding: ${viewport.isMobile ? "0" : "22px"};
        background: #eef5f4;
      }
      .visual-journey-evidence {
        width: min(100%, ${viewport.isMobile ? "390px" : "920px"});
        margin: 0 auto;
      }
      .visual-journey-evidence .message {
        width: 100%;
        max-width: none;
      }
      .visual-journey-evidence .message-content {
        width: 100%;
        padding: 0;
        border: 0;
        background: transparent;
        box-shadow: none;
      }
      .visual-journey-evidence .message-content::before,
      .visual-journey-evidence .message-avatar {
        display: none;
      }
    </style>
  </head>
  <body>
    <main class="visual-journey-evidence">
      <section class="message assistant">
        <div class="message-content">
          <div class="message-text">
            <div class="visual-journey-workbench">${shellHtml}</div>
          </div>
        </div>
      </section>
    </main>
  </body>
</html>`,
    { waitUntil: "domcontentloaded" }
  );
  await expectVisible(
    evidencePage,
    ".journey-live-map-shell--immersive",
    `${viewport.name} evidence map`
  );

  const screenshots = [];
  const focusedPath = path.join(
    runtimeDir,
    `frontend-visual-journey-${viewport.name}.png`
  );
  await evidencePage.locator(".journey-live-map-shell--immersive").first().screenshot({
    path: focusedPath,
  });
  screenshots.push(workbenchPath, editorPath, focusedPath);
  if (editorMenuPath) screenshots.push(editorMenuPath);

  if (viewport.isMobile) {
    const mapPath = path.join(runtimeDir, "frontend-visual-journey-mobile-map.png");
    await evidencePage.locator(".journey-map-stage").first().screenshot({
      path: mapPath,
    });
    screenshots.push(mapPath);
  }
  await evidencePage.close();
  return screenshots;
}

function assertNoConsoleErrors(viewport, consoleErrors, pageErrors) {
  const filteredConsoleErrors = consoleErrors.filter(
    (message) => !/favicon|ERR_FILE_NOT_FOUND/i.test(message)
  );
  if (filteredConsoleErrors.length || pageErrors.length) {
    const details = [...filteredConsoleErrors, ...pageErrors].join("\n");
    throw new Error(`${viewport.name} console/page errors:\n${details}`);
  }
}

async function runViewport(browser, viewport) {
  const session = await createPage(browser, viewport);
  try {
    await seedLoggedInState(session.page);
    await gotoFrontend(session.page);
    await injectVisualJourney(session.page);
    await checkVisualJourneySurface(session.page, viewport);
    const editingScreenshots = await checkVisualJourneyEditing(session.page, viewport);
    await checkLayoutHealth(session.page, viewport);
    const screenshots = [
      ...editingScreenshots,
      ...(await captureScreenshots(session.page, viewport)),
    ];
    assertNoConsoleErrors(viewport, session.consoleErrors, session.pageErrors);
    return screenshots;
  } finally {
    await session.context.close();
  }
}

async function main() {
  fs.mkdirSync(runtimeDir, { recursive: true });
  let browser;
  try {
    browser = await playwright.chromium.launch({ headless: true });
  } catch (error) {
    const message = String(error?.message || error);
    if (
      message.includes("Executable doesn't exist") ||
      message.includes("Please run the following command")
    ) {
      finishMissingDependency("Chromium for Playwright is not installed.", [
        "Install it with: npx playwright install chromium",
        "CI and ZHIXING_FRONTEND_BROWSER_STRICT=1 treat this as a failed gate.",
      ]);
    }
    throw error;
  }

  const screenshots = [];
  try {
    for (const viewport of viewports) {
      screenshots.push(...(await runViewport(browser, viewport)));
    }
  } finally {
    await browser.close();
  }

  console.log("frontend-visual-journey-browser-ok");
  console.log(`viewports=${viewports.map((item) => `${item.width}x${item.height}`).join(",")}`);
  console.log(`screenshots=${screenshots.join(",")}`);
}

main().catch((error) => {
  console.error("frontend-visual-journey-browser-failed");
  console.error(error);
  process.exit(1);
});
