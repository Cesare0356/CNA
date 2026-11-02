# Fragment multilayer: risultati dell'analisi

Riepilogo per la relazione (sezione 9 del piano operativo). Il dettaglio è nei notebook; figure e tabelle sono in `analisi_output/`.

## Come rieseguire

`fragment_final.jsonl` non è su git (2,4 GB): va in `dataset_network_final/`, dove lo crea `preprocessing/final_processing.ipynb`, oppure nella cartella principale. Le tabelle intermedie in `analisi_output/dati/` si rigenerano.

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m ipykernel install --prefix .venv --name cna --display-name "CNA (.venv)"
```

Ordine dei notebook: `fase_b_reti` → `fase_c_intra_layer` → `fase_d_inter_layer` → `fase_e_comportamento`. Seed fissi; per aggiungere i gift si parte da `LAYERS` in `analisi_utils.py`.

## Metodi

- **Dati**: 3.406.889 azioni e 691.773 NFT (555.207 username, 136.566 numeri), dal 2 novembre 2022 al 22 ottobre 2026. Il dataset è usato così com'è. I conteggi coincidono con quelli di `preprocessing/final_processing.ipynb` (2.579.191 archi, 135.925 righe B → B).
- **Layer**: un grafo diretto per mercato. Lo stesso wallet è lo stesso nodo in ogni layer.
- **Archi**: regole di `descrizione_colonne_fragment_final.txt`. NULL → A crea solo il nodo, A → B crea l'arco, B → B non crea niente. Peso = numero di passaggi.
- **Due versioni della rete**:
  - `completa`: le regole applicate alle righe così come sono.
  - `senza_contratti` (riferimento, perché le ipotesi riguardano gli attori): si tolgono le righe con destinatario un contratto identificato, quindi A → contratto → B diventa A → B. Contratti identificati: 224.429 su 669.615 indirizzi, dalle etichette `is_wallet` del campione, dal controllo dei 100 indirizzi più attivi e da due regole strutturali. Sulle etichette note, i destinatari delle "fabbriche" di contratti sono contratti in 2.165 casi su 2.186 e lo schema dei noleggi in 935 su 935.
- **Possessi**: `COMPLETE` se conclusi, `INFERRED` se conclusi attraverso un contratto, `OPEN` se ancora in corso (censurati con Kaplan-Meier).
- **Comunità**: Leiden con risoluzione 1 sul grafo non orientato pesato, con sensibilità a risoluzione, seed e Louvain.
- **Core**: wallet nel top 1% per forza in entrambi i layer. **Hub specialisti**: nel top 1% di un solo layer.
- **Validazione** (lezione 8): configuration model per reciprocità, clustering, modularità ed edge overlap; rimescolamento delle identità e delle etichette per overlap, comunità e categorie; z-score, p-value e correzione di Benjamini-Hochberg.

## Risultati

Rete senza contratti, salvo diversa indicazione.

### RQ1: struttura di ogni mercato

| | Username | Numeri |
|---|---|---|
| Wallet (con archi) | 346.133 (316.639) | 133.355 (124.438) |
| Passaggi | 1.470.602 | 610.955 |
| Componente gigante | 92% | 98% |
| Quota di forza del top 1% / 10% | 37% / 69% | 50% / 78% |
| Reciprocità (nullo) | 0,18 (0,02) | 0,17 (0,05) |
| Modularità di Louvain (nullo) | 0,80 (0,26) | 0,68 (0,23) |

- Le due reti hanno la stessa forma: gradi a coda pesante, forte concentrazione, struttura che i gradi da soli non spiegano.
- Gli hub dipendono dalla metrica (Jaccard dei top 100 tra metriche 0,19-0,74) e dai contratti (per il PageRank, Jaccard 0,49 / 0,77 tra le due reti).
- Le comunità grandi sono affidabili, i confini di dettaglio meno (NMI con un altro seed 0,83 / 0,70).
- Alcune comunità hanno un profilo chiaro. Negli username una è arricchita di circa 16 volte in parole di dizionario, con prezzo mediano di 49 TON contro 6-8 della maggior parte delle altre. Nei numeri il prezzo mediano delle grandi comunità va da 32 a 860 TON.

Figure: `c_gradi_e_concentrazione`, `c_arricchimento_heatmap`, `c_profili_comunita`.

### RQ2: persistenza tra i mercati

- 34.302 wallet (7,7%) sono in entrambi i mercati, ma generano il 32% degli eventi degli username e il 57% di quelli dei numeri.
- Spearman della forza: 0,35 (IC 95% 0,34-0,36) sui wallet con archi in entrambi; 0,27 con le sole vendite.
- Comunità: ARI 0,09, NMI 0,27 (nullo 0 e 0,13). Si somigliano più del caso, ma non sono le stesse.
- Coppie collegate in entrambi i layer: 14.058 contro 1.260 attese, ma solo 486 con le sole vendite. I legami condivisi sono quasi tutti trasferimenti senza prezzo.

Figure: `d_overlap_nodi`, `d_top_actor_overlap`, `d_rank_correlation`, `d_community_overlap`.

### H1 e H2

- **H1 è supportata.** Esiste un core oltre il caso: 234 wallet contro 13 attesi con identità casuali e 34 tra i soli wallet condivisi (z 62 e 35). Regge nella rete completa (321) e con le sole vendite (64, contro 10,7 attesi tra i wallet condivisi). Genera il 4,9% dei passaggi degli username e il 13,8% di quelli dei numeri.
- **H2 è supportata.** Gli influenti sono soprattutto specialisti: 3.942 hub specialisti contro 234 wallet del core (94%), e il 93% dei wallet con archi concentra almeno il 92% della propria attività in un solo mercato (coefficiente di partecipazione P < 0,3). Ai vertici assoluti la sovrapposizione è minima: per forza 0 su 10 e 4 su 100.

Figura: `d_partecipazione`.

### RQ3: comportamento

A parità di attività e anno di ingresso (`analisi_output/tabelle/e_test_a_parita_di_attivita.csv`).

| Confronto | Differenze principali |
|---|---|
| Core contro hub specialisti | più controparti (circa 1,4 volte), possessi più brevi (circa 2/3); negli username prezzi incassati più alti (circa 3,3 volte), prezzi primari più alti (circa 2,2 volte) e più NFT rari (+6,8 punti). Nessuna differenza significativa nel prezzo pagato sul secondario, né nei prezzi dei numeri |
| Cross-layer contro specialisti | possessi più lunghi (circa 1,6 volte), prezzi pagati sul secondario più alti (circa 1,3 e 1,2 volte), prezzi incassati più alti (circa 1,5 e 1,2 volte), meno passaggi senza prezzo (−5,8 punti), più NFT rari, meno scambi con altre comunità |

- Possesso mediano con i periodi aperti (Kaplan-Meier): nei numeri 1,5 giorni per il core, 22 per gli hub specialisti, 88 per i cross-layer, 169 per gli specialisti; negli username 13, 13, 290, 29.
- Il core entra subito nel secondo mercato (mediana 10 giorni), mantiene la stessa posizione nei due layer (differenza mediana di percentile 0,005 contro 0,21 dei cross-layer) e ha più scambi verso altre comunità.

**In sintesi**: Fragment non è fatto di mercati separati, ma nemmeno di un ecosistema guidato da un solo gruppo di attori. Esiste un piccolo core reale e riconoscibile accanto a molti specialisti, e la maggior parte dei wallet resta in un solo mercato.

Figure: `e_attivita`, `e_economia`, `e_possesso_km`, `e_evoluzione`, `e_ruoli_bridging`.

## Limiti

- Un wallet non è necessariamente una persona, e la stessa persona può avere più wallet.
- L'81% dei passaggi degli username e il 65% di quelli dei numeri non ha un prezzo. Il prezzo assente non vuol dire regalo.
- L'elenco dei contratti è parziale: non tutti i contratti minori sono stati riconosciuti.
- I prezzi sono presi dal file finale, quindi si usano le mediane e i volumi non vanno interpretati come profitti. Ci sono prezzi anomali da verificare: 14 vendite di numeri da oltre 1 milione di TON, tra febbraio e aprile 2025, valgono il 55% del volume secondario dei numeri; 2 vendite valgono il 19% di quello degli username.
- Le vendite primarie sono il 66% degli acquisti degli username, quasi sempre a 10 TON, e sono analizzate a parte. Nei numeri il prezzo primario c'è solo per 5.488 NFT su 136.566.
- Con questi numeri quasi tutto è statisticamente significativo: contano le dimensioni delle differenze. Con 200 permutazioni il p-value minimo è 0,005.
- Le sequenze temporali non indicano un rapporto di causa.

## Non fatto

- **Gift**: il dataset non è ancora disponibile.
- **Multilayer community detection e link prediction**: facoltative nel piano.
