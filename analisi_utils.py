"""Funzioni comuni ai notebook di analisi (fasi B-E del piano operativo)."""
import random
from pathlib import Path

import igraph as ig
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parent
JSONL = BASE / 'fragment_final.jsonl'
OUTPUT = BASE / 'analisi_output'
DATI = OUTPUT / 'dati'          # tabelle intermedie, escluse da git perche' troppo grandi
TABELLE = OUTPUT / 'tabelle'
FIGURE = OUTPUT / 'figure'
for cartella in (DATI, TABELLE, FIGURE):
    cartella.mkdir(parents=True, exist_ok=True)

LAYERS = ['usernames', 'phone_numbers']     # per i gift basta aggiungere il layer qui e in NOME, FILE e COLORI
NOME = {'usernames': 'Username', 'phone_numbers': 'Numeri', 'gifts': 'Gift'}
FILE = {'usernames': 'usernames', 'phone_numbers': 'numbers', 'gifts': 'gifts'}
VARIANTI = ['senza_contratti', 'completa']
NOME_VARIANTE = {'senza_contratti': 'senza contratti', 'completa': 'completa'}
SEED = 2026

# slot 1-3 della palette categoriale (validati su tutte le coppie); un layer gifts prende lo slot 4
COLORI = {'usernames': '#2a78d6', 'phone_numbers': '#eb6834', 'cross': '#1baf7a', 'gifts': '#eda100'}
GRIGIO, INK, SUPERFICIE, SECONDARIO = '#898781', '#0b0b0b', '#fcfcfb', '#52514e'


def stile():
    plt.rcParams.update({
        'figure.facecolor': SUPERFICIE, 'axes.facecolor': SUPERFICIE, 'savefig.facecolor': SUPERFICIE,
        'axes.edgecolor': '#c3c2b7', 'axes.linewidth': 0.8, 'axes.spines.top': False, 'axes.spines.right': False,
        'axes.grid': True, 'grid.color': '#e1e0d9', 'grid.linewidth': 0.8, 'grid.linestyle': '-', 'axes.axisbelow': True,
        'axes.labelcolor': SECONDARIO, 'xtick.color': GRIGIO, 'ytick.color': GRIGIO, 'text.color': INK,
        'axes.titlesize': 11, 'axes.titleweight': 'bold', 'axes.titlelocation': 'left', 'font.size': 9.5,
        'font.family': 'sans-serif', 'font.sans-serif': ['Helvetica Neue', 'Helvetica', 'Arial', 'DejaVu Sans'],
        'lines.linewidth': 2, 'lines.solid_capstyle': 'round', 'lines.solid_joinstyle': 'round',
        'legend.frameon': False, 'figure.dpi': 110,
    })
    pd.set_option('display.float_format', '{:.4g}'.format)
    pd.set_option('display.width', 220)
    pd.set_option('display.max_columns', 40)
    pd.set_option('display.max_colwidth', 60)


def salva_figura(fig, nome):
    fig.savefig(FIGURE / f'{nome}.png', dpi=200, bbox_inches='tight')


def salva_tabella(df, nome, **kwargs):
    df.to_csv(TABELLE / f'{nome}.csv', **kwargs)


def cartella_variante(variante):
    cartella = DATI / variante
    cartella.mkdir(exist_ok=True)
    return cartella


def carica_grafi(variante):
    # Un grafo diretto e pesato per layer. I nodi sono tutti i wallet della tabella wallet x layer,
    # anche quelli senza archi. Attributi: name (indirizzo), weight, n_distinct_nfts, n_vendite
    nodi = pd.read_parquet(cartella_variante(variante) / 'wallet_layer.parquet', columns=['wallet', 'layer'])
    G = {}
    for layer in LAYERS:
        archi = pd.read_parquet(cartella_variante(variante) / f'edges_{FILE[layer]}.parquet',
                                columns=['sender', 'recipient', 'n_transfers', 'n_distinct_nfts', 'n_vendite'])
        indice = pd.Index(nodi.loc[nodi.layer == layer, 'wallet'])
        coppie = np.c_[indice.get_indexer(archi.sender), indice.get_indexer(archi.recipient)]
        g = ig.Graph(n=len(indice), edges=coppie.tolist(), directed=True,
                     vertex_attrs={'name': indice.tolist()},
                     edge_attrs={'weight': archi.n_transfers.tolist(), 'n_distinct_nfts': archi.n_distinct_nfts.tolist(),
                                 'n_vendite': archi.n_vendite.tolist()})
        g['layer'] = layer
        G[layer] = g
    return G


def attivi(g):
    # Sottografo dei wallet con almeno un arco: le comunita' e le centralita' si calcolano qui
    return g.induced_subgraph(np.flatnonzero(np.array(g.degree()) > 0).tolist())


def non_orientato(g):
    # Rappresentazione usata per le comunita': non orientata, peso = somma dei passaggi nelle due direzioni
    return g.as_undirected(mode='collapse', combine_edges={'weight': 'sum', 'n_distinct_nfts': 'sum', 'n_vendite': 'sum'})


def z_score(osservato, nullo):
    nullo = np.asarray(nullo, dtype=float)
    m, s = nullo.mean(), nullo.std(ddof=1)
    return (osservato - m) / s if s > 0 else np.nan


def p_empirico(osservato, nullo):
    nullo = np.asarray(nullo, dtype=float)
    return (1 + np.sum(np.abs(nullo - nullo.mean()) >= abs(osservato - nullo.mean()))) / (1 + len(nullo))


def benjamini_hochberg(p):
    p = np.asarray(p, dtype=float)
    n = len(p)
    ordine = np.argsort(p)
    q = np.empty(n)
    q[ordine] = np.minimum.accumulate((p[ordine] * n / np.arange(1, n + 1))[::-1])[::-1]
    return np.minimum(q, 1)


def ccdf(x):
    # P(X >= k) per ogni valore distinto k
    x = np.sort(np.asarray(x))
    k, primo = np.unique(x, return_index=True)
    return k, 1 - primo / len(x)


def gini(x):
    x = np.sort(np.asarray(x, dtype=float))
    n = len(x)
    return (2 * np.arange(1, n + 1) - n - 1).dot(x) / (n * x.sum())


def leggibile(df):
    # Per mostrare a schermo tabelle che mischiano conteggi e quote
    fmt = lambda v: f'{int(v):,}'.replace(',', '.') if float(v).is_integer() and abs(v) >= 1 else f'{v:.3g}'
    return df.map(lambda v: fmt(v) if isinstance(v, (int, float, np.integer, np.floating)) and pd.notna(v) else v)


def corto(indirizzo):
    return indirizzo[:10] + '…'


def nullo_configurazione(g, seed):
    # Configuration model sui passaggi: ogni wallet tiene quanti NFT cede e riceve, cambiano le controparti.
    # I passaggi ripetuti tra la stessa coppia diventano il peso, i self-loop del modello si scartano
    random.seed(seed)
    h = attivi(g)
    n = ig.Graph.Degree_Sequence(h.strength(mode='out', weights='weight'), h.strength(mode='in', weights='weight'),
                                 method='configuration')
    n.vs['name'] = h.vs['name']
    n.es['weight'] = 1
    n.simplify(multiple=True, loops=True, combine_edges={'weight': 'sum'})
    return n


def modularita_louvain(u, seed):
    # Modularita' pesata della partizione di Louvain su un grafo non orientato
    random.seed(seed)
    return u.modularity(u.community_multilevel(weights='weight').membership, weights='weight')
