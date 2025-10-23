# -*- coding: utf-8 -*-
# dizipal_episodes_selenium_m3u.py

"""
Gereksinimler:
Bu script'i çalıştırmadan önce, aşağıdaki kütüphanelerin yüklü olduğundan emin olun:
pip install requests beautifulsoup4 selenium webdriver-manager
"""
import time
import json
import re
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager
from selenium.common.exceptions import TimeoutException, WebDriverException
import sys

# -------------------------
# Ayarlar
# -------------------------
# Domain URL'si, güncel dizipal adresini içeren TXT dosyasını çeker.
DOMAIN_URL = "https://raw.githubusercontent.com/zerodayip/domain/refs/heads/main/dizipal.txt"
# Dizilerin listelendiği JSON dosyası (Gerekli: dizipal/diziler.json)
JSON_FILE = "dizipal/diziler.json"
# Çıktı M3U dosyasının adı.
OUTPUT_FILE = "dizipalyerlidizi.m3u"

# Tarayıcı ve bekleme ayarları
INITIAL_PAGE_WAIT = 30       # Ana sayfa yüklendikten sonra sabit bekleme (saniye)
PAGE_LOAD_MAX_WAIT = 30      # Her bir dizi sayfası için maksimum bekleme (saniye)
HTML_PRINT_LIMIT = 2000      # Debug için terminale yazdırılacak HTML uzunluğu (karakter)
RETRY_COUNT = 1              # Sayfa açma denemesi (şu an sadece bir kere deneniyor)

# -------------------------
# Selenium başlatma (Chrome)
# -------------------------
def make_chrome_driver(headless=True):
    """Headless Chrome tarayıcıyı başlatır."""
    options = webdriver.ChromeOptions()
    # Headless modunu ayarlama
    if headless:
        options.add_argument("--headless=new") # Yeni headless modu
    
    # Otomasyon ortamları için gerekli argümanlar
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-extensions")
    options.add_argument("--window-size=1920,1080")
    
    # Tarayıcıyı gizleme (Anti-bot algılamalarını azaltma)
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    try:
        # WebDriver'ı ChromeDriverManager ile otomatik indirme ve kurma
        service = ChromeService(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)
        
        # Navigator.webdriver özelliğini gizleme (CDP injection)
        driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {
                "source": """
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                """
            },
        )
        return driver
    except WebDriverException as e:
        print(f"❌ Chrome driver başlatılamadı: {e}", file=sys.stderr)
        print("Lütfen Chrome'un kurulu ve sürümünün `webdriver-manager` tarafından desteklendiğinden emin olun.", file=sys.stderr)
        raise

# -------------------------
# Sayfa yükleme / bekleme
# -------------------------
def load_page_and_wait(driver, url, max_wait=PAGE_LOAD_MAX_WAIT, check_strings=None):
    """
    Belirtilen URL'yi yükler ve içerik yüklenene veya zaman aşımı olana kadar bekler.
    """
    print(f"  -> URL yükleniyor: {url}")
    driver.get(url)
    start = time.time()
    
    while True:
        page_source = driver.page_source
        title = driver.title or ""
        elapsed = time.time() - start

        # Başarı Kontrolü 1: Özel kontrol dizileri
        if check_strings:
            for s in check_strings:
                if s.lower() in page_source.lower():
                    return page_source, True
        
        # Başarı Kontrolü 2: Cloudflare (CF) kontrolü geçti mi?
        is_cf_challenge = "just a moment" in title.lower() or "enable javascript" in page_source.lower()
        is_cf_checking = "checking your browser" in page_source.lower()

        if not is_cf_challenge and not is_cf_checking:
            # CF kalktıysa, beklenen bir içerik var mı kontrol et
            if "episode-item" in page_source or re.search(r"IMDB\s*Puan", page_source, re.I):
                print("  -> Başarılı yükleme (beklenen içerik bulundu).")
                return page_source, True
            # CF yazısı yoksa ve sayfa değişmişse de kabul et (Bazı siteler sadece boş dönebilir)
            if elapsed > 5: # 5 saniye geçtikten sonra hala CF yoksa kabul et
                return page_source, True
        
        if elapsed >= max_wait:
            print(f"  -> Zaman aşımı ({max_wait}s).")
            return page_source, False
            
        time.sleep(1)

# -------------------------
# Scrape fonksiyonu (BeautifulSoup ile pars)
# -------------------------
def scrape_series_episodes_from_html(html_text):
    """HTML içeriğinden IMDB puanını ve bölüm linklerini ayrıştırır."""
    soup = BeautifulSoup(html_text, "html.parser")
    
    # 1. IMDB Puanı
    imdb_score = "-"
    # IMDB Puanını içeren div'i bulma
    imdb_div = soup.find("div", class_="key", string=re.compile(r"IMDB", re.I))
    if imdb_div:
        value_div = imdb_div.find_next_sibling("div", class_="value")
        imdb_score = value_div.get_text(strip=True) if value_div else "-"
    
    # 2. Bölüm Listesi
    episodes = []
    # Standart bölüm seçicisini kullanma
    for ep_div in soup.select("div.episode-item a[href]"):
        ep_href = ep_div.get("href")
        ep_title_div = ep_div.select_one("div.episode")
        ep_title = ep_title_div.get_text(strip=True) if ep_title_div else "-"
        # Tam URL değil, sadece path ekle (BASE_URL ile birleştirilecek)
        episodes.append({"href": ep_href, "title": ep_title})
    
    # Fallback: Eğer standart seçici işe yaramazsa, tüm linkleri tarayıp anahtar kelimeye göre al
    if not episodes:
        for a in soup.select("a[href]"):
            href = a.get("href")
            txt = a.get_text(strip=True) or ""
            # Linkte /bolum veya metinde Bölüm geçenleri al
            if href and ("/bolum" in href.lower() or "bölüm" in txt.lower()):
                # Yine sadece path'i al
                episodes.append({"href": href, "title": txt or href})

    return {"imdb": imdb_score, "episodes": episodes}

# -------------------------
# Ana akış
# -------------------------
def main():
    BASE_URL = None
    driver = None
    
    try:
        # 0) Chrome driver oluştur
        # Cloudflare zorluyorsa headless=False dene.
        headless = True
        driver = make_chrome_driver(headless=headless)

        # 1) DOMAIN_URL'den BASE_URL al
        print("🌍 Domain bilgisi alınıyor (tarayıcı ile)...", flush=True)
        # Direkt requests yerine selenium kullanıyoruz (CF korumalı olabilir)
        domain_page, ok = load_page_and_wait(driver, DOMAIN_URL, max_wait=10) # 10 saniye bekleme yeterli

        if not ok:
             # Eğer yüklenemediyse basit bir requests denemesi yapabiliriz (GitHub raw için)
             import requests
             try:
                 response = requests.get(DOMAIN_URL, timeout=10)
                 if response.status_code == 200:
                     domain_page = response.text
                 else:
                     print(f"❌ Domain URL'si yüklenemedi. HTTP Durumu: {response.status_code}", file=sys.stderr)
                     return
             except requests.RequestException as e:
                 print(f"❌ Domain URL'si (requests) yüklenemedi: {e}", file=sys.stderr)
                 return

        # raw içeriği body içinde düz metin olarak gelecektir
        m = re.search(r"https?://[^\s'\"<>]+", domain_page)
        if m:
            BASE_URL = m.group(0).strip()
        else:
            # fallback: sadece text olarak al
            text_only = re.sub(r"<[^>]+>", "", domain_page)
            # İlk satırı al ve temizle
            BASE_URL = text_only.strip().splitlines()[0].strip() if text_only.strip() else None

        if not BASE_URL:
            print("❌ Geçerli bir BASE_URL bulunamadı.", file=sys.stderr)
            return
            
        print(f"🌍 Kullanılan BASE_URL: {BASE_URL}")

        # 2) Ana sayfa için sabit bekleme (Site korumaları için bazen gerekli)
        print(f"⏳ Site korumaları için {INITIAL_PAGE_WAIT} saniye bekleniyor...")
        time.sleep(INITIAL_PAGE_WAIT)

        # 3) JSON oku
        print(f"📚 {JSON_FILE} okunuyor.")
        try:
            with open(JSON_FILE, "r", encoding="utf-8") as f:
                series_data = json.load(f)
        except FileNotFoundError:
            print(f"❌ JSON dosyası bulunamadı: {JSON_FILE}", file=sys.stderr)
            print("Lütfen 'dizipal/diziler.json' dosyasının doğru yolda olduğundan emin olun.", file=sys.stderr)
            return
        except json.JSONDecodeError as e:
            print(f"❌ JSON okuma hatası: {e}", file=sys.stderr)
            return

        # 4) M3U dosyası aç
        print(f"📝 {OUTPUT_FILE} dosyasına yazılıyor.")
        with open(OUTPUT_FILE, "w", encoding="utf-8") as m3u_file:
            print("#EXTM3U", file=m3u_file, flush=True)

            for series_href, info in series_data.items():
                group = info.get("group", "BİLİNMİYOR")
                tvg_logo = info.get("tvg-logo", "")
                print(f"\n🎬 {group} bölümleri çekiliyor...", flush=True)

                # Tam URL oluştur
                target_url = f"{BASE_URL}{series_href}"

                # Sayfayı headless tarayıcı ile aç ve bekle
                page_html, ok = load_page_and_wait(driver, target_url, max_wait=PAGE_LOAD_MAX_WAIT)

                # Debug: ilk kısmı yazdır
                print(f"  📄 HTML (ilk {HTML_PRINT_LIMIT} karakter):")
                if page_html:
                    print(page_html[:HTML_PRINT_LIMIT].replace('\n', ' '))
                else:
                    print("  ⚠️ HTML boş geldi.")

                if not ok:
                    print(f"  ⚠️ {group}: Sayfa yüklenemedi veya Cloudflare challenge geçilemedi (timeout).")
                    continue

                # Pars et
                try:
                    data = scrape_series_episodes_from_html(page_html)
                except Exception as e:
                    print(f"  ⚠️ {group} parsing hatası: {e}", file=sys.stderr)
                    continue

                imdb_score = data.get("imdb", "-")
                episodes = data.get("episodes", [])

                if not episodes:
                    print(f"  ⚠️ {group}: Hiç bölüm bulunamadı. Sonraki diziye geçiliyor.")
                    continue

                for ep in episodes:
                    ep_href = ep.get("href")
                    ep_title_full = (ep.get("title") or "").upper()

                    # Sezon ve Bölüm numarasını çekme (Ör: 1. SEZON 2. BÖLÜM)
                    season_match = re.search(r"(\d+)\.\s*SEZON", ep_title_full)
                    episode_match = re.search(r"(\d+)\.\s*BÖLÜM", ep_title_full)
                    season = season_match.group(1).zfill(2) if season_match else "01"
                    episode = episode_match.group(1).zfill(2) if episode_match else "01"

                    # M3U Gerekli Veriler
                    tvg_name = f"{group.upper()} S{season}E{episode}"
                    
                    # EXTINF Satırı
                    extinf_line = (
                        f'#EXTINF:-1 tvg-id="" tvg-name="{tvg_name}" '
                        f'tvg-logo="{tvg_logo}" group-title="{group.upper()}",'
                        f'{group.upper()} {int(season)}. SEZON {int(episode)}. BÖLÜM (IMDb: {imdb_score} | YERLİ DİZİ | DIZIPAL)'
                    )
                    
                    # Proxy URL
                    # ep_href'in BASE_URL'siz sadece path olması gerekiyor.
                    proxy_url = f"https://zerodayip.com/proxy/dizipal?url={BASE_URL}{ep_href}"

                    print(extinf_line, file=m3u_file, flush=True)
                    print(proxy_url, file=m3u_file, flush=True)

    except Exception as e:
        print(f"\n❌ Kritik Hata: {e}", file=sys.stderr)
        
    finally:
        if driver:
            print("\n🧹 Tarayıcı kapatılıyor.")
            driver.quit()

    if BASE_URL:
        print(f"\n✅ Dizipal m3u dosyası hazırlandı: {OUTPUT_FILE}")
    else:
        print("\n❌ İşlem tamamlanamadı. Lütfen hata mesajlarını kontrol edin.", file=sys.stderr)

if __name__ == "__main__":
    main()