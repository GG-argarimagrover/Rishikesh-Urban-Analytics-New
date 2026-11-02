"""Step 13 – the scroll-through "story" dashboard (heat → greenery → services → education & health →
economy → mobility → priorities). Produces a single self-contained HTML file."""
from __future__ import annotations

import html as _html
import json
from pathlib import Path

import numpy as np
import pandas as pd

from .amenities import KINDS
from .context import Ctx
from .indices import RoadInfo

TEMPLATE_PATH = Path(__file__).parent / "templates" / "dashboard.html"

KIND_COLOR = {"hospital": "#ff4d4d", "pharmacy": "#ff9ecb", "school": "#4da3ff", "college": "#7a5cff",
              "supermarket": "#ffd24d", "entertainment": "#2ee6a8", "bank": "#9be37a", "transport": "#bbbbbb"}


def esc(x):
    return _html.escape(str(x))


def fin(x):
    try:
        x = float(x)
        return x if np.isfinite(x) else None
    except Exception:  # noqa: BLE001
        return None


def n(x, d=0):
    return "n/a" if x is None or not np.isfinite(x) else f"{x:,.{d}f}"


def names(idx, k=3):
    return ", ".join(esc(i) for i in list(idx)[:k]) or "–"


def _json_safe(o):
    """Recursively replace NaN/inf (invalid JSON) with None."""
    if isinstance(o, dict):
        return {k: _json_safe(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_json_safe(v) for v in o]
    if isinstance(o, (float, np.floating)):
        return float(o) if np.isfinite(o) else None
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    return o


def build_dashboard(ctx: Ctx, cnt: dict, roads: RoadInfo, real: dict, has_ndvi: bool) -> tuple[str, dict]:
    """Returns (html_fragment, summary_dict)."""
    cfg = ctx.cfg
    H = cfg.language == "Hinglish"

    def T(en, hi):
        return hi if H else en

    units = ctx.units
    CNT = cnt
    rl = roads.layer
    major_d = roads.major_dist
    edu_real, health_real, econ_real, mob_real = real["edu"], real["health"], real["econ"], real["mob"]

    KIND_LABEL = {"hospital": T("Hospitals / clinics", "Hospital / clinic"), "pharmacy": T("Pharmacies", "Medical stores"),
                  "school": T("Schools", "School"), "college": T("Colleges", "College"),
                  "supermarket": T("Super-markets / markets", "Super market / bazaar"),
                  "entertainment": T("Entertainment hubs", "Entertainment hub"), "bank": T("Banks / ATMs", "Bank / ATM"),
                  "transport": T("Transport stops", "Transport stops")}

    # ------------------------------------------------------------ aggregates per place
    u = units
    tot_pop = float(u["pop"].sum())
    HAS_POP = tot_pop > 0
    b = u[u.is_built].copy()
    b["pop_hot"] = b["pop"].where(b.hot, 0)
    b["pop_pri"] = b["pop"].where(b.priority, 0)
    pl = (b.groupby("place").agg(units=("uid", "count"), pop=("pop", "sum"), lst=("lst_c", "mean"), ndvi=("ndvi", "mean"),
                                  access=("access_score", "mean"), edu=("edu_idx", "mean"), health=("health_idx", "mean"),
                                  econ=("econ_idx", "mean"), mob=("mob_idx", "mean"), pop_hot=("pop_hot", "sum"),
                                  pop_pri=("pop_pri", "sum"), n_pri=("priority", "sum")))
    pl = pl[pl.units >= 2]
    if pl.empty:                     # very small datasets: fall back to every place
        pl = b.groupby("place").agg(units=("uid", "count"), pop=("pop", "sum"), lst=("lst_c", "mean"), ndvi=("ndvi", "mean"),
                                    access=("access_score", "mean"), edu=("edu_idx", "mean"), health=("health_idx", "mean"),
                                    econ=("econ_idx", "mean"), mob=("mob_idx", "mean"), pop_hot=("pop_hot", "sum"),
                                    pop_pri=("pop_pri", "sum"), n_pri=("priority", "sum"))

    def top(col, asc=False, k=3):
        return pl[col].dropna().sort_values(ascending=asc).head(k).index

    def pshare(mask):
        return 100 * u.loc[mask, "pop"].sum() / tot_pop if HAS_POP else np.nan

    def wmean(col):
        v = b[col]
        ok = v.notna()
        return float(np.average(v[ok], weights=b.loc[ok, "pop"])) if HAS_POP and b.loc[ok, "pop"].sum() > 0 else float(v.mean())

    area_km2 = ctx.aoi.area / 1e6
    built_km2 = b.geometry.area.sum() / 1e6
    n_bld = int(u["n_buildings"].sum()) if "n_buildings" in u else None
    SEC = []

    # ---- Section 1: overview
    SEC.append(dict(id="overview", icon="🏔️", title=T("Rishikesh at a glance", "Rishikesh ek nazar mein"),
      text=T(f"The study area covers <b>{n(area_km2)} km²</b>, of which about <b>{n(built_km2)} km²</b> is built-up. "
             + (f"Roughly <b>{n(tot_pop)}</b> people live here (≈ <b>{n(tot_pop / built_km2)}</b> people per built-up km²). " if HAS_POP else "")
             + "Scroll down – each step explains one aspect of the city and the map on the right changes with you.",
             f"Study area <b>{n(area_km2)} km²</b> ka hai, jisme lagbhag <b>{n(built_km2)} km²</b> built-up hai. "
             + (f"Yahan takriban <b>{n(tot_pop)}</b> log rehte hain (≈ <b>{n(tot_pop / built_km2)}</b> log per built-up km²). " if HAS_POP else "")
             + "Neeche scroll karte jaiye – har step mein sheher ka ek pehlu samjhaya gaya hai aur right side ka map saath-saath badalta hai."),
      kpis=[[n(area_km2), "km² area"], [n(built_km2), "km² built-up"]] + ([[n(tot_pop), T("people", "log")]] if HAS_POP else [])
            + ([[n(n_bld), T("buildings", "imaarat")]] if n_bld else []),
      layers=["pop"] if HAS_POP else ["lst"]))

    # ---- Section 2: heat
    ref = float(b.lst_c.median()); mx = float(b.lst_c.max()); gap = float(b.lst_c.quantile(.9) - b.lst_c.quantile(.1))
    p40 = 100 * float((b.lst_c >= 40).mean()); pop_hot = float(u.loc[u.hot, "pop"].sum())
    SEC.append(dict(id="heat", icon="🔥", title=T("Heat – where it burns most", "Garmi – kahan sabse zyada"),
      text=T(f"In a typical pre-monsoon summer the median built-up surface temperature is <b>{n(ref, 1)}°C</b>, and the hottest cell reaches <b>{n(mx, 1)}°C</b>. "
             f"<b>{n(p40)}%</b> of built-up cells cross 40°C. Hottest places: <b>{names(top('lst'))}</b>. Coolest: <b>{names(top('lst', True))}</b>. "
             f"The gap between the hot and cool parts of town is about <b>{n(gap, 1)}°C</b>."
             + (f" About <b>{n(pop_hot)}</b> people live in the hottest 10% of cells." if HAS_POP else ""),
             f"Pre-monsoon garmi mein built-up area ka median surface temperature <b>{n(ref, 1)}°C</b> hai aur sabse garam cell <b>{n(mx, 1)}°C</b> tak jaata hai. "
             f"<b>{n(p40)}%</b> built-up cells 40°C se upar hain. Sabse zyada garmi: <b>{names(top('lst'))}</b>. Sabse thanda: <b>{names(top('lst', True))}</b>. "
             f"Garam aur thande hisson mein lagbhag <b>{n(gap, 1)}°C</b> ka fark hai."
             + (f" Sabse garam 10% cells mein lagbhag <b>{n(pop_hot)}</b> log rehte hain." if HAS_POP else "")),
      kpis=[[n(ref, 1) + "°C", T("median", "median")], [n(mx, 1) + "°C", T("hottest cell", "sabse garam cell")], [n(p40) + "%", T("built-up ≥ 40°C", "built-up ≥ 40°C")],
            [n(gap, 1) + "°C", T("hot–cool gap", "garam–thanda fark")]],
      layers=["lst"],
      chart=dict(type="bar", horizontal=True, title=T("Hottest places (avg °C)", "Sabse garam jagah (avg °C)"),
                 labels=[str(x) for x in top("lst", False, 8)], datasets=[dict(label="°C", color="#ff7a45", data=[fin(round(v, 1)) for v in pl.loc[top("lst", False, 8), "lst"]])])))

    # ---- Section 3: greenery
    if has_ndvi:
        _m = u.is_built & u.lst_c.notna() & u.ndvi.notna()
        slope = None
        if _m.sum() > 20:
            slope = float(np.polyfit(u.ndvi[_m], u.lst_c[_m], 1)[0])
        cool01 = -slope * 0.1 if slope is not None else None
        g_all = 100 * float((u.ndvi >= 0.4).mean()); low_b = 100 * float((b.ndvi < 0.2).mean())
        rel_en = (f"Every +0.1 of greenery goes with about <b>{n(cool01, 1)}°C</b> lower surface temperature." if cool01 and cool01 > 0
                  else "No clear greenery–temperature link was found in this data.")
        rel_hi = (f"Hariyali (NDVI) har +0.1 badhne par surface temperature lagbhag <b>{n(cool01, 1)}°C</b> kam milta hai." if cool01 and cool01 > 0
                  else "Is data mein hariyali aur temperature ka saaf rishta nahi mila.")
        pts = [dict(x=fin(round(a_, 2)), y=fin(round(b_, 1))) for a_, b_ in zip(b.ndvi.dropna().head(700), b.loc[b.ndvi.notna(), "lst_c"].head(700))]
        SEC.append(dict(id="green", icon="🌳", title=T("Greenery – the natural cooler", "Hariyali – kudrati cooler"),
          text=T(f"Average greenery (NDVI) in built-up Rishikesh is <b>{n(b.ndvi.mean(), 2)}</b>; <b>{n(g_all)}%</b> of the study area is dense green (NDVI ≥ 0.4) "
                 f"while <b>{n(low_b)}%</b> of built-up cells have very little vegetation. Greenest: <b>{names(top('ndvi'))}</b>. Barest: <b>{names(top('ndvi', True))}</b>. " + rel_en,
                 f"Built-up Rishikesh mein average hariyali (NDVI) <b>{n(b.ndvi.mean(), 2)}</b> hai; study area ka <b>{n(g_all)}%</b> ghana hara hai (NDVI ≥ 0.4), "
                 f"jabki <b>{n(low_b)}%</b> built-up cells mein bahut kam vegetation hai. Sabse hara: <b>{names(top('ndvi'))}</b>. Sabse kam hara: <b>{names(top('ndvi', True))}</b>. " + rel_hi),
          kpis=[[n(b.ndvi.mean(), 2), T("avg NDVI (built-up)", "avg NDVI (built-up)")], [n(g_all) + "%", T("dense green area", "ghana hara area")],
                [n(low_b) + "%", T("built-up with low green", "kam hariyali wale cells")], [("−" + n(cool01, 1) + "°C") if cool01 else "–", T("per +0.1 NDVI", "per +0.1 NDVI")]],
          layers=["ndvi"],
          chart=dict(type="scatter", title=T("Greenery vs temperature (each dot = 1 cell)", "Hariyali vs temperature (har dot = 1 cell)"), points=pts,
                     xlabel="NDVI", ylabel="°C")))

    # ---- Section 4: services
    def ppl(k):
        return tot_pop / CNT[k] if HAS_POP and CNT[k] else None

    sh_school, sh_hosp, sh_mart = pshare(u.dist_school <= 1000), pshare(u.dist_hospital <= 2000), pshare(u.dist_supermarket <= 1000)
    SEC.append(dict(id="services", icon="🏥", title=T("Services – hospitals, schools, markets, fun", "Suvidhayein – hospital, school, market, entertainment"),
      text=T(f"The data shows <b>{CNT['hospital']}</b> hospitals/clinics, <b>{CNT['pharmacy']}</b> pharmacies, <b>{CNT['school']}</b> schools, <b>{CNT['college']}</b> colleges, "
             f"<b>{CNT['supermarket']}</b> super-markets/markets, <b>{CNT['entertainment']}</b> entertainment hubs (cafés, parks, ghats, adventure spots…) and <b>{CNT['bank']}</b> banks/ATMs."
             + (f" That is about <b>{n(ppl('school'))}</b> people per school and <b>{n(ppl('hospital'))}</b> per hospital/clinic. "
                f"<b>{n(sh_school)}%</b> of people have a school within 1 km, <b>{n(sh_hosp)}%</b> a hospital/clinic within 2 km, <b>{n(sh_mart)}%</b> a market within 1 km." if HAS_POP else "")
             + " Tick the boxes on the map to see each facility.",
             f"Data ke hisaab se <b>{CNT['hospital']}</b> hospital/clinic, <b>{CNT['pharmacy']}</b> medical store, <b>{CNT['school']}</b> school, <b>{CNT['college']}</b> college, "
             f"<b>{CNT['supermarket']}</b> super market/bazaar, <b>{CNT['entertainment']}</b> entertainment hub (café, park, ghat, adventure spot…) aur <b>{CNT['bank']}</b> bank/ATM hain."
             + (f" Yaani lagbhag <b>{n(ppl('school'))}</b> logon par 1 school aur <b>{n(ppl('hospital'))}</b> logon par 1 hospital/clinic. "
                f"<b>{n(sh_school)}%</b> logon ke 1 km mein school, <b>{n(sh_hosp)}%</b> ke 2 km mein hospital/clinic, <b>{n(sh_mart)}%</b> ke 1 km mein market hai." if HAS_POP else "")
             + " Map par box tick karke har suvidha ke points dekhiye."),
      kpis=[[str(CNT[k]), KIND_LABEL[k]] for k in ("hospital", "school", "college", "supermarket", "entertainment", "bank")],
      layers=["access"], poi=True,
      chart=dict(type="bar", horizontal=False, title=T("Facilities found", "Kitni suvidhayein mili"), labels=[KIND_LABEL[k] for k in KINDS],
                 datasets=[dict(label="count", color="#4da3ff", data=[CNT[k] for k in KINDS])]),
      note=T("Counts depend on how complete your amenity layer / OpenStreetMap is – treat them as a minimum.",
             "Ginti aapke amenity layer / OpenStreetMap ki completeness par depend karti hai – ise minimum maaniye.")))

    # ---- Section 5: education & health
    e_lab = T("Education rate", "Shiksha dar") if edu_real else T("Education access index", "Shiksha access index")
    h_lab = T("Health rate", "Swasthya dar") if health_real else T("Health access index", "Swasthya access index")
    _ew = (pl.edu.fillna(0) + pl.health.fillna(0)) / 2
    _worst = _ew.sort_values().head(8).index
    SEC.append(dict(id="edu_health", icon="🎓", title=T("Education & health", "Shiksha aur swasthya"),
      text=T(f"{e_lab}: <b>{n(wmean('edu_idx'), 0)}/100</b> · {h_lab}: <b>{n(wmean('health_idx'), 0)}/100</b>"
             + ("" if (edu_real and health_real) else " – these are <i>access</i> indices (how close schools/colleges and hospitals/pharmacies are), not literacy or health outcomes.")
             + f" Weakest education access: <b>{names(top('edu', True))}</b>. Weakest health access: <b>{names(top('health', True))}</b>.",
             f"{e_lab}: <b>{n(wmean('edu_idx'), 0)}/100</b> · {h_lab}: <b>{n(wmean('health_idx'), 0)}/100</b>"
             + ("" if (edu_real and health_real) else " – ye <i>access</i> index hain (school/college aur hospital/medical store kitne paas hain), literacy ya health outcome nahi.")
             + f" Shiksha mein sabse kamzor: <b>{names(top('edu', True))}</b>. Swasthya mein sabse kamzor: <b>{names(top('health', True))}</b>."),
      kpis=[[n(wmean("edu_idx")), e_lab], [n(wmean("health_idx")), h_lab]]
            + ([[n(pshare(u.dist_school <= 1000)) + "%", T("people ≤1 km from school", "log ≤1 km school")], [n(pshare(u.dist_hospital > 3000)) + "%", T("people >3 km from hospital", "log >3 km hospital se door")]] if HAS_POP else []),
      layers=["edu", "health"],
      chart=dict(type="bar", horizontal=True, title=T("Places with weakest access (0–100)", "Sabse kamzor access wali jagah (0–100)"), labels=[str(x) for x in _worst],
                 datasets=[dict(label=e_lab, color="#4da3ff", data=[fin(round(v, 0)) for v in pl.loc[_worst, "edu"]]),
                           dict(label=h_lab, color="#ff4d4d", data=[fin(round(v, 0)) for v in pl.loc[_worst, "health"]])])))

    # ---- Section 6: economy
    ec_lab = T("Income index", "Aamdani index") if econ_real else T("Economic-activity proxy", "Aarthik gatividhi proxy")
    SEC.append(dict(id="econ", icon="💰", title=T("Economy & income", "Arthvyavastha aur aamdani"),
      text=T(f"{ec_lab}: highest in <b>{names(top('econ'))}</b>, lowest in <b>{names(top('econ', True))}</b>."
             + ("" if econ_real else " No real income data is in the GeoPackage, so this is a <i>proxy</i> built from building density, building size, shops/banks/entertainment around, and road density. "
                                       "Replace it with census / survey income by typing the column name in INCOME_COLUMN."),
             f"{ec_lab}: sabse zyada <b>{names(top('econ'))}</b> mein, sabse kam <b>{names(top('econ', True))}</b> mein."
             + ("" if econ_real else " GeoPackage mein asli aamdani data nahi hai, isliye ye ek <i>proxy</i> hai (building density, building size, aas-paas dukaan/bank/entertainment aur road density se). "
                                       "Census/survey ki aamdani lagane ke liye INCOME_COLUMN mein column ka naam likhiye.")),
      kpis=[[n(u.econ_idx.mean()), T("avg index", "avg index")], [n(pl.econ.max()), T("highest place", "sabse zyada")], [n(pl.econ.min()), T("lowest place", "sabse kam")],
            [str(CNT["supermarket"] + CNT["bank"] + CNT["entertainment"]), T("commercial points", "commercial points")]],
      layers=["econ"],
      chart=dict(type="bar", horizontal=True, title=ec_lab + " – " + T("top places", "top jagah"), labels=[str(x) for x in top("econ", False, 8)],
                 datasets=[dict(label="index", color="#ffd24d", data=[fin(round(v, 0)) for v in pl.loc[top("econ", False, 8), "econ"]])])))

    # ---- Section 7: mobility
    m_lab = T("Traffic index", "Traffic index") if mob_real else T("Mobility / connectivity index", "Mobility / connectivity index")
    tot_km = float(u.road_km.sum()); mj_share = 100 * float((major_d < 500).mean()) if major_d is not None and major_d.notna().any() else None
    _wm = top("mob", True, 8)
    SEC.append(dict(id="mobility", icon="🚦", title=T("Traffic & mobility", "Traffic aur aavagaman"),
      text=T((f"The road layer holds <b>{n(tot_km)} km</b> of roads (<b>{n(tot_km / area_km2, 1)} km per km²</b>)"
              + (f"; about <b>{n(tot_pop / tot_km)}</b> people share each km of road" if HAS_POP and tot_km else "") + ". " if rl else "No road layer was found. ")
             + f"{m_lab}: best connected <b>{names(top('mob'))}</b>, least connected <b>{names(top('mob', True))}</b>."
             + ("" if mob_real else " This shows how <i>well connected</i> a place is (road density, nearness to main roads, bus/taxi stops); real traffic counts need a traffic dataset – add it via TRAFFIC_COLUMN."),
             (f"Road layer mein <b>{n(tot_km)} km</b> sadak hai (<b>{n(tot_km / area_km2, 1)} km per km²</b>)"
              + (f"; har km sadak par lagbhag <b>{n(tot_pop / tot_km)}</b> log" if HAS_POP and tot_km else "") + ". " if rl else "Road layer nahi mili. ")
             + f"{m_lab}: sabse achhi connectivity <b>{names(top('mob'))}</b>, sabse kamzor <b>{names(top('mob', True))}</b>."
             + ("" if mob_real else " Ye batata hai ki jagah kitni <i>connected</i> hai (road density, main road se doori, bus/taxi stops); asli traffic ginti ke liye traffic dataset chahiye – TRAFFIC_COLUMN mein jodiye.")),
      kpis=[[n(tot_km) + " km", T("roads", "sadak")], [n(tot_km / area_km2, 1), "km / km²"], [n(u.mob_idx.mean()), m_lab]]
            + ([[n(mj_share) + "%", T("cells within 500 m of a main road", "cells main road se 500 m ke andar")]] if mj_share is not None else []),
      layers=["mob"],
      chart=dict(type="bar", horizontal=True, title=T("Least connected places (0–100)", "Sabse kam connected jagah (0–100)"), labels=[str(x) for x in _wm],
                 datasets=[dict(label="index", color="#2ee6a8", data=[fin(round(v, 0)) for v in pl.loc[_wm, "mob"]])])))

    # ---- Section 8: priorities
    n_pri = int(u.priority.sum()); pop_pri = float(u.loc[u.priority, "pop"].sum())
    _miss = (u.loc[u.priority, "missing"].str.split(", ").explode().value_counts().drop(["none", ""], errors="ignore").head(3).index.tolist())
    _tp = pl.sort_values("pop_pri" if HAS_POP else "n_pri", ascending=False).head(8)
    SEC.append(dict(id="priority", icon="⚠️", title=T("Priority zones – where to act first", "Priority zones – pehle kahan kaam karein"),
      text=T(f"<b>{n_pri}</b> cells are both very hot and poorly served" + (f", home to about <b>{n(pop_pri)}</b> people (<b>{n(100 * pop_pri / tot_pop, 1)}%</b>)" if HAS_POP else "")
             + f". Biggest hot-spots: <b>{names(_tp.index, 4)}</b>. Most common missing services there: <b>{', '.join(_miss) or '–'}</b>. "
             "Suggested action: shade trees and cool roofs, drinking-water points, and new health/education/market services in these zones first.",
             f"<b>{n_pri}</b> cells aise hain jo bahut garam bhi hain aur suvidhaon mein kamzor bhi" + (f"; inme lagbhag <b>{n(pop_pri)}</b> log (<b>{n(100 * pop_pri / tot_pop, 1)}%</b>) rehte hain" if HAS_POP else "")
             + f". Sabse bade hot-spot: <b>{names(_tp.index, 4)}</b>. Yahan aksar kam milne wali suvidhayein: <b>{', '.join(_miss) or '–'}</b>. "
             "Sujhav: in zones mein pehle chhaya wale ped, cool roof, peene ka pani, aur health/shiksha/market suvidhayein badhayein."),
      kpis=[[str(n_pri), T("priority cells", "priority cells")]] + ([[n(pop_pri), T("people affected", "prabhavit log")]] if HAS_POP else []) + [[str(len(_miss)), T("service types missing", "kam suvidha prakar")]],
      layers=["cls"],
      chart=dict(type="bar", horizontal=True, title=T("People in hot + under-served cells", "Garam + kam suvidha cells mein log") if HAS_POP else T("Priority cells per place", "Priority cells per jagah"),
                 labels=[str(x) for x in _tp.index], datasets=[dict(label="", color="#d7191c", data=[fin(round(v, 0)) for v in (_tp.pop_pri if HAS_POP else _tp.n_pri)])]),
      table=dict(headers=[T("Place", "Jagah"), T("People (priority)", "Log (priority)"), "Avg °C", T("Access", "Access")],
                 rows=[[esc(i), n(r.pop_pri), n(r.lst, 1), n(r.access)] for i, r in _tp.iterrows()])))

    # ------------------------------------------------------------ map layers + HTML
    LAYERS = {
     "pop": dict(prop="pop", label=T("Population", "Aabadi"), stops=["#ffffcc", "#fed976", "#fd8d3c", "#e31a1c", "#800026"], all=True, dec=0),
     "lst": dict(prop="lst", label=T("Summer temperature °C", "Garmi ka temperature °C"), stops=["#2c7bb6", "#abd9e9", "#ffffbf", "#fdae61", "#d7191c", "#7f0000"], all=True, dec=1),
     "ndvi": dict(prop="ndvi", label=T("Greenery (NDVI)", "Hariyali (NDVI)"), stops=["#8c510a", "#f6e8c3", "#c7e9b4", "#41ab5d", "#00441b"], all=True, dec=2),
     "access": dict(prop="access", label=T("Amenity access", "Suvidha access"), stops=["#d7191c", "#fdae61", "#ffffbf", "#a6d96a", "#1a9641"], dec=0),
     "edu": dict(prop="edu", label=e_lab, stops=["#d7191c", "#fdae61", "#ffffbf", "#74add1", "#313695"], dec=0),
     "health": dict(prop="health", label=h_lab, stops=["#d7191c", "#fdae61", "#ffffbf", "#a6d96a", "#1a9641"], dec=0),
     "econ": dict(prop="econ", label=ec_lab, stops=["#fff7bc", "#fec44f", "#ec7014", "#993404"], dec=0),
     "mob": dict(prop="mob", label=m_lab, stops=["#d7191c", "#fdae61", "#ffffbf", "#66c2a5", "#006d2c"], dec=0),
     "cls": dict(prop="cls", label=T("Priority classes", "Priority classes"), cats={"Hot + low amenities": "#d7191c", "Hot": "#fd8d3c", "Low amenities": "#3182bd", "OK": "#c7e9c0", "Non-built": "#dddddd"}),
    }
    g = units[["place", "pop", "lst_c", "ndvi", "access_score", "edu_idx", "health_idx", "econ_idx", "mob_idx", "class", "is_built", "geometry"]].copy()
    g.columns = ["place", "pop", "lst", "ndvi", "access", "edu", "health", "econ", "mob", "cls", "built", "geometry"]
    for c in ("pop", "access", "edu", "health", "econ", "mob"):
        g[c] = g[c].round(0)
    g["geometry"] = g.geometry.simplify(3)
    g = g.to_crs(4326)
    geo = json.loads(g.to_json(drop_id=True))

    pp = ctx.pois.to_crs(4326)
    poi_json = {}
    for k in KINDS:
        if k == "transport":
            continue
        s = pp[pp.kind == k].head(1500)
        poi_json[k] = [[round(p.y, 5), round(p.x, 5)] for p in s.geometry]
    poi_meta = {k: dict(label=KIND_LABEL[k], color=KIND_COLOR[k], n=CNT[k]) for k in poi_json}

    payload = dict(title=T("Rishikesh Urban Intelligence Dashboard", "Rishikesh Urban Intelligence Dashboard"),
                   subtitle=T("Heat · Greenery · Services · Education & Health · Economy · Mobility",
                              "Garmi · Hariyali · Suvidhayein · Shiksha-Swasthya · Arthvyavastha · Mobility"),
                   center=[float(ctx.aoi_ll.centroid.y), float(ctx.aoi_ll.centroid.x)], geo=geo, layers=LAYERS,
                   sections=SEC, poi=poi_json, poiMeta=poi_meta)
    payload_js = json.dumps(_json_safe(payload), ensure_ascii=False).replace("</", "<\\/")
    html_out = TEMPLATE_PATH.read_text(encoding="utf-8").replace("__PAYLOAD__", payload_js)

    summary = dict(area_km2=area_km2, built_km2=built_km2, population=tot_pop if HAS_POP else None,
                   median_lst_c=ref, max_lst_c=mx, priority_cells=n_pri, priority_population=pop_pri if HAS_POP else None,
                   poi_counts=CNT, sections=[s["id"] for s in SEC])
    return html_out, _json_safe(summary)


def wrap_standalone(fragment: str) -> str:
    return ("<!DOCTYPE html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<title>Rishikesh Urban Intelligence Dashboard</title></head><body style='margin:0;background:#0f1720'>"
            + fragment + "</body></html>")
