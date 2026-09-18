"""Curated major first-division football competitions.

League IDs are API-Football identifiers. API-Football states that league IDs are
unique and remain stable across seasons; season-level feature availability must
still be checked through the coverage object returned by /leagues.
"""

MAJOR_LEAGUES = {
    39: "England — Premier League",
    140: "Spain — LaLiga",
    78: "Germany — Bundesliga",
    135: "Italy — Serie A",
    61: "France — Ligue 1",
    88: "Netherlands — Eredivisie",
    94: "Portugal — Primeira Liga",
    179: "Scotland — Premiership",
    144: "Belgium — Jupiler Pro League",
    203: "Turkey — Süper Lig",
    197: "Greece — Super League",
    218: "Austria — Bundesliga",
    207: "Switzerland — Super League",
    119: "Denmark — Superliga",
    103: "Norway — Eliteserien",
    113: "Sweden — Allsvenskan",
    106: "Poland — Ekstraklasa",
    345: "Czech Republic — Czech Liga",
    210: "Croatia — HNL",
    286: "Serbia — Super Liga",
    283: "Romania — Liga I",
    333: "Ukraine — Premier League",
    235: "Russia — Premier League",
    233: "Egypt — Premier League",
    200: "Morocco — Botola Pro",
    186: "Algeria — Ligue 1",
    202: "Tunisia — Ligue 1",
    288: "South Africa — Premier Division",
    399: "Nigeria — NPFL",
    307: "Saudi Arabia — Pro League",
    301: "United Arab Emirates — Pro League",
    305: "Qatar — Stars League",
    98: "Japan — J1 League",
    292: "South Korea — K League 1",
    253: "USA — Major League Soccer",
    71: "Brazil — Serie A",
    128: "Argentina — Liga Profesional",
    262: "Mexico — Liga MX",
    239: "Colombia — Primera A",
    265: "Chile — Primera División",
    242: "Ecuador — Liga Pro",
    268: "Uruguay — Primera División",
    188: "Australia — A-League",
}

DEFAULT_MAJOR_LEAGUE_IDS = ",".join(str(league_id) for league_id in MAJOR_LEAGUES)
