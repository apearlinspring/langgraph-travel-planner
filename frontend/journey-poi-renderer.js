(function (global) {
  function createJourneyPoiRenderer(options = {}) {
    const escapeHtml =
      typeof options.escapeHtml === "function"
        ? options.escapeHtml
        : (value = "") =>
            String(value || "")
              .replace(/&/g, "&amp;")
              .replace(/</g, "&lt;")
              .replace(/>/g, "&gt;")
              .replace(/"/g, "&quot;")
              .replace(/'/g, "&#039;");
    const getVisualPoiInitial =
      typeof options.getVisualPoiInitial === "function"
        ? options.getVisualPoiInitial
        : (name = "") => String(name || "").trim().slice(0, 1) || "点";
    const getVisualPoiVerificationBadge =
      typeof options.getVisualPoiVerificationBadge === "function"
        ? options.getVisualPoiVerificationBadge
        : () => ({ tone: "pending", label: "待核验" });

    function renderVisualPoiMedia(poi = {}, index = 0, compact = false) {
      const imageUrl = String(poi.image_url || "").trim();
      if (/^https?:\/\//i.test(imageUrl)) {
        return `
          <figure class="visual-poi-media${compact ? " compact" : ""}">
            <img src="${escapeHtml(imageUrl)}" alt="${escapeHtml(poi.name || "地点图片")}" loading="lazy">
          </figure>
        `;
      }
      const palette = [
        "lake",
        "temple",
        "mountain",
        "city",
        "forest",
        "street",
      ][index % 6];
      return `
        <figure class="visual-poi-media visual-poi-media--fallback ${palette}${
          compact ? " compact" : ""
        }">
          <span>${escapeHtml(getVisualPoiInitial(poi.name))}</span>
        </figure>
      `;
    }

    function renderVisualPoiDetails(pois = []) {
      if (!pois.length) return "";
      return `
        <div class="visual-poi-grid">
          ${pois
            .slice(0, 14)
            .map((poi, index) => {
              const verification = getVisualPoiVerificationBadge(poi);
              const evidenceItems = [
                verification.label,
                poi.address || poi.map_query,
                poi.amap_type,
              ].filter(Boolean);
              return `
                <details class="visual-poi-card" data-poi-id="${escapeHtml(poi.id || "")}"${
                index === 0 ? " open" : ""
              }>
                  <summary>
                    <span>${index + 1}</span>
                    <div>
                      <strong>${escapeHtml(poi.name || "地点待确认")}</strong>
                      <small>${escapeHtml(
                        [poi.city, poi.type_label || poi.type, poi.suggested_time]
                          .filter(Boolean)
                          .join(" · ")
                      )}</small>
                    </div>
                  </summary>
                  ${renderVisualPoiMedia(poi, index)}
                  <div class="visual-poi-evidence">
                    ${evidenceItems
                      .slice(0, 3)
                      .map(
                        (item, itemIndex) =>
                          `<span class="${itemIndex === 0 ? escapeHtml(verification.tone) : ""}">${escapeHtml(
                            item
                          )}</span>`
                      )
                      .join("")}
                  </div>
                  <p>${escapeHtml(poi.description || "地点介绍待补充。")}</p>
                  <div class="visual-poi-meta">
                    <span>停留 ${escapeHtml(String(poi.duration_minutes || "待核验"))} 分钟</span>
                    <span>${escapeHtml(poi.estimated_cost || "费用待核验")}</span>
                    ${
                      Array.isArray(poi.tags) && poi.tags.length
                        ? `<span>${escapeHtml(poi.tags.slice(0, 2).join(" · "))}</span>`
                        : ""
                    }
                  </div>
                  <div class="visual-poi-actions">
                    <button
                      class="visual-poi-focus-btn"
                      type="button"
                      data-map-day-stop="visual-day-${escapeHtml(
                        String(poi.day_number || 1)
                      )}:${escapeHtml(String(Math.max(Number(poi.order || 1) - 1, 0)))}"
                    >
                      地图定位
                    </button>
                    <button
                      type="button"
                      data-journey-edit-action="up"
                      data-map-day-stop="visual-day-${escapeHtml(
                        String(poi.day_number || 1)
                      )}:${escapeHtml(String(Math.max(Number(poi.order || 1) - 1, 0)))}"
                    >
                      上移
                    </button>
                    <button
                      type="button"
                      data-journey-edit-action="down"
                      data-map-day-stop="visual-day-${escapeHtml(
                        String(poi.day_number || 1)
                      )}:${escapeHtml(String(Math.max(Number(poi.order || 1) - 1, 0)))}"
                    >
                      下移
                    </button>
                    <button
                      type="button"
                      data-journey-edit-action="delete"
                      data-map-day-stop="visual-day-${escapeHtml(
                        String(poi.day_number || 1)
                      )}:${escapeHtml(String(Math.max(Number(poi.order || 1) - 1, 0)))}"
                    >
                      删除
                    </button>
                    <button type="button" disabled>打卡</button>
                  </div>
                  <em>${escapeHtml(
                    poi.reservation_note || "开放、预约和票价出发前二次核验。"
                  )}</em>
                </details>
              `;
            })
            .join("")}
        </div>
      `;
    }

    return {
      renderVisualPoiMedia,
      renderVisualPoiDetails,
    };
  }

  global.ZhiXingJourneyPoiRenderer = {
    createJourneyPoiRenderer,
  };
})(window);
