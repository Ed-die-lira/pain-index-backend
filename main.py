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


def calculate_pain_score(percent_from_ath: float) -> int:
    """Calcula o Pain Score com base na queda do ATH."""
    score = 0
    # Aumenta a dor exponencialmente quanto maior a queda
    if percent_from_ath < -50:
        score = int(abs(percent_from_ath) * 0.9)
    if percent_from_ath < -80:
        score = int(abs(percent_from_ath) * 1.0)
    if percent_from_ath < -95:
        score = int(abs(percent_from_ath) * 1.05)  # Bônus para capitulação total

    return min(score, 100)  # Limita o score a 100


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
    for item in raw_data:
        asset = Asset(
            rank=0,  # O rank será definido após a ordenação
            id=f"{item['name'].lower().replace(' ', '-')}-{item['symbol'].lower()}",
            name=item["name"],
            symbol=item["symbol"],
            price=item["price"],
            percent_from_ath=item["percent_from_ath"],
            pain_score=calculate_pain_score(item["percent_from_ath"]),
            logo_url=item["logo_url"],
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
