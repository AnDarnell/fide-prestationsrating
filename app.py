import streamlit as st
import pandas as pd
import math
import numpy as np
import requests
import time
import os
from bs4 import BeautifulSoup
from datetime import datetime, timedelta

SCRAPER_API_KEY = os.environ.get("SCRAPER_API_KEY", "")

def scraper_get(url, timeout=60):
    if SCRAPER_API_KEY:
        proxy_url = f"http://api.scraperapi.com?api_key={SCRAPER_API_KEY}&url={requests.utils.quote(url, safe=':/?=&')}"
        return requests.get(proxy_url, timeout=timeout)
    return requests.get(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}, timeout=timeout)

def hamta_spelarinfo(fide_id: str) -> dict:
    url = f"https://ratings.fide.com/profile/{fide_id}"
    try:
        response = scraper_get(url)
        soup = BeautifulSoup(response.text, "html.parser")
        namn = ""
        namn_tag = soup.find("div", class_="profile-title-container")
        if namn_tag:
            namn = namn_tag.text.strip()
        ratings = {}
        for typ, klass in [("standard", "profile-standart"), ("rapid", "profile-rapid"), ("blitz", "profile-blitz")]:
            tag = soup.find("div", class_=klass)
            if tag:
                siffror = tag.text.strip().replace(typ.upper(), "").strip()
                try:
                    ratings[typ] = int(siffror[:4])
                except:
                    pass
        return {"namn": namn, "ratings": ratings}
    except:
        return {"namn": "Okänd", "ratings": {}}


def hamta_perioder(fide_id: str) -> list:
    url = f"https://ratings.fide.com/a_calculations.phtml?event={fide_id}"
    response = scraper_get(url)
    soup = BeautifulSoup(response.text, "html.parser")
    perioder = []
    for lanken in soup.find_all("a", class_="tur"):
        href = lanken.get("href", "")
        if "period=" in href and "rating=" in href:
            period = href.split("period=")[1].split("&")[0]
            rating_typ = href.split("rating=")[1].split("&")[0]
            perioder.append({"period": period, "rating_typ": rating_typ})
    return perioder


def hamta_partier_for_period(fide_id: str, period: str, rating_typ: str) -> list:
    url = f"https://ratings.fide.com/a_indv_calculations.php?id_number={fide_id}&rating_period={period}&t={rating_typ}"
    try:
        response = scraper_get(url)
    except:
        return []
    soup = BeautifulSoup(response.text, "html.parser")
    partier = []
    for tabell in soup.find_all("table", class_="calc_table"):
        turnering = ""
        fore_tabell = tabell.find_previous("div", class_="rtng_line01")
        if fore_tabell:
            turnering = fore_tabell.text.strip()
        for rad in tabell.find_all("tr", bgcolor="#efefef"):
            celler = rad.find_all("td", class_="list4")
            if len(celler) >= 6:
                namn = celler[0].text.strip()
                motstandare_elo = celler[3].text.strip()
                land = celler[4].text.strip()
                resultat = celler[5].text.strip()
                if namn and motstandare_elo:
                    partier.append({
                        "period": period,
                        "turnering": turnering,
                        "motstandare": namn,
                        "motstandare_elo": motstandare_elo,
                        "land": land,
                        "resultat": resultat,
                    })
    return partier


def hamta_parti_historik(fide_id: str, antal_partier: int, rating_typ: str, max_ar: int = 3, buffert: float = 2.0) -> pd.DataFrame:
    perioder = hamta_perioder(fide_id)
    perioder = [p for p in perioder if p["rating_typ"] == rating_typ]
    tidsgrans = datetime.now() - timedelta(days=max_ar * 365)
    perioder = [p for p in perioder if datetime.strptime(p["period"], "%Y-%m-%d") >= tidsgrans]
    if not perioder:
        return pd.DataFrame()
    hamta_antal = int(antal_partier * buffert)
    alla_partier = []
    for p in perioder:
        if len(alla_partier) >= hamta_antal:
            break
        alla_partier.extend(hamta_partier_for_period(fide_id, p["period"], p["rating_typ"]))
        time.sleep(1.0)
    return pd.DataFrame(alla_partier).head(hamta_antal)


def berakna_prestationsrating(df: pd.DataFrame, min_motstandare_diff: int = 400,
                               officiell_rating: int = None, antal_partier: int = 36) -> float:
    if df.empty:
        return 0.0
    df = df.copy().reset_index(drop=True)
    df["motstandare_elo"] = pd.to_numeric(
        df["motstandare_elo"].str.replace(r"[^\d.]", "", regex=True), errors="coerce"
    )
    df["poang"] = pd.to_numeric(df["resultat"], errors="coerce")
    df = df.dropna(subset=["motstandare_elo", "poang"])
    if df.empty:
        return 0.0
    referens_elo = officiell_rating if officiell_rating else df["motstandare_elo"].mean()
    df = df[df["motstandare_elo"] >= referens_elo - min_motstandare_diff].head(antal_partier)
    if df.empty:
        return 0.0
    halvliv = max(5, int(len(df) * 0.4))
    vikter = np.array([math.exp(-i * math.log(2) / halvliv) for i in range(len(df))])
    snitt_elo = np.average(df["motstandare_elo"], weights=vikter)
    score_procent = np.average(df["poang"], weights=vikter)
    if score_procent >= 1.0:
        dp = 800
    elif score_procent <= 0.0:
        dp = -800
    else:
        dp = -400 * math.log10(1 / score_procent - 1)
    return round(snitt_elo + dp, 1)


def hamta_topp_spelare(antal: int = 15) -> list:
    url = "https://ratings.fide.com/a_top.php?list=open"
    try:
        response = scraper_get(url)
        soup = BeautifulSoup(response.text, "html.parser")
        spelare = []
        for rad in soup.find_all("tr"):
            lanken = rad.find("a")
            if lanken and "/profile/" in lanken.get("href", ""):
                fide_id = lanken["href"].split("/profile/")[1]
                namn = lanken.text.strip()
                celler = rad.find_all("td")
                rating = celler[3].text.strip() if len(celler) > 3 else ""
                spelare.append({"fide_id": fide_id, "namn": namn, "rating": rating})
            if len(spelare) >= antal:
                break
        return spelare
    except:
        return []


@st.cache_data(ttl=3600)
def skanna_topp_spelare(antal_spelare: int = 15, antal_partier: int = 36) -> pd.DataFrame:
    spelare = hamta_topp_spelare(antal_spelare)
    resultat = []
    for s in spelare:
        try:
            df = hamta_parti_historik(s["fide_id"], antal_partier=antal_partier, rating_typ="0")
            officiell = int(s["rating"]) if s["rating"].isdigit() else None
            prestationsrating = berakna_prestationsrating(df, officiell_rating=officiell, antal_partier=antal_partier)
            diff = round(prestationsrating - officiell, 1) if officiell else None
            resultat.append({
                "Namn": s["namn"],
                "Officiell rating": officiell,
                "Prestationsrating": prestationsrating,
                "Skillnad": f"{'+' if diff and diff >= 0 else ''}{diff}" if diff else "-",
            })
            time.sleep(1.0)
        except:
            continue
    return pd.DataFrame(resultat)


st.set_page_config(page_title="FIDE Prestationsrating", page_icon="♟️", layout="centered")
st.title("♟️ FIDE Prestationsrating")

flik1, flik2 = st.tabs(["🔍 Beräkna spelare", "🌍 Världsrankning"])

with flik1:
    st.markdown("Beräknar en viktad prestationsrating baserad på de senaste partierna.")

    with st.form("sokformular"):
        fide_id = st.text_input("FIDE-ID", placeholder="T.ex. 1503014")
        col1, col2 = st.columns(2)
        with col1:
            rating_typ_val = st.selectbox("Ratingtyp", ["Standard", "Rapid", "Blitz"])
        with col2:
            antal = st.number_input("Antal partier", min_value=10, max_value=100, value=36, step=1)
        sokknapp = st.form_submit_button("Beräkna", use_container_width=True)

    if sokknapp:
        if not fide_id.strip().isdigit():
            st.error("Ange ett giltigt FIDE-ID (endast siffror).")
        else:
            rating_typ_map = {"Standard": "0", "Rapid": "1", "Blitz": "2"}
            rating_typ = rating_typ_map[rating_typ_val]
            rating_typ_namn = rating_typ_val.lower()

            with st.spinner("Hämtar spelarinfo..."):
                info = hamta_spelarinfo(fide_id)

            officiell_rating = info["ratings"].get(rating_typ_namn, None)

            with st.spinner(f"Hämtar de senaste {antal} partierna..."):
                df = hamta_parti_historik(fide_id, antal_partier=antal, rating_typ=rating_typ)

            if df.empty:
                st.error("Kunde inte hitta data. Kontrollera att FIDE-ID:t är korrekt.")
            else:
                df_elo = df.copy()
                df_elo["motstandare_elo"] = pd.to_numeric(
                    df_elo["motstandare_elo"].str.replace(r"[^\d.]", "", regex=True), errors="coerce"
                )
                referens = officiell_rating if officiell_rating else df_elo["motstandare_elo"].mean()
                df_filtrerad = df_elo[df_elo["motstandare_elo"] >= referens - 400].head(antal)
                borttagna = len(df) - len(df_filtrerad)

                prestationsrating = berakna_prestationsrating(
                    df, min_motstandare_diff=400, officiell_rating=officiell_rating, antal_partier=antal
                )

                poang_numerisk = pd.to_numeric(df_filtrerad["resultat"], errors="coerce")
                score = poang_numerisk.sum()
                halvliv = max(5, int(len(df_filtrerad) * 0.4))

                st.divider()
                st.subheader(f"🏆 {info['namn']}")

                col1, col2, col3 = st.columns(3)
                col1.metric("Officiell rating", officiell_rating if officiell_rating else "Okänd")
                if officiell_rating:
                    diff = round(prestationsrating - officiell_rating, 1)
                    col2.metric("Prestationsrating", prestationsrating, delta=f"{'+' if diff >= 0 else ''}{diff}")
                else:
                    col2.metric("Prestationsrating", prestationsrating)
                col3.metric("Score%", f"{round(score/len(df_filtrerad)*100, 1)}%")

                col4, col5, col6 = st.columns(3)
                col4.metric("Partier analyserade", f"{len(df_filtrerad)} / {antal}")
                col5.metric("Snitt motståndares elo", round(df_filtrerad["motstandare_elo"].mean(), 1))
                col6.metric("Viktningens halvliv", f"{halvliv} partier")

                if borttagna > 0:
                    st.info(f"{borttagna} partier hoppades över pga för låg motståndarrating.")

                st.divider()
                st.subheader("Partihistorik")
                st.dataframe(
                    df_filtrerad[["period", "turnering", "motstandare", "motstandare_elo", "land", "resultat"]],
                    use_container_width=True,
                    hide_index=True
                )

with flik2:
    st.markdown("Jämför officiell rating mot prestationsrating för världens top 15.")
    st.warning("Scanningen tar 5-10 minuter eftersom data hämtas för varje spelare. Resultatet cachas i 1 timme.")

    if st.button("Kör världsrankning-scan", use_container_width=True):
        with st.spinner("Skannar top 15 – detta tar några minuter..."):
            df_topp = skanna_topp_spelare()
        if df_topp.empty:
            st.error("Kunde inte hämta data.")
        else:
            st.divider()
            st.subheader("Top 15 – Officiell vs Prestationsrating")
            st.dataframe(df_topp, use_container_width=True, hide_index=True)