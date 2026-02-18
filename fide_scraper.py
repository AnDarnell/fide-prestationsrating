import requests
from bs4 import BeautifulSoup
import pandas as pd
import math
import time
import numpy as np
from datetime import datetime, timedelta

def hamta_spelarinfo(fide_id: str) -> dict:
    url = f"https://ratings.fide.com/profile/{fide_id}"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
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
    
    except Exception as e:
        print(f"Kunde inte hämta spelarinfo: {e}")
        return {"namn": "Okänd", "ratings": {}}

def hamta_perioder(fide_id: str) -> list:
    url = f"https://ratings.fide.com/a_calculations.phtml?event={fide_id}"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    response = requests.get(url, headers=headers)
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
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
    except Exception as e:
        print(f"    Anslutningsfel för {period}: {e}")
        return []
    
    soup = BeautifulSoup(response.text, "html.parser")
    partier = []
    
    for tabell in soup.find_all("table", class_="calc_table"):
        turnering = ""
        fore_tabell = tabell.find_previous("div", class_="rtng_line01")
        if fore_tabell:
            turnering = fore_tabell.text.strip()
        
        rader = tabell.find_all("tr", bgcolor="#efefef")
        for rad in rader:
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
        print(f"  Hämtar period {p['period']}...")
        partier = hamta_partier_for_period(fide_id, p["period"], p["rating_typ"])
        alla_partier.extend(partier)
        time.sleep(1.5)
    
    df = pd.DataFrame(alla_partier)
    return df.head(hamta_antal)

def berakna_prestationsrating(df: pd.DataFrame, min_motstandare_diff: int = 400,
                               officiell_rating: int = None, antal_partier: int = 36) -> float:
    if df.empty:
        return 0.0
    
    df = df.copy().reset_index(drop=True)
    
    df["motstandare_elo"] = pd.to_numeric(
        df["motstandare_elo"].str.replace(r"[^\d.]", "", regex=True),
        errors="coerce"
    )
    df["poang"] = pd.to_numeric(df["resultat"], errors="coerce")
    df = df.dropna(subset=["motstandare_elo", "poang"])
    
    if df.empty:
        return 0.0
    
    referens_elo = officiell_rating if officiell_rating else df["motstandare_elo"].mean()
    df = df[df["motstandare_elo"] >= referens_elo - min_motstandare_diff].head(antal_partier)
    
    if df.empty:
        return 0.0
    
    # Dynamiskt halvliv baserat på antal partier
    halvliv = max(5, int(len(df) * 0.4))
    
    n = len(df)
    vikter = np.array([math.exp(-i * math.log(2) / halvliv) for i in range(n)])
    
    snitt_elo = np.average(df["motstandare_elo"], weights=vikter)
    score_procent = np.average(df["poang"], weights=vikter)
    
    if score_procent >= 1.0:
        dp = 800
    elif score_procent <= 0.0:
        dp = -800
    else:
        dp = -400 * math.log10(1 / score_procent - 1)
    
    return round(snitt_elo + dp, 1)

def main():
    print("=== FIDE Prestationsrating ===\n")
    
    while True:
        fide_id = input("Ange FIDE-ID (eller 'q' för att avsluta): ").strip()
        if fide_id.lower() == "q":
            break
        if not fide_id.isdigit():
            print("Ogiltigt ID, försök igen.\n")
            continue
        
        print("\nVälj ratingtyp:")
        print("  0 = Standard")
        print("  1 = Rapid")
        print("  2 = Blitz")
        rating_typ = input("Ratingtyp (standard är 0): ").strip() or "0"
        
        antal = input("Antal partier (standard är 36): ").strip()
        antal = int(antal) if antal.isdigit() else 36
        
        print(f"\nHämtar spelarinfo...")
        info = hamta_spelarinfo(fide_id)
        
        rating_typ_namn = {"0": "standard", "1": "rapid", "2": "blitz"}.get(rating_typ, "standard")
        officiell_rating = info["ratings"].get(rating_typ_namn, None)
        
        print(f"Hämtar de senaste {antal} partierna (max 3 år tillbaka)...\n")
        df = hamta_parti_historik(fide_id, antal_partier=antal, rating_typ=rating_typ)
        
        if df.empty:
            print("Kunde inte hitta data. Kontrollera att FIDE-ID:t är korrekt.\n")
        else:
            df_elo = df.copy()
            df_elo["motstandare_elo"] = pd.to_numeric(
                df_elo["motstandare_elo"].str.replace(r"[^\d.]", "", regex=True), errors="coerce"
            )
            referens = officiell_rating if officiell_rating else df_elo["motstandare_elo"].mean()
            df_filtrerad = df_elo[df_elo["motstandare_elo"] >= referens - 400].head(antal)
            
            borttagna = len(df) - len(df_filtrerad)
            if borttagna > 0:
                print(f"  ({borttagna} partier hoppades över pga för låg motståndarrating)\n")
            
            halvliv = max(5, int(len(df_filtrerad) * 0.4))
            
            prestationsrating = berakna_prestationsrating(
                df, min_motstandare_diff=400, officiell_rating=officiell_rating, antal_partier=antal
            )
            
            poang_numerisk = pd.to_numeric(df_filtrerad["resultat"], errors="coerce")
            score = poang_numerisk.sum()
            
            print(f"\n--- Resultat för {info['namn']} ---")
            print(f"Officiell rating:          {officiell_rating if officiell_rating else 'Okänd'}")
            print(f"Prestationsrating:         {prestationsrating}")
            if officiell_rating:
                diff = prestationsrating - officiell_rating
                riktning = "+" if diff >= 0 else ""
                print(f"Skillnad:                  {riktning}{round(diff, 1)}")
            print(f"Antal partier analyserade: {len(df_filtrerad)} (av {len(df)} hämtade)")
            print(f"Viktningens halvliv:       {halvliv} partier")
            print(f"Snitt motståndares elo:    {round(df_filtrerad['motstandare_elo'].mean(), 1)}")
            print(f"Poäng / möjliga:           {score} / {len(df_filtrerad)}")
            print(f"Score%:                    {round(score/len(df_filtrerad)*100, 1)}%\n")
        
        print("-" * 40 + "\n")

if __name__ == "__main__":
    main()

# python fide_scraper.py