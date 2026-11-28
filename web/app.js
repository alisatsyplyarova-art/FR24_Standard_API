"use strict";

// Адрес API FR24. Веб-интерфейс работает на порту 8080,
// API-сервер — на порту 8765.
const API_HOST = window.location.hostname || "127.0.0.1";
const RADAR_AREA = Object.freeze({ latitude: 40.4675, longitude: 50.0467, radiusKm: 100, radiusNm: 100 / 1.852 });
const DEFAULT_RADAR_SETTINGS = { latitude: 55.0126, longitude: 82.6507, radiusKm: 100, city: "Новосибирск", airport: "UNNT" }; let radarSettings = (() => { try { return { ...DEFAULT_RADAR_SETTINGS, ...JSON.parse(localStorage.getItem("fr24RadarSettings") || "{}") }; } catch { return { ...DEFAULT_RADAR_SETTINGS }; } })(); function currentApiUrl() { const radiusNm = Number(radarSettings.radiusKm) / 1.852; return `http://${API_HOST}:8765/v2/lat/${radarSettings.latitude}/lon/${radarSettings.longitude}/dist/${radiusNm.toFixed(5)}`; }
const REFRESH_INTERVAL = 5000;

const statusDot = document.getElementById("statusDot");
const statusText = document.getElementById("statusText");
const updateTime = document.getElementById("updateTime");

const aircraftCount = document.getElementById("aircraftCount");
const tableCount = document.getElementById("tableCount");
const radarRadius = document.getElementById("radarRadius");
const radarCenter = document.getElementById("radarCenter");
const aircraftTable = document.getElementById("aircraftTable");
const mapElement = document.getElementById("map");

let map = null;
let radarCircle = null;
let radarCenterMarker = null;
let latestAreaSignature = null;
let latestAircraft = [];
let selectedAircraftId = null;
let followRequests = false;
let showSearchZone = true;

const aircraftMarkers = new Map();
const aircraftById = new Map();

const FIELD_LABELS = {
    fr24_id: "FR24 ID",
    id: "ID",
    hex: "ICAO HEX",
    icao: "ICAO",
    callsign: "Позывной",
    registration: "Регистрация",
    reg: "Регистрация",
    aircraft_code: "Тип самолёта",
    type: "Тип",
    model: "Модель",
    airline: "Авиакомпания",
    airline_name: "Авиакомпания",
    origin: "Аэропорт вылета",
    origin_airport: "Аэропорт вылета",
    destination: "Аэропорт назначения",
    destination_airport: "Аэропорт назначения",
    lat: "Широта",
    latitude: "Широта",
    lon: "Долгота",
    lng: "Долгота",
    longitude: "Долгота",
    altitude: "Высота",
    altitude_ft: "Высота, ft",
    speed: "Скорость",
    speed_kt: "Скорость, kt",
    heading: "Курс",
    track: "Путевой угол",
    vertical_speed: "Вертикальная скорость",
    squawk: "Код Squawk",
    on_ground: "На земле",
    distance: "Расстояние",
    distance_nm: "Расстояние, NM",
    seen: "Возраст данных",
    seen_pos: "Возраст позиции",
    timestamp: "Время данных",
    source: "Источник"
};

function number(value, digits = 0) {
    if (value === null || value === undefined || value === "") {
        return "—";
    }

    const n = Number(value);

    if (!Number.isFinite(n)) {
        return String(value);
    }

    return n.toLocaleString("ru-RU", {
        minimumFractionDigits: digits,
        maximumFractionDigits: digits
    });
}

function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, char => ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#039;"
    })[char]);
}

function displayValue(value) {
    if (value === null || value === undefined || value === "") {
        return "—";
    }

    if (typeof value === "boolean") {
        return value ? "Да" : "Нет";
    }

    if (typeof value === "object") {
        try {
            return JSON.stringify(value, null, 2);
        } catch (_) {
            return String(value);
        }
    }

    return String(value);
}

function fieldLabel(key) {
    return FIELD_LABELS[key] || key.replace(/_/g, " ");
}

function formatTime(value) {
    if (value === null || value === undefined || value === "") {
        return "—";
    }

    const seconds = Number(value);

    if (!Number.isFinite(seconds) || seconds < 0) {
        return displayValue(value);
    }

    if (seconds < 60) {
        return `${Math.round(seconds)} сек. назад`;
    }

    if (seconds < 3600) {
        return `${Math.floor(seconds / 60)} мин. назад`;
    }

    return `${Math.floor(seconds / 3600)} ч. назад`;
}

function setStatus(online, message) {
    statusDot.className = "status-dot " + (online ? "online" : "offline");
    statusText.textContent = message;
}

function injectInterfaceStyles() {
    const style = document.createElement("style");

    style.textContent = `
      .radar-controls {
        display: flex;
        gap: 18px;
        align-items: center;
        flex-wrap: wrap;
        margin-left: auto;
      }

      .radar-controls label {
        display: flex;
        gap: 7px;
        align-items: center;
        color: #c8d8e8;
        font-size: 13px;
        cursor: pointer;
      }

      .radar-controls input {
        accent-color: #00baff;
        width: 16px;
        height: 16px;
      }

      #aircraftTable tr {
        cursor: pointer;
      }

      #aircraftTable tr.selected-aircraft {
        background: rgba(0, 186, 255, .18);
        outline: 1px solid #00baff;
      }

      .aircraft-details {
        margin-top: 16px;
        padding: 16px;
        background: rgba(8, 20, 34, .82);
        border: 1px solid rgba(0, 186, 255, .28);
        border-radius: 10px;
      }

      .aircraft-details h3 {
        margin: 0 0 12px;
        color: #eaf7ff;
        font-size: 16px;
      }

      .aircraft-details-grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
        gap: 8px;
      }

      .aircraft-field {
        padding: 9px 10px;
        background: rgba(255, 255, 255, .035);
        border-radius: 6px;
        min-width: 0;
      }

      .aircraft-field-name {
        display: block;
        color: #8faabd;
        font-size: 11px;
        text-transform: uppercase;
        margin-bottom: 5px;
      }

      .aircraft-field-value {
        display: block;
        color: #e8f5ff;
        font-size: 13px;
        overflow-wrap: anywhere;
        white-space: pre-wrap;
      }

      .aircraft-details-empty {
        color: #9bb1c2;
        font-size: 13px;
      }

      .aircraft-icon-wrapper {
        background: transparent;
        border: 0;
      }

      @media (max-width: 700px) {
        .radar-controls {
          width: 100%;
          margin: 10px 0 0;
        }
      }
    `;

    document.head.appendChild(style);
}

function addRadarControls() {
    const heading = document.querySelector(".map-panel .panel-heading");

    if (!heading) {
        return;
    }

    const controls = document.createElement("div");
    controls.className = "radar-controls";

    controls.innerHTML = `
      <label>
        <input id="followRequests" type="checkbox">
        Следовать за запросами
      </label>

      <label>
        <input id="showSearchZone" type="checkbox" checked>
        Показывать зону поиска
      </label>
    `;

    heading.appendChild(controls);

    controls.querySelector("#followRequests").addEventListener("change", event => {
        followRequests = event.target.checked;

        if (followRequests && radarCircle) {
            fitRadarArea();
        }
    });

    controls.querySelector("#showSearchZone").addEventListener("change", event => {
        showSearchZone = event.target.checked;
        setRadarZoneVisibility();
    });
}

function addDetailsPanel() {
    const tablePanel = document.querySelector(".table-panel");

    if (!tablePanel) {
        return;
    }

    const panel = document.createElement("section");
    panel.id = "aircraftDetails";
    panel.className = "aircraft-details";

    panel.innerHTML = `
      <h3>Данные выбранного самолёта</h3>
      <div class="aircraft-details-empty">
        Выберите самолёт на карте или в таблице.
      </div>
    `;

    tablePanel.appendChild(panel);
}

function initializeMap() {
    map = L.map(mapElement, {
        zoomControl: true
    }).setView([radarSettings.latitude, radarSettings.longitude], 7);

    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
        maxZoom: 19,
        attribution: '&copy; <a href="https://www.openstreetmap.org/">OpenStreetMap</a>'
    }).addTo(map);
}

function createAircraftIcon(heading) {
    const angle = Number.isFinite(Number(heading))
        ? Number(heading)
        : 0;

    return L.divIcon({
        className: "aircraft-icon-wrapper",
        html: `
          <div style="
            transform: rotate(${angle}deg);
            color: #55d6ff;
            font-size: 24px;
            line-height: 24px;
            text-shadow: 0 0 8px #00aaff;
          ">▲</div>
        `,
        iconSize: [28, 28],
        iconAnchor: [14, 14]
    });
}

function getArea(area) {
    if (!area) {
        return null;
    }

    const latitude = Number(area.latitude ?? area.lat);
    const longitude = Number(area.longitude ?? area.lon ?? area.lng);
    const radiusKm = Number(area.radius_km);

    if (
        !Number.isFinite(latitude) ||
        !Number.isFinite(longitude) ||
        !Number.isFinite(radiusKm) ||
        radiusKm <= 0
    ) {
        return null;
    }

    return {
        latitude,
        longitude,
        radiusKm,
        radiusNm: Number(area.radius_nm)
    };
}

function areaSignature(area) {
    return [
        area.latitude.toFixed(5),
        area.longitude.toFixed(5),
        area.radiusKm.toFixed(3)
    ].join(":");
}

function fitRadarArea() {
    if (!map || !radarCircle) {
        return;
    }

    map.fitBounds(radarCircle.getBounds(), {
        padding: [28, 28],
        maxZoom: 11,
        animate: true
    });
}

function setRadarZoneVisibility() {
    if (!map) {
        return;
    }

    [radarCircle, radarCenterMarker].forEach(layer => {
        if (!layer) {
            return;
        }

        if (showSearchZone && !map.hasLayer(layer)) {
            layer.addTo(map);
        }

        if (!showSearchZone && map.hasLayer(layer)) {
            map.removeLayer(layer);
        }
    });
}

function updateRadarArea(rawArea) {
    const area = getArea(rawArea);

    if (!area) {
        return;
    }

    const center = [area.latitude, area.longitude];
    const signature = areaSignature(area);
    const isNewArea = signature !== latestAreaSignature;

    latestAreaSignature = signature;

    if (!radarCircle) {
        radarCircle = L.circle(center, {
            radius: area.radiusKm * 1000,
            color: "#00baff",
            weight: 2,
            fillColor: "#008cff",
            fillOpacity: 0.06
        });

        radarCenterMarker = L.circleMarker(center, {
            radius: 5,
            color: "#ffffff",
            weight: 2,
            fillColor: "#00baff",
            fillOpacity: 1
        });
    } else {
        radarCircle.setLatLng(center);
        radarCircle.setRadius(area.radiusKm * 1000);
        radarCenterMarker.setLatLng(center);
    }

    setRadarZoneVisibility();

    if (followRequests && isNewArea) {
        fitRadarArea();
    }

    radarRadius.innerHTML = `
      ${number(
        Number.isFinite(area.radiusNm)
          ? area.radiusNm
          : area.radiusKm / 1.852,
        1
      )}
      <small>NM</small>
    `;

    radarCenter.textContent =
        `${number(area.latitude, 4)}, ${number(area.longitude, 4)}`;
}
function createAircraftPopup(plane) {
    const callsign = plane.callsign || "Без позывного";

    return `
      <div class="aircraft-popup">
        <strong>${escapeHtml(callsign)}</strong><br>
        ICAO HEX: ${escapeHtml(plane.hex || "—")}<br>
        Высота: ${escapeHtml(number(plane.altitude_ft ?? plane.altitude))} ft<br>
        Скорость: ${escapeHtml(number(plane.speed_kt ?? plane.speed))} kt<br>
        Курс: ${escapeHtml(number(plane.heading ?? plane.track))}°<br>
        Расстояние: ${escapeHtml(number(plane.distance_nm, 1))} NM
      </div>
    `;
}

function aircraftId(plane) {
    return plane.fr24_id ||
        plane.id ||
        plane.hex ||
        plane.icao ||
        null;
}

function renderAircraftDetails(plane) {
    const panel = document.getElementById("aircraftDetails");

    if (!panel) {
        return;
    }

    if (!plane) {
        panel.innerHTML = `
          <h3>Данные выбранного самолёта</h3>
          <div class="aircraft-details-empty">
            Выберите самолёт на карте или в таблице.
          </div>
        `;
        return;
    }

    const entries = Object.entries(plane);

    const title =
        plane.callsign ||
        plane.registration ||
        plane.hex ||
        aircraftId(plane) ||
        "Самолёт";

    panel.innerHTML = `
      <h3>Выбран самолёт: ${escapeHtml(title)}</h3>

      <div class="aircraft-details-grid">
        ${entries.map(([key, value]) => `
          <div class="aircraft-field">
            <span class="aircraft-field-name">
              ${escapeHtml(fieldLabel(key))}
            </span>

            <span class="aircraft-field-value">${escapeHtml(
                displayValue(value)
            )}</span>
          </div>
        `).join("")}
      </div>
    `;
}

function selectAircraft(id, source) {
    const plane = aircraftById.get(id);

    if (!plane) {
        return;
    }

    selectedAircraftId = id;

    // Подсветка выбранного самолёта в таблице.
    document.querySelectorAll(
        "#aircraftTable tr[data-aircraft-id]"
    ).forEach(row => {
        row.classList.toggle(
            "selected-aircraft",
            row.dataset.aircraftId === String(id)
        );
    });

    // Полная карточка данных самолёта.
    renderAircraftDetails(plane);

    const marker = aircraftMarkers.get(id);

    if (marker) {
        // Если самолёт выбран в таблице — перемещаем карту к нему.
        if (source === "table") {
            map.setView(
                marker.getLatLng(),
                Math.max(map.getZoom(), 8),
                { animate: true }
            );
        }

        marker.openPopup();
    }

    // Если выбран маркер на карте — прокручиваем таблицу к самолёту.
    if (source === "map") {
        const row = [...document.querySelectorAll(
            "#aircraftTable tr[data-aircraft-id]"
        )].find(item => item.dataset.aircraftId === String(id));

        if (row) {
            row.scrollIntoView({
                behavior: "smooth",
                block: "center"
            });
        }
    }
}

function updateAircraft(aircraft) {
    const currentIds = new Set();

    aircraftById.clear();

    for (const plane of aircraft) {
        const id = aircraftId(plane);

        if (!id) {
            continue;
        }

        const latitude = Number(plane.lat ?? plane.latitude);
        const longitude = Number(
            plane.lon ?? plane.lng ?? plane.longitude
        );

        if (
            !Number.isFinite(latitude) ||
            !Number.isFinite(longitude)
        ) {
            continue;
        }

        currentIds.add(id);
        aircraftById.set(id, plane);

        const position = [latitude, longitude];

        const icon = createAircraftIcon(
            plane.heading ?? plane.track
        );

        const popup = createAircraftPopup(plane);

        if (aircraftMarkers.has(id)) {
            const marker = aircraftMarkers.get(id);

            marker.setLatLng(position);
            marker.setIcon(icon);
            marker.setPopupContent(popup);
        } else {
            const marker = L.marker(position, { icon }).addTo(map);

            marker.bindPopup(popup);

            marker.on("click", () => {
                selectAircraft(id, "map");
            });

            aircraftMarkers.set(id, marker);
        }
    }

    // Удаляем маркеры самолётов, исчезнувших из ответа API.
    for (const [id, marker] of aircraftMarkers) {
        if (!currentIds.has(id)) {
            map.removeLayer(marker);
            aircraftMarkers.delete(id);
        }
    }

    // Обновляем карточку выбранного самолёта после обновления API.
    if (selectedAircraftId && aircraftById.has(selectedAircraftId)) {
        renderAircraftDetails(
            aircraftById.get(selectedAircraftId)
        );
    } else if (selectedAircraftId) {
        selectedAircraftId = null;
        renderAircraftDetails(null);
    }
}

function updateAircraftTable(aircraft) {
    aircraftTable.innerHTML = "";

    const rows = [...aircraft].sort((a, b) =>
        Number(a.distance_nm ?? Infinity) -
        Number(b.distance_nm ?? Infinity)
    );

    for (const plane of rows) {
        const id = aircraftId(plane);

        if (!id) {
            continue;
        }

        const row = document.createElement("tr");

        row.dataset.aircraftId = String(id);

        row.innerHTML = `
          <td>
            <strong>${escapeHtml(plane.callsign || "—")}</strong>
          </td>

          <td>
            ${escapeHtml(plane.hex || plane.icao || "—")}
          </td>

          <td>
            ${escapeHtml(number(
                plane.altitude_ft ?? plane.altitude
            ))}
          </td>

          <td>
            ${escapeHtml(number(
                plane.speed_kt ?? plane.speed
            ))}
          </td>

          <td>
            ${escapeHtml(number(
                plane.heading ?? plane.track
            ))}
          </td>

          <td>
            ${escapeHtml(number(plane.distance_nm, 1))}
          </td>

          <td>
            ${escapeHtml(formatTime(
                plane.seen_pos ?? plane.seen
            ))}
          </td>
        `;

        row.addEventListener("click", () => {
            selectAircraft(id, "table");
        });

        row.classList.toggle(
            "selected-aircraft",
            id === selectedAircraftId
        );

        aircraftTable.appendChild(row);
    }

    if (rows.length === 0) {
        aircraftTable.innerHTML = `
          <tr>
            <td colspan="7" class="empty">
              Нет самолётов в зоне радара
            </td>
          </tr>
        `;
    }

    aircraftCount.textContent = rows.length;
    tableCount.textContent = `${rows.length} БОРТОВ`;
}
function distanceNm(lat1,lon1,lat2,lon2){const rad=v=>v*Math.PI/180;const p1=rad(lat1),p2=rad(lat2);const dp=rad(lat2-lat1),dl=rad(lon2-lon1);const a=Math.sin(dp/2)**2+Math.cos(p1)*Math.cos(p2)*Math.sin(dl/2)**2;return 2*3440.065*Math.asin(Math.min(1,Math.sqrt(a)));}
function updateDashboard(data){const activeArea=data.active_area||{latitude:radarSettings.latitude,longitude:radarSettings.longitude,radius_km:radarSettings.radiusKm,radius_nm:radarSettings.radiusKm/1.852};const sourceAircraft=Array.isArray(data.aircraft)?data.aircraft:(Array.isArray(data.ac)?data.ac:[]);const aircraft=sourceAircraft.map(plane=>{const lat=Number(plane.lat??plane.latitude);const lon=Number(plane.lon??plane.longitude??plane.lng);const distance=plane.distance_nm!==null&&plane.distance_nm!==undefined&&Number.isFinite(Number(plane.distance_nm))?Number(plane.distance_nm):distanceNm(radarSettings.latitude,radarSettings.longitude,lat,lon);return {...plane,callsign:plane.callsign||plane.flight||"",distance_nm:distance};});latestAircraft=aircraft;updateRadarArea(activeArea);updateAircraft(aircraft);updateAircraftTable(aircraft);updateTime.textContent=new Date().toLocaleTimeString("ru-RU");setStatus(true,"ПОДКЛЮЧЕНО");}

async function loadRadarData() {
    try {
        const response = await fetch(currentApiUrl(), {
            cache: "no-store"
        });

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }

        const data = await response.json();

        updateDashboard(data);

    } catch (error) {
        console.error(
            "Ошибка получения данных FR24:",
            error
        );

        setStatus(false, "НЕТ СВЯЗИ");
    }
}

async function addAirportSelector(){
const h=document.querySelector(".map-panel .panel-heading");if(!h||document.querySelector("#airportSelectorPanel"))return;
const p=document.createElement("section");p.id="airportSelectorPanel";p.style.cssText="display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:10px;padding:12px;margin:0 0 12px;background:#0b1b2b;border:1px solid #31516b;border-radius:8px";
p.innerHTML='<label>Город<select id="apCity"></select></label><label>Аэропорт<select id="apAirport"></select></label><label>Широта<input id="apLat" type="number" step="any"></label><label>Долгота<input id="apLon" type="number" step="any"></label><label>Радиус, км<input id="apRadius" type="number" min="1" max="926"></label><button id="apApply" type="button">Применить зону</button><small id="apStatus" style="grid-column:1/-1">Загрузка airports.csv…</small>';
h.insertAdjacentElement("afterend",p);p.querySelectorAll("label").forEach(x=>{x.style.cssText="color:#c8d8e8;font-size:12px";x.querySelectorAll("select,input").forEach(y=>y.style.cssText="display:block;box-sizing:border-box;width:100%;margin-top:5px;padding:7px;background:#102438;color:#e8f5ff;border:1px solid #31516b;border-radius:4px")});
const $=id=>p.querySelector("#"+id),status=$("apStatus");
function csv(t){let rows=[],r=[],f="",q=false;for(let i=0;i<t.length;i++){let c=t[i];if(q){if(c==='"'&&t[i+1]==='"'){f+='"';i++}else if(c==='"')q=false;else f+=c}else if(c==='"')q=true;else if(c===","){r.push(f);f=""}else if(c==="\n"){r.push(f.replace(/\r$/,""));rows.push(r);r=[];f=""}else f+=c}if(f||r.length){r.push(f);rows.push(r)}let heads=rows.shift();return rows.map(v=>Object.fromEntries(heads.map((k,i)=>[k,v[i]||""])))}
try{
let res=await fetch("airports.csv",{cache:"force-cache"});if(!res.ok)throw Error("HTTP "+res.status);
let all=csv(await res.text()).filter(a=>["large_airport","medium_airport","small_airport"].includes(a.type)&&a.municipality&&a.iso_country&&a.latitude_deg&&a.longitude_deg);
let cities=[...new Set(all.map(a=>a.municipality+"|||"+a.iso_country))].sort((a,b)=>a.localeCompare(b,"ru"));
$("apCity").innerHTML=cities.map(k=>`<option value="${k}">${k.replace("|||"," (")+")"}</option>`).join("");
function fill(){let [city,country]=$("apCity").value.split("|||");$("apAirport")._list=all.filter(a=>a.municipality===city&&a.iso_country===country).sort((a,b)=>a.name.localeCompare(b.name,"ru"));$("apAirport").innerHTML=$("apAirport")._list.map((a,i)=>`<option value="${i}">${a.name} — ${a.iata_code||a.ident}</option>`).join("");let n=$("apAirport")._list.findIndex(a=>a.ident===radarSettings.airport);if(n>=0)$("apAirport").value=n;coords()}
function coords(){let a=$("apAirport")._list?.[$("apAirport").selectedIndex];if(a){$("apLat").value=a.latitude_deg;$("apLon").value=a.longitude_deg}}
let saved=all.find(a=>a.ident===radarSettings.airport);let cityKey=saved?saved.municipality+"|||"+saved.iso_country:cities.find(k=>k.startsWith("Обь|||RU")||k.startsWith("Новосибирск|||RU"));if(cityKey)$("apCity").value=cityKey;
$("apCity").addEventListener("change",fill);$("apAirport").addEventListener("change",coords);fill();$("apRadius").value=radarSettings.radiusKm;
status.textContent="Аэропортов загружено: "+all.length.toLocaleString("ru-RU");
$("apApply").addEventListener("click",()=>{let latitude=Number($("apLat").value),longitude=Number($("apLon").value),radiusKm=Number($("apRadius").value);if(!Number.isFinite(latitude)||latitude< -90||latitude>90||!Number.isFinite(longitude)||longitude< -180||longitude>180||!Number.isFinite(radiusKm)||radiusKm<1||radiusKm>926){alert("Координаты: широта −90…90, долгота −180…180; радиус 1…926 км.");return}let a=$("apAirport")._list[$("apAirport").selectedIndex];radarSettings={latitude,longitude,radiusKm,city:$("apCity").value.split("|||")[0],airport:a?.ident||""};localStorage.setItem("fr24RadarSettings",JSON.stringify(radarSettings));if(map){updateRadarArea({latitude,longitude,radius_km:radiusKm,radius_nm:radiusKm/1.852});map.setView([latitude,longitude],7)}loadRadarData();status.textContent="Зона применена: "+radiusKm+" км"});
}catch(e){status.textContent="Ошибка airports.csv: "+e.message}
}
function startRadar() {
    injectInterfaceStyles();

    addRadarControls();

    addAirportSelector();

    addDetailsPanel();

    initializeMap();

    loadRadarData();

    setInterval(
        loadRadarData,
        REFRESH_INTERVAL
    );
}

document.addEventListener(
    "DOMContentLoaded",
    startRadar
);