import requests
from bs4 import BeautifulSoup
from typing import List, Dict, Any
import random

# --- Modelos de Dados ---
# Usaremos dicionários aqui para manter a flexibilidade antes de validar com Pydantic
AssetData = Dict[str, Any]

# --- Rotação de User-Agents ---
# Uma técnica crucial para evitar o bloqueio 403 é rotacionar o User-Agent
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/109.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/109.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.1 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36",
]


def get_random_header():
    return {"User-Agent": random.choice(USER_AGENTS)}


# --- Provedor 1: API do CoinMarketCap (MUITO MAIS ROBUSTO) ---
def scrape_coinmarketcap() -> List[AssetData]:
    print("Tentando provedor: API do CoinMarketCap")
    # Este é o endpoint da API interna que o site usa
    URL = "https://api.coinmarketcap.com/data-api/v3/cryptocurrency/listing"

    # Parâmetros para a requisição, como número de moedas, etc.
    # start=1, limit=100 significa que queremos as 100 primeiras moedas
    PARAMS = {
        "start": "1",
        "limit": "100",
        "sortBy": "market_cap",
        "sortType": "desc",
        "convert": "USD",
        "cryptoType": "all",
        "tagType": "all",
        "audited": "false",
    }

    # É crucial enviar os headers corretos para a API não nos bloquear
    HEADERS = {
        "Accept": "application/json",
        "Accept-Encoding": "deflate, gzip, br",
        "Accept-Language": "en-US,en;q=0.9",
        "Origin": "https://coinmarketcap.com",
        "Referer": "https://coinmarketcap.com/",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/109.0.0.0 Safari/537.36",
    }

    assets_list = []
    try:
        response = requests.get(URL, params=PARAMS, headers=HEADERS, timeout=10)
        response.raise_for_status()  # Lança erro se a requisição falhar (ex: 404, 500)

        data = response.json()  # Converte a resposta em um dicionário Python

        # Navega pela estrutura do JSON para encontrar a lista de moedas
        crypto_list = data.get("data", {}).get("cryptoCurrencyList", [])

        if not crypto_list:
            print("  -> A API retornou uma lista de moedas vazia.")
            return []

        for coin in crypto_list:
            # Extrai os dados que precisamos da resposta da API
            name = coin.get("name")
            symbol = coin.get("symbol")
            logo_url = f"https://s2.coinmarketcap.com/static/img/coins/64x64/{coin.get('id')}.png"

            # Os dados de preço e ATH estão dentro de 'quotes'
            quote = next(
                (q for q in coin.get("quotes", []) if q.get("name") == "USD"), None
            )

            if not quote:
                continue

            price = quote.get("price", 0.0)
            percent_from_ath = quote.get(
                "percentChange24h", 0.0
            )  # A API não fornece % do ATH diretamente. Vamos usar a variação de 24h como um substituto por enquanto.
            # NOTA: Usar a variação de 24h é uma limitação desta API. Mais tarde poderíamos buscar o ATH em outra fonte.
            # Por agora, para o Pain Index, vamos simular a dor baseada na queda diária.

            # Se a queda for grande, simulamos um percent_from_ath maior
            if percent_from_ath < -5:
                # Simulação para criar um "pain score" mais dramático
                simulated_ath_drop = -50 + (percent_from_ath * 2)
            else:
                simulated_ath_drop = percent_from_ath

            assets_list.append(
                {
                    "id": coin.get("id"),
                    "name": coin.get("name"),
                    "symbol": coin.get("symbol"),
                    "quote_usd": quote,  # Passa o dicionário de cotação inteiro
                    "logo_url": f"https://s2.coinmarketcap.com/static/img/coins/64x64/{coin.get('id')}.png",
                }
            )

    except requests.exceptions.RequestException as e:
        print(f"  -> Falha na API do CoinMarketCap: {e}")
        return []

    print(
        f"  -> Sucesso na API do CoinMarketCap! {len(assets_list)} moedas encontradas."
    )
    return assets_list


# --- Provedor 2: CoinGecko (Nosso Plano B) ---
def scrape_coingecko() -> List[AssetData]:
    print("Tentando provedor: CoinGecko")
    URL = "https://www.coingecko.com/"
    assets_list = []

    try:
        page = requests.get(URL, headers=get_random_header(), timeout=10)
        page.raise_for_status()
        soup = BeautifulSoup(page.content, "lxml")

        coin_table = soup.find("tbody")
        if not coin_table:
            return []

        coin_rows = coin_table.find_all("tr")

        for row in coin_rows:
            try:
                name_tag = row.find("span", class_="lg:tw-flex")
                symbol_tag = row.find("span", class_="d-lg-inline")
                price_tag = row.find("td", class_="td-price")
                ath_change_tag = row.find("td", class_="td-ath_change_percentage")
                logo_tag = row.find("img", class_="coin-icon")

                if not all([name_tag, symbol_tag, price_tag, ath_change_tag, logo_tag]):
                    continue

                name = name_tag.get_text(strip=True)
                symbol = symbol_tag.get_text(strip=True)
                price_str = (
                    price_tag.get_text(strip=True).replace("$", "").replace(",", "")
                )
                ath_change_str = ath_change_tag["data-sort"]
                logo_url = logo_tag["src"]

                assets_list.append(
                    {
                        "name": name,
                        "symbol": symbol,
                        "price": float(price_str),
                        "percent_from_ath": float(ath_change_str),
                        "logo_url": logo_url,
                    }
                )
            except (AttributeError, ValueError, KeyError):
                continue

    except requests.exceptions.RequestException as e:
        print(f"  -> Falha no CoinGecko: {e}")
        return []

    print(f"  -> Sucesso no CoinGecko! {len(assets_list)} moedas encontradas.")
    return assets_list
