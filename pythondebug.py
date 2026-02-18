import requests
from bs4 import BeautifulSoup

headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
response = requests.get("https://ratings.fide.com/profile/1710400", headers=headers)
soup = BeautifulSoup(response.text, "html.parser")

# Skriv ut alla div-klasser så vi ser vad som finns
for div in soup.find_all("div", class_=True):
    print(div.get("class"), "|", div.text.strip()[:50])