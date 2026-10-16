"""Build every CSV the page loads, from the raw TMDB pull and Netflix's Top 10 lists.

Run from the repo root:

    python3 scripts/build_data.py

Inputs are kept out of the repo because they are large or hold the API key:

    FIT3179/Assignment 2/data/raw_series.csv    one row per series, from pull_tmdb.py
    FIT3179/Assignment 2/data/raw_details.csv   seasons, episodes, type and status
    FIT3179/Assignment 2/data/raw/netflix/all-weeks-countries.tsv
        Netflix weekly Top 10 by country, https://www.netflix.com/tudum/top10
    FIT3179/Assignment 2/.env                  TMDB_API_KEY, for matching Netflix titles

Rules shared by every chart, so the numbers agree across the page:

  * Episodes per season is a series' episode count divided by its season count.
  * Series averaging more than 100 episodes a season are dropped. These are daily
    soaps, talk shows and news, which do not have seasons in the usual sense. They are
    the longest series and mostly old, so dropping them understates the fall.
  * Only series first aired from 1990 to 2025 are used; 2026 is not over.
  * A co-production counts as a series of every country it lists.
  * A country is shown for a period only when it has at least 10 series in it.
"""
import csv
import json
import re
import statistics
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "FIT3179" / "Assignment 2" / "data"
OUT = ROOT / "data"
CACHE = RAW / "raw" / "netflix"

MAX_EPS = 100
MIN_SERIES = 10
LAST_YEAR = 2025

# Short names for tooltips and labels. Two-letter codes are ISO 3166-1.
NAMES = {
    "AR": "Argentina", "AT": "Austria", "AU": "Australia", "BE": "Belgium", "BR": "Brazil",
    "CA": "Canada", "CH": "Switzerland", "CL": "Chile", "CN": "China", "CO": "Colombia",
    "CZ": "Czechia", "DE": "Germany", "DK": "Denmark", "EG": "Egypt", "ES": "Spain",
    "FI": "Finland", "FR": "France", "GB": "United Kingdom", "GR": "Greece", "HK": "Hong Kong",
    "HU": "Hungary", "ID": "Indonesia", "IE": "Ireland", "IL": "Israel", "IN": "India",
    "IR": "Iran", "IS": "Iceland", "IT": "Italy", "JP": "Japan", "KR": "South Korea",
    "LB": "Lebanon", "MX": "Mexico", "MY": "Malaysia", "NG": "Nigeria", "NL": "Netherlands",
    "NO": "Norway", "NZ": "New Zealand", "PE": "Peru", "PH": "Philippines", "PK": "Pakistan",
    "PL": "Poland", "PT": "Portugal", "RO": "Romania", "RS": "Serbia", "RU": "Russia",
    "SA": "Saudi Arabia", "SE": "Sweden", "SG": "Singapore", "SU": "Soviet Union",
    "TH": "Thailand", "TR": "Türkiye", "TW": "Taiwan", "UA": "Ukraine", "US": "United States",
    "VE": "Venezuela", "VN": "Vietnam", "ZA": "South Africa",
}
# Abbreviations for circles too small to hold a full name, in the Dorling cartogram.
ABBR = {
    "AR": "ARG", "AT": "AUT", "AU": "AUS", "BE": "BEL", "BR": "BRA", "CA": "CAN", "CN": "CHN",
    "DE": "GER", "DK": "DEN", "ES": "ESP", "FI": "FIN", "FR": "FRA", "GB": "UK", "GR": "GRE",
    "IN": "IND", "IT": "ITA", "JP": "JPN", "KR": "KOR", "MX": "MEX", "NL": "NED", "NO": "NOR",
    "PL": "POL", "RU": "RUS", "SE": "SWE", "TR": "TUR", "TW": "TWN", "US": "USA",
}
# Approximate country centres (latitude, longitude) for symbols and flow lines. The
# United States point sits in the lower 48 and France's in mainland France, rather than
# at centroids dragged off by Alaska or overseas territories.
CENTRES = {
    "AR": (-38.4, -63.6), "AT": (47.5, 14.6), "AU": (-25.3, 133.8), "BE": (50.5, 4.5),
    "BR": (-14.2, -51.9), "CA": (56.1, -106.3), "CN": (35.9, 104.2), "CO": (4.6, -74.3),
    "DE": (51.2, 10.5), "DK": (56.3, 9.5), "ES": (40.5, -3.7), "FI": (61.9, 25.7),
    "FR": (46.2, 2.2), "GB": (54.0, -2.0), "GR": (39.1, 21.8), "ID": (-2.5, 118.0),
    "IN": (20.6, 79.0), "IT": (41.9, 12.6), "JP": (36.2, 138.3), "KR": (36.5, 127.8),
    "MX": (23.6, -102.5), "MY": (3.1, 101.7), "NL": (52.1, 5.3), "NO": (60.5, 8.5),
    "PH": (12.9, 121.8), "PL": (51.9, 19.1), "RU": (61.5, 105.3), "SE": (60.1, 18.6),
    "SG": (1.35, 103.8), "TH": (15.9, 100.9), "TR": (38.9, 35.2), "TW": (23.7, 121.0),
    "US": (39.8, -98.6), "ZA": (-30.6, 22.9),
}
TOPO_IDS = json.loads((OUT / "iso_to_topo.json").read_text(encoding="utf-8"))


def write(name, rows, cols):
    with open(OUT / name, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"  wrote data/{name}: {len(rows)} rows")


def median(values):
    return statistics.median(values) if values else None


def quartiles(values):
    q = statistics.quantiles(values, n=4, method="inclusive")
    return q[0], q[2]


# ---------------------------------------------------------------- TMDB catalogue

def load_series():
    details = {r["id"]: r for r in csv.DictReader(open(RAW / "raw_details.csv", encoding="utf-8"))}
    series = []
    for r in csv.DictReader(open(RAW / "raw_series.csv", encoding="utf-8")):
        d = details.get(r["id"])
        if not d or not d["seasons"] or not d["episodes"]:
            continue
        seasons, episodes = float(d["seasons"]), float(d["episodes"])
        if seasons <= 0 or episodes <= 0 or episodes / seasons > MAX_EPS:
            continue
        year = int(r["first_air_date"][:4])
        if year > LAST_YEAR:
            continue
        series.append({
            "year": year, "month": int(r["first_air_date"][5:7]), "eps": episodes / seasons,
            "seasons": seasons, "type": d["type"],
            "countries": [c for c in (r["countries"] or "").split("|") if c],
        })
    return series


def by_country(series, first, last):
    groups = defaultdict(list)
    for s in series:
        if first <= s["year"] <= last:
            for c in s["countries"]:
                groups[c].append(s["eps"])
    return groups


def build_country_periods(series):
    """Charts 1 and 2: each country before 2005 against 2015 onward."""
    then = by_country(series, 1990, 2004)
    now = by_country(series, 2015, LAST_YEAR)
    both = sorted(c for c in then if len(then[c]) >= MIN_SERIES and len(now.get(c, [])) >= MIN_SERIES)
    falls = [c for c in both if median(now[c]) < median(then[c])]
    print(f"  {len(both)} countries qualify in both periods, {len(falls)} shortened: {both}")
    # Hong Kong qualifies but has no outline at 110m resolution, so it stays off the maps.
    mapped = [c for c in both if c in TOPO_IDS]
    period_rows, change_rows = [], []
    for c in mapped:
        for label, g in (("pre-2005", then), ("2015+", now)):
            period_rows.append({"iso": c, "name": NAMES[c], "med": round(median(g[c]), 1),
                                "n": len(g[c]), "period": label, "topo_id": TOPO_IDS[c]})
        a, b = median(then[c]), median(now[c])
        change_rows.append({"iso": c, "name": NAMES[c], "abbr": ABBR[c], "now": round(b, 1),
                            "then": round(a, 1), "change": round(b - a, 1),
                            "pct": round(100 * (b - a) / a), "n_then": len(then[c]),
                            "n_now": len(now[c]), "lat": CENTRES[c][0], "lon": CENTRES[c][1]})
    write("eps_by_country_period.csv", period_rows, ["iso", "name", "med", "n", "period", "topo_id"])
    write("eps_change_by_country.csv", change_rows,
          ["iso", "name", "abbr", "now", "then", "change", "pct", "n_then", "n_now", "lat", "lon"])


BANDS = [(4, "1 to 4"), (6, "5 or 6"), (10, "7 to 10"), (13, "11 to 13"), (20, "14 to 20"),
         (26, "21 to 26"), (MAX_EPS, "27 or more")]


def build_bands(series):
    """Chart 3: each year's new series split by season length."""
    rows = []
    for year in range(1990, LAST_YEAR + 1):
        counts = Counter(next(i for i, (top, _) in enumerate(BANDS) if s["eps"] <= top)
                         for s in series if s["year"] == year)
        total = sum(counts.values())
        for i, (_, label) in enumerate(BANDS):
            rows.append({"year": year, "band": label, "band_order": i, "n": counts[i],
                         "total": total, "share": round(counts[i] / total, 4)})
    write("eps_band_by_year.csv", rows, ["year", "band", "band_order", "n", "total", "share"])


def build_us_uk(series):
    """Chart 4: the shape of season lengths in the US and the UK, decade by decade.
    Lengths over 30 are grouped at 30 so the long tail does not stretch the axis."""
    rows = []
    for c in ("US", "GB"):
        for decade in (1990, 2000, 2010, 2020):
            vals = [min(round(s["eps"]), 30) for s in series
                    if c in s["countries"] and decade <= s["year"] <= min(decade + 9, LAST_YEAR)]
            counts = Counter(vals)
            for e in range(1, 31):
                rows.append({"country": NAMES[c], "iso": c, "decade": f"{decade}s", "eps": e,
                             "share": round(counts[e] / len(vals), 4), "n": len(vals),
                             "median": round(median([s["eps"] for s in series if c in s["countries"]
                                                     and decade <= s["year"] <= decade + 9]), 1)})
    write("eps_dist_us_uk.csv", rows, ["country", "iso", "decade", "eps", "share", "n", "median"])


PERIODS = [(1995, 1999), (2000, 2004), (2005, 2009), (2010, 2014), (2015, 2019), (2020, LAST_YEAR)]


def build_convergence(series):
    """Chart 5: every country's median in each five-year period. Starts at 1995 because
    only 12 countries reach 10 series in 1990 to 1994."""
    rows = []
    for a, b in PERIODS:
        g = by_country(series, a, b)
        meds = {c: median(v) for c, v in g.items() if len(v) >= MIN_SERIES}
        lo, hi = quartiles(list(meds.values()))
        print(f"  {a} to {b}: {len(meds)} countries, middle half {lo:.1f} to {hi:.1f}")
        for c, m in sorted(meds.items()):
            rows.append({"iso": c, "name": NAMES.get(c, c), "period": f"{a} to {b}",
                         "period_start": a, "med": round(m, 1), "n": len(g[c]),
                         "countries": len(meds)})
    write("country_medians_5yr.csv", rows,
          ["iso", "name", "period", "period_start", "med", "n", "countries"])


def build_renewal(series):
    """Chart 6: share of each year's new series that reached a second season.
    Miniseries are left out because they are made to end after one season. The 2022
    group has had the least time to be renewed, which the chart text says."""
    rows = []
    for year in (2010, 2015, 2019, 2022):
        group = [s for s in series if s["year"] == year and s["type"] != "Miniseries"]
        renewed = sum(1 for s in group if s["seasons"] >= 2)
        rows.append({"cohort": year, "n": len(group), "renewed": renewed,
                     "share": round(renewed / len(group), 4), "per100": round(100 * renewed / len(group))})
    print("  renewal:", [(r["cohort"], r["per100"]) for r in rows])
    write("renewal_by_cohort.csv", rows, ["cohort", "n", "renewed", "share", "per100"])


def build_months(series):
    """Chart 7: the month American series premiered, 1990s against the 2020s."""
    rows = []
    for label, a, b in (("1990s", 1990, 1999), ("2020s", 2020, LAST_YEAR)):
        counts = Counter(s["month"] for s in series if "US" in s["countries"] and a <= s["year"] <= b)
        total = sum(counts.values())
        for m in range(1, 13):
            rows.append({"era": label, "month": m, "n": counts[m], "share": round(counts[m] / total, 4)})
    write("premiere_month_us.csv", rows, ["era", "month", "n", "share"])


PANELS = ["US", "JP", "KR", "CN", "FR", "DE", "CA", "AU"]


def build_yearly(series):
    """Small multiples: each big producer's median year by year, beside the UK's. A year's
    figure pools that year and its neighbours, and needs at least 15 series, which keeps
    one odd year from making a spike. Every panel carries the UK line for reference."""
    def line(c):
        out = {}
        for y in range(1991, LAST_YEAR):
            v = [s["eps"] for s in series if c in s["countries"] and y - 1 <= s["year"] <= y + 1]
            if len(v) >= 15:
                out[y] = (round(median(v), 1), len(v))
        return out
    uk = line("GB")
    rows = []
    for c in PANELS:
        for iso, pts in ((c, line(c)), ("GB", uk)):
            for y, (m, n) in sorted(pts.items()):
                rows.append({"panel": NAMES[c], "series": NAMES[iso], "iso": iso, "year": y,
                             "med": m, "n": n})
    write("eps_yearly_panels.csv", rows, ["panel", "series", "iso", "year", "med", "n"])


# ---------------------------------------------------------------- Netflix Top 10, Malaysia

def tmdb_key():
    for line in (RAW.parent / ".env").read_text().splitlines():
        if line.startswith("TMDB_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("TMDB_API_KEY missing from FIT3179/Assignment 2/.env")


def tmdb(path, cache_name, **params):
    """GET a TMDB endpoint once and keep the JSON, so re-runs make no calls."""
    f = CACHE / "tmdb" / cache_name
    if f.exists():
        return json.loads(f.read_text(encoding="utf-8"))
    params["api_key"] = tmdb_key()
    url = f"https://api.themoviedb.org/3{path}?{urllib.parse.urlencode(params)}"
    for attempt in range(4):
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                data = json.loads(r.read().decode("utf-8"))
            break
        except Exception:
            time.sleep(2 ** attempt)
    else:
        raise RuntimeError(f"TMDB request failed: {path}")
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(data), encoding="utf-8")
    return data


def slug(text):
    t = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-") or "x"


def norm(text):
    t = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


def plausible(query, result, week_year):
    """A search result counts only if its English or original name matches the query,
    exactly, by containment, or closely, and, unless the name is exact, it first aired
    within 15 years of its Top 10 run. Without this, 'Idol I' matched Indian Idol and
    'The Secret of Us' matched an Australian drama from 2001."""
    q = norm(query)
    names = {norm(result.get("name") or ""), norm(result.get("original_name") or "")} - {""}
    if q in names:
        return True
    close = any((len(n) >= 5 and (n in q or q in n)) or SequenceMatcher(None, q, n).ratio() >= 0.8
                for n in names)
    year = (result.get("first_air_date") or "")[:4]
    return close and year.isdigit() and int(year) >= week_year - 15


def match(title, week_year):
    """Netflix lists a show by its English title. Of TMDB's five most popular TV results
    that pass plausible(), prefer an exact name with the same capitals (Netflix writes the
    2023 live-action show as ONE PIECE and the anime as One Piece), then an exact name in
    any case, then a close name. Ties go to the show that first aired nearest its Top 10
    run, so Little Women is the 2022 Korean drama. If the full title finds nothing, retry
    with the part before a colon, which strips season names such as 'BoBoiBoy Galaxy:
    Sori'. A show with no plausible result stays unmatched rather than guessed."""
    def rank(query, r):
        names = (r.get("name") or "", r.get("original_name") or "")
        year = (r.get("first_air_date") or "")[:4]
        tier = 0 if query in names else 1 if norm(query) in map(norm, names) else 2
        return tier, abs(week_year - int(year)) if year.isdigit() else 99
    for query in dict.fromkeys((title, title.split(":")[0].strip())):
        res = tmdb("/search/tv", f"search-{slug(query)}.json", query=query).get("results", [])
        ok = [r for r in res[:5] if plausible(query, r, week_year)]
        if ok:
            best = min(ok, key=lambda r: rank(query, r))
            return tmdb(f"/tv/{best['id']}", f"tv-{best['id']}.json")
    return None


GROUPS = ["South Korea", "Japan", "United States", "Malaysia", "United Kingdom", "Other"]


def group_of(countries):
    for iso, name in (("KR", "South Korea"), ("JP", "Japan"), ("US", "United States"),
                      ("MY", "Malaysia"), ("GB", "United Kingdom")):
        if countries and countries[0] == iso:
            return name
    return "Other"


def build_netflix():
    """Charts 8 to 10: what Malaysians watched in Netflix's weekly Top 10 for TV."""
    rows = [r for r in csv.DictReader(open(CACHE / "all-weeks-countries.tsv", encoding="utf-8"),
                                      delimiter="\t")
            if r["country_iso2"] == "MY" and r["category"] == "TV"]
    weeks = Counter(r["show_title"] for r in rows)
    first_week = {}
    for r in rows:
        first_week[r["show_title"]] = min(first_week.get(r["show_title"], r["week"]), r["week"])
    print(f"  Malaysia TV: {len(rows)} entries, {len(weeks)} shows, "
          f"{min(r['week'] for r in rows)} to {max(r['week'] for r in rows)}")
    titles = sorted(weeks)
    with ThreadPoolExecutor(8) as pool:
        found = dict(zip(titles, pool.map(match, titles,
                                          [int(first_week[t][:4]) for t in titles])))
    missing = [t for t in titles if not found[t]]
    print(f"  matched {len(titles) - len(missing)}/{len(titles)} shows on TMDB; "
          f"unmatched show-weeks {sum(weeks[t] for t in missing)}/{sum(weeks.values())}")

    shows = []
    for t in titles:
        d = found[t]
        if not d:
            continue
        cs = d.get("origin_country") or []
        seasons, episodes = d.get("number_of_seasons") or 0, d.get("number_of_episodes") or 0
        shows.append({"title": t, "tmdb_name": d.get("name", ""), "tmdb_id": d["id"], "weeks": weeks[t],
                      "first_week": first_week[t], "origin": "|".join(cs), "group": group_of(cs),
                      "seasons": seasons, "episodes": episodes,
                      "eps": round(episodes / seasons, 1) if seasons and episodes else "",
                      "first_aired": (d.get("first_air_date") or "")[:4]})
    write("netflix_my_titles.csv", shows,
          ["title", "tmdb_name", "tmdb_id", "weeks", "first_week", "origin", "group", "seasons",
           "episodes", "eps", "first_aired"])

    # Beeswarm: one circle per series. Netflix lists some seasons as separate titles
    # (each BoBoiBoy Galaxy season, for one), so titles are merged on their TMDB id.
    merged = {}
    for s in shows:
        m = merged.setdefault(s["tmdb_id"], dict(s, titles=0, weeks=0))
        m["titles"] += 1
        m["weeks"] += s["weeks"]
        if m["titles"] > 1:
            m["title"] = s["tmdb_name"]
    series_rows = [m for m in merged.values() if m["eps"] != ""]
    write("netflix_my_shows.csv", series_rows,
          ["title", "tmdb_id", "weeks", "titles", "origin", "group", "seasons", "episodes", "eps",
           "first_aired"])

    # Flow map: show-weeks by country of origin, split evenly across co-producers so the
    # shares add up to 100%. One set of rows covers all weeks ("all"), and one set covers
    # each calendar year, for the map's Play button. Shares, not weeks, size the lines, so
    # a part year such as 2021 compares fairly with a full one.
    origin_of = {s["title"]: (s["origin"].split("|") if s["origin"] else []) for s in shows}
    weeks_by = defaultdict(lambda: defaultdict(float))
    for r in rows:
        cs = origin_of.get(r["show_title"], [])
        for c in cs:
            weeks_by["all"][c] += 1 / len(cs)
            weeks_by[r["week"][:4]][c] += 1 / len(cs)
    keep = [c for c, w in sorted(weeks_by["all"].items(), key=lambda kv: -kv[1]) if c in CENTRES and w >= 5]
    left_out = {c: round(w, 1) for c, w in weeks_by["all"].items() if c not in keep}
    flows = []
    for period in ["all"] + sorted(k for k in weeks_by if k != "all"):
        total = sum(weeks_by[period].values())
        for c in keep:
            w = weeks_by[period].get(c, 0)
            flows.append({"period": period, "iso": c, "name": NAMES.get(c, c), "weeks": round(w, 1),
                          "share": round(w / total, 4), "lat": CENTRES[c][0], "lon": CENTRES[c][1]})
    print(f"  flows: {[(c, round(weeks_by['all'][c], 1)) for c in keep]}; left out {left_out}")
    write("netflix_my_origin.csv", flows, ["period", "iso", "name", "weeks", "share", "lat", "lon"])

    # Bump chart: each year's ranking of the five named origins plus everything else.
    year_weeks = defaultdict(Counter)
    group = {s["title"]: s["group"] for s in shows}
    for r in rows:
        if r["show_title"] in group:
            year_weeks[int(r["week"][:4])][group[r["show_title"]]] += 1
    bump = []
    for y in sorted(year_weeks):
        ranked = sorted(GROUPS, key=lambda g: -year_weeks[y][g])
        for g in GROUPS:
            bump.append({"year": y, "group": g, "weeks": year_weeks[y][g],
                         "rank": ranked.index(g) + 1, "total": sum(year_weeks[y].values())})
    write("netflix_my_group_year.csv", bump, ["year", "group", "weeks", "rank", "total"])


if __name__ == "__main__":
    parts = sys.argv[1:] or ["tmdb", "netflix"]
    if "tmdb" in parts:
        print("TMDB catalogue")
        s = load_series()
        print(f"  {len(s)} series kept")
        build_country_periods(s)
        build_bands(s)
        build_us_uk(s)
        build_convergence(s)
        build_renewal(s)
        build_months(s)
        build_yearly(s)
    if "netflix" in parts:
        print("Netflix Top 10, Malaysia")
        build_netflix()
