# Instalacja kolektora RUM w sklepie Magento (przez GTM)

Kolektor instalujemy wyłącznie przez Google Tag Manager. W kodzie Magento nic nie zmieniamy (zasada POC).

Adres ingestu (środowisko `main` na Upsun):

```
https://ingest.main-bvxea6i-xeu4pm5hpww7u.eu-5.platformsh.site
```

## 0. Zanim zaczniesz: dwie rzeczy po naszej stronie

1. **Allowlista sklepu.** Vector odrzuca beacony z nieznanych domen. Do pliku `vector/tenants.csv` dopisz po jednej linii na każdy wariant adresu sklepu, a potem zrób push na `origin` i `upsun`:
   ```
   https://www.sklep.pl,sklep
   https://sklep.pl,sklep
   ```
   Schemat (`https://`) i host muszą się zgadzać co do znaku. Wariant z `www` i bez `www` to dwie osobne linie z tym samym tenantem.
2. **Plan Upsun.** Plan Development (128 MB RAM na aplikację) nie udźwignie ruchu całego sklepu. Do czasu podniesienia planu testuj tylko w trybie podglądu GTM (krok 3) albo ogranicz ruch (krok 5).

## 1. Sprawdź CSP sklepu

Beacon wysyłany przez `navigator.sendBeacon` podlega dyrektywie `connect-src`, a plik `rum.js` dyrektywie `script-src`.

W DevTools na stronie sklepu otwórz Network, kliknij dokument HTML i sprawdź nagłówki odpowiedzi:

- **Brak `Content-Security-Policy`** albo tylko `Content-Security-Policy-Report-Only`: niczego nie trzeba robić. Tryb report-only to domyślne ustawienie Magento 2.4 na stronach sklepu (poza płatnościami w checkout).
- **Jest `Content-Security-Policy` (tryb wymuszania):** domena ingestu musi trafić do `connect-src` i `script-src`. W Magento wymaga to wpisu w `csp_whitelist.xml` albo w konfiguracji modułu CSP, czyli zmiany po stronie sklepu. Uzgodnij to z zespołem sklepu, zanim pójdziesz dalej.

## 2. Utwórz tag w GTM

1. GTM → kontener sklepu → **Tags → New**.
2. Nazwa: `RUM collector (POC)`.
3. Tag Configuration → **Custom HTML**, z treścią:
   ```html
   <script>
     // Opcjonalnie: wersja wdrożenia sklepu, żeby porównywać metryki przed i po release.
     // window.RUM_RELEASE = '2026.10.1';
   </script>
   <script async src="https://ingest.main-bvxea6i-xeu4pm5hpww7u.eu-5.platformsh.site/static/rum.js"></script>
   ```
   Opcja „Support document.write” zostaje wyłączona.
4. Advanced Settings → Tag firing options: **Once per page**.
5. Consent Settings: kolektor nie ustawia cookies, nie zapisuje IP i nie używa identyfikatorów użytkownika. Czy tag może działać bez zgody, decyduje osoba odpowiedzialna za consent i RODO w sklepie. Nie zakładaj tego sam.
6. Triggering: **Initialization – All Pages**. Im wcześniej skrypt się załaduje, tym mniej interakcji (INP) przepadnie. LCP, CLS, FCP i TTFB są zbierane wstecz, więc późniejsze ładowanie ich nie psuje.
7. **Zapisz, ale jeszcze nie publikuj.**

## 3. Test w trybie podglądu (bez wpływu na klientów)

1. GTM → **Preview** → wpisz adres sklepu.
2. W otwartej karcie sklepu otwórz DevTools → Network i wpisz w filtr `rum`.
3. Przejdź przez kilka stron: główną, kategorię i produkt. Na każdej kliknij coś, np. filtr albo przycisk.
4. Przełącz się na inną kartę albo zamknij kartę. W Network powinien pojawić się request `rum` typu `ping` ze statusem **200**. Wcześniej, przy ładowaniu, widać `rum.js` ze statusem 200.
5. Po ok. 10 sekundach otwórz Grafanę: dashboard **RUM → RUM overview**, w filtrze Tenant wybierz nazwę sklepu.

Karta sklepu musi być widoczna na ekranie. W karcie, która cały czas była w tle, mierzone jest tylko TTFB.

## 4. Co powinno być widać w Grafanie

- Kafelki p75 dla LCP, INP, CLS, FCP i TTFB z liczbą wyświetleń stron. INP pojawia się dopiero po kliknięciu czegoś na stronie.
- Tabela „p75 by page type”, w której strona główna to `cms-index-index`, kategoria `catalog-category-view`, a produkt `catalog-product-view`. Jeśli wszystko ląduje w `other`, motyw sklepu zmienia klasy na `<body>`, więc zgłoś to.

## 5. Publikacja

Publikuj dopiero, gdy krok 3 działa, a plan Upsun jest podniesiony.

Jeśli trzeba wystartować przed podniesieniem planu, ogranicz ruch. Najprościej ustawić sampling w kolektorze, np. 10%:
```
cd collector && RUM_SAMPLE_RATE=0.1 npm run build
```
Potem commit i push. Zmiana dotyczy wszystkich sklepów naraz.

GTM → **Submit** → opis wersji, np. „RUM POC collector”.

## Rozwiązywanie problemów

| Objaw | Przyczyna | Co zrobić |
|---|---|---|
| W konsoli: `Refused to load the script … rum.js` | CSP `script-src` | Krok 1 |
| W konsoli: `Refused to connect …/rum` | CSP `connect-src` | Krok 1 |
| `rum.js` ładuje się, ale nie ma requestu `rum` | Karta nie została ukryta albo zamknięta, nie było żadnych metryk, albo strona była cały czas w tle | Przełącz kartę, gdy strona jest widoczna |
| Request `rum` ma status 200, ale w Grafanie nic nie ma | Domena nie jest na allowliście. Vector odpowiada 200 także na odrzucone beacony. | Sprawdź log: `upsun ssh -A vector -- 'grep rejected /var/log/app.log \| tail'`. Wpis `unknown origin` oznacza, że trzeba poprawić `tenants.csv` (często chodzi o `www`). |
| Wszystkie strony mają typ `other` | Motyw nie ma standardowych klas Magento na `<body>` | Zgłoś, dopasujemy listę w `collector/src/collector.js` |
| `cache_status` jest puste | Sklep nie wysyła nagłówka `Server-Timing` z wpisem `cache` | Dla POC nie szkodzi. To kwestia konfiguracji CDN lub Varnisha. |

## Wyłączenie

GTM → wstrzymaj (Pause) albo usuń tag `RUM collector (POC)` → Submit. Po stronie sklepu nic więcej nie zostaje.
