import time
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional

# Importa nossas funções de scraping do outro arquivo
from providers import scrape_coinmarketcap, scrape_coingecko


# --- Modelo Pydantic para validação final ---
class Asset(BaseModel):
    rank: int
    id: str
    name: str
    symbol: str
    price: float
    percent_from_ath: float
    pain_score: int
    logo_url: str


# --- Cache ---
cached_data: Optional[List[Asset]] = None
last_cache_time: float = 0
CACHE_DURATION_SECONDS = 60 * 15  # Cache de 15 minutos


def calculate_pain_score(quote: dict) -> int:
    """
    Calcula o Pain Score com base em múltiplos fatores de tempo.
    `quote` é o dicionário de cotação do ativo (ex: quote['USD']).
    """
    # Pega as variações de preço. Se não existirem, o padrão é 0.
    change_24h = quote.get("percentChange24h", 0.0)
    change_7d = quote.get("percentChange7d", 0.0)
    change_30d = quote.get("percentChange30d", 0.0)

    # Define os pesos para cada período de tempo
    weight_24h = 0.50  # Dor imediata (50% do peso)
    weight_7d = 0.30  # Dor na semana (30% do peso)
    weight_30d = 0.20  # Dor no mês (20% do peso)

    # Calcula a "dor" para cada período (só nos importamos com quedas)
    pain_24h = abs(change_24h) if change_24h < 0 else 0
    pain_7d = abs(change_7d) if change_7d < 0 else 0
    pain_30d = abs(change_30d) if change_30d < 0 else 0

    # Fórmula do Score: Média ponderada da dor, com um multiplicador para amplificar o resultado
    # O multiplicador (ex: 2.5) é ajustado para que scores altos (80-100) sejam possíveis em quedas fortes.
    raw_score = (
        pain_24h * weight_24h + pain_7d * weight_7d + pain_30d * weight_30d
    ) * 2.5

    # Adiciona um "bônus de pânico" se a queda diária for muito grande
    if pain_24h > 10:  # Se caiu mais de 10% em um dia
        raw_score += 15
    if pain_24h > 20:  # Se caiu mais de 20%
        raw_score += 10  # Bônus adicional

    # Garante que o score final fique entre 0 e 100
    final_score = min(int(raw_score), 100)

    return final_score


def get_data_from_providers() -> List[Asset]:
    """Tenta buscar dados de múltiplos provedores em ordem."""

    # Lista de provedores a serem tentados, em ordem de preferência
    provider_functions = [
        scrape_coinmarketcap,
        scrape_coingecko,
        # Adicione mais funções de provedores aqui no futuro
    ]

    raw_data = []
    for provider in provider_functions:
        raw_data = provider()
        if raw_data:  # Se o provedor retornou dados com sucesso...
            break  # ...paramos de tentar outros.

    if not raw_data:
        print("Todos os provedores falharam. Retornando lista vazia.")
        return []

    # Processa os dados brutos e transforma em nossa estrutura final 'Asset'
    assets_list = []
    for coin_item in raw_data:
        quote_data = coin_item.get("quote_usd", {})

        asset = Asset(
            rank=0,
            id=f"{coin_item['name'].lower().replace(' ', '-')}-{coin_item['symbol'].lower()}",
            name=coin_item["name"],
            symbol=coin_item["symbol"],
            price=quote_data.get("price", 0.0),
            # Na UI, vamos continuar mostrando a variação de 24h por enquanto
            percent_from_ath=quote_data.get("percentChange24h", 0.0),
            # A função de cálculo agora recebe o dicionário de cotação completo
            pain_score=calculate_pain_score(quote_data),
            logo_url=coin_item["logo_url"],
        )
        assets_list.append(asset)

    # Ordena a lista final pelo maior Pain Score
    sorted_assets = sorted(assets_list, key=lambda x: x.pain_score, reverse=True)

    # Reatribui o rank baseado na dor
    for i, asset in enumerate(sorted_assets):
        asset.rank = i + 1

    return sorted_assets


# --- Configuração do FastAPI ---
app = FastAPI()

origins = ["http://localhost:3000"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Endpoint da API com Cache e Provedores em Cascata ---
@app.get("/api/leaderboard", response_model=List[Asset])
def get_leaderboard():
    global cached_data, last_cache_time

    current_time = time.time()
    if not cached_data or (current_time - last_cache_time) > CACHE_DURATION_SECONDS:
        print("Cache expirado. Buscando novos dados dos provedores...")
        cached_data = get_data_from_providers()
        last_cache_time = current_time
    else:
        print("Retornando dados do cache.")

    return cached_data
