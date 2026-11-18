# Fragment multilayer: risultati dell'analisi

Riepilogo per la relazione (sezione 9 del piano operativo). Il dettaglio è nei notebook; figure e tabelle sono in `analisi_output/`.

## Come rieseguire

`fragment_final.jsonl` non è su git (2,4 GB): va in `dataset_network_final/`, dove lo crea `preprocessing/final_processing.ipynb`, oppure nella cartella principale. Le tabelle intermedie in `analisi_output/dati/` si rigenerano.

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m ipykernel install --prefix .venv --name cna --display-name "CNA (.venv)"
```

Ordine dei notebook: `fase_b_reti` → `fase_c_intra_layer` → `fase_d_inter_layer` → `fase_d_multilayer` → `fase_e_comportamento`. `fase_c_rete_completa` ripete lo studio intra-layer sulla rete completa e richiede solo `fase_b_reti`. Seed fissi; per aggiungere i gift si parte da `LAYERS` in `analisi_utils.py`.

## Metodi

- **Dati**: 3.406.889 azioni e 691.773 NFT (555.207 username, 136.566 numeri), dal 2 novembre 2022 al 22 ottobre 2026. Il dataset è usato così com'è. I conteggi coincidono con quelli di `preprocessing/final_processing.ipynb` (2.579.191 archi, 135.925 righe B → B).
- **Layer**: un grafo diretto per mercato. Lo stesso wallet è lo stesso nodo in ogni layer.
- **Archi**: regole di `descrizione_colonne_fragment_final.txt`. NULL → A crea solo il nodo, A → B crea l'arco, B → B non crea niente. Peso = numero di passaggi.
- **Due versioni della rete**:
  - `completa`: le regole applicate alle righe così come sono.
  - `senza_contratti` (riferimento, perché le ipotesi riguardano gli attori): si tolgono le righe con destinatario un contratto identificato, quindi A → contratto → B diventa A → B. Contratti identificati: 224.429 su 669.615 indirizzi, dalle etichette `is_wallet` del campione, dal controllo dei 100 indirizzi più attivi e da due regole strutturali. Sulle etichette note, i destinatari delle "fabbriche" di contratti sono contratti in 2.165 casi su 2.186 e lo schema dei noleggi in 935 su 935.
- **Possessi**: `COMPLETE` se conclusi, `INFERRED` se conclusi attraverso un contratto, `OPEN` se ancora in corso. Compaiono solo nei profili delle comunità, come mediana dei periodi conclusi.
- **Comunità**: Leiden con risoluzione 1 sul grafo non orientato pesato, con sensibilità a risoluzione, seed e Louvain.
- **Core**: wallet nel top 1% per forza in entrambi i layer. **Hub specialisti**: nel top 1% di un solo layer.
- **Senza modelli nulli**: i risultati sono descrittivi, senza confronto con modelli nulli né test di significatività. L'unica misura di incertezza è l'intervallo di confidenza bootstrap dello Spearman.

## Risultati

Rete senza contratti, salvo diversa indicazione.

### RQ1: struttura di ogni mercato

| | Username | Numeri |
|---|---|---|
| Wallet (con archi) | 346.133 (316.639) | 133.355 (124.438) |
| Passaggi | 1.470.602 | 610.955 |
| Componente gigante | 92% | 98% |
| Quota di forza del top 1% / 10% | 37% / 69% | 50% / 78% |
| Reciprocità | 0,18 | 0,17 |
| Clustering medio | 0,11 | 0,12 |
| Modularità di Leiden | 0,80 | 0,69 |

- Le due reti hanno la stessa forma: gradi a coda pesante e forte concentrazione.
- Gli hub dipendono dalla metrica e dai contratti. Confrontando per ogni metrica tanti wallet quanti hanno grado ≥ 100 (887 / 564), il Jaccard tra metriche va da 0,28 a 0,74. Nella rete completa 378 dei primi 887 wallet per PageRank degli username sono contratti, e il Jaccard del PageRank tra le due reti è 0,33 / 0,84.
- La struttura a gruppi è solida, le singole comunità molto meno. Con un altro seed l'ARI è 0,72 / 0,70, con un'altra risoluzione 0,42-0,50 / 0,31. Tra le 12 più grandi, negli username alcune restano quasi uguali (per esempio quella delle parole di dizionario, Jaccard 0,91 con altri seed) e altre no; nei numeri il Jaccard mediano con altri seed è circa 0,6.
- Alcune comunità hanno un profilo chiaro. Negli username una è arricchita di circa 16 volte in parole di dizionario, con prezzo mediano di 49 TON contro 6-8 della maggior parte delle altre. Nei numeri il prezzo mediano delle grandi comunità va da 32 a 860 TON. In alcune comunità un solo wallet tocca gran parte dei passaggi interni (fino all'84% nei numeri): lì il profilo può riflettere quel wallet.

**Rete completa** (`fase_c_rete_completa`, tabelle `c_completa_*`): lo stesso studio senza separare wallet e contratti.

| | Username | Numeri |
|---|---|---|
| Nodi | 554.965 (346.133) | 149.031 (133.355) |
| Reciprocità | 0,42 (0,18) | 0,18 (0,17) |
| Quota di forza del top 1% | 36% (37%) | 51% (50%) |
| Comunità / modularità | 22.508 / 0,84 (9.402 / 0,80) | 1.649 / 0,71 (1.564 / 0,69) |

Tra parentesi la rete senza contratti.
- Nei numeri non cambia quasi niente.
- Negli username i contratti raddoppiano la reciprocità (andata e ritorno di noleggi e annunci) e formano una grande comunità con possesso mediano di poche ore e il 6% di vendite.
- Restano uguali la concentrazione, il disaccordo tra metriche sugli hub (Jaccard 0,18-0,78, con 945 / 592 wallet di grado ≥ 100) e la comunità delle parole di dizionario (prezzo mediano 43 TON).

Figure: `c_gradi_e_concentrazione`, `c_arricchimento_heatmap`, `c_profili_comunita`.

### RQ2: persistenza tra i mercati

- 34.302 wallet (7,7%) sono in entrambi i mercati, ma generano il 32% degli eventi degli username e il 57% di quelli dei numeri.
- Spearman della forza: 0,35 (IC 95% 0,34-0,36) sui wallet con archi in entrambi; 0,27 con le sole vendite.
- Comunità: ARI 0,09, NMI 0,27. Le comunità dei due mercati si somigliano poco: anche le coppie di comunità grandi condividono al massimo il 10-20% dei wallet.
- Comunità inter-layer: 74 coppie di comunità sono la stessa nei due mercati (Jaccard ≥ 0,5 sulle comunità intere), per 257 wallet. Sono 48 coppie di wallet, 9 catene in cui un solo username e un solo numero passano tra gli stessi wallet (fino a 39, le più grandi tra gennaio e febbraio 2024) e 17 gruppi chiusi da 3 a 11 wallet che si scambiano NFT senza vendite, spesso nella stessa ora nei due mercati. Nessuno di questi wallet è un hub: sono tutti fuori dal top 1% e hanno al massimo 11 archi. Tabella `d_comunita_speculari`.
- **Comunità multilayer sovrapposte** (`fase_d_multilayer`): comunità calcolate sui due mercati insieme, con un wallet che può stare in più comunità (ego-splitting e Leiden multiplex, peso uguale ai due mercati). Sono 36.846: 25.785 solo username, 5.627 solo numeri, 5.079 inter-layer con gli stessi wallet (quasi tutte piccole; ci sono 72 delle 74 speculari) e 355 **gruppi grandi** con wallet diversi nei due mercati, tenuti insieme da wallet attivi in entrambi. I gruppi grandi contengono 228 dei 234 wallet del core. Sono di due tipi: **mercato aperto** (il più grande ha 19.236 wallet, il 69% / 63% dei passaggi interni sono vendite, NFT comuni) e **asset di pregio senza vendite** (dall'1% al 15% di vendite, username di 4 lettere da 3 a 17 volte e numeri con cifre ripetute da 2 a 8 volte più frequenti che nel mercato). Nei gruppi di pregio username rari e numeri rari si muovono insieme: tra i 39 gruppi con abbastanza NFT, quelli con più username rari hanno più numeri rari (Spearman 0,39), e le categorie più legate sono parole di dizionario con numeri a cifre ripetute e username di 4 lettere con numeri ABCDABCD (0,56). I gruppi si specializzano in un livello di qualità, non in un tema. Tutti i wallet del core stanno in più comunità (mediana 7). Tabelle `d_multilayer_*`.
- Coppie collegate in entrambi i layer: 14.058, ma solo 486 con le sole vendite. I legami condivisi sono quasi tutti trasferimenti senza prezzo.

Figure: `d_overlap_nodi`, `d_top_actor_overlap`, `d_rank_correlation`, `d_community_overlap`, `d_multilayer_gruppi_grandi`, `d_multilayer_categorie`, `d_multilayer_mappa`, `d_multilayer_esempio`, `d_multilayer_coppie_categorie`.

### H1 e H2

Senza modelli nulli le due ipotesi sono descritte, non testate.

- **H1: esiste un gruppo di wallet molto attivi in entrambi i mercati.** Sono 234 nel top 1% di entrambi i mercati; 321 nella rete completa e 64 con le sole vendite. Generano il 4,9% dei passaggi degli username e il 13,8% di quelli dei numeri. Non è stato misurato se siano collegati tra loro o al centro della rete, quindi non si può parlare di nucleo strutturale.
- **H2: gli influenti sono soprattutto specialisti.** Gli hub specialisti sono 3.942 contro 234 wallet del core (94%). Il 93% dei wallet con archi concentra almeno il 92% della propria attività in un solo mercato (P < 0,3). Ai vertici la sovrapposizione è minima: per forza 0 su 10 e 4 su 100. Il dato riguarda i wallet: una persona con un wallet per mercato risulta specialista.

Figure: `d_top_actor_overlap`, `d_partecipazione`.

### RQ3: comportamento

Rimane solo l'evoluzione: quando i wallet presenti in entrambi i mercati entrano nel secondo. Attività, possesso, preferenze, ruoli ed economia sono stati tolti.

| Gruppo | Wallet | Ritardo mediano (giorni) | Entro 30 giorni | Prima gli username |
|---|---|---|---|---|
| Core | 234 | 10 | 72% | 53% |
| Hub specialisti username | 1.054 | 32 | 49% | 78% |
| Hub specialisti numeri | 599 | 16 | 60% | 25% |
| Cross-layer | 32.415 | 15 | 59% | 46% |

- Il core entra nel secondo mercato prima degli altri gruppi e non ha un mercato di partenza. Gli hub specialisti sono entrati quasi sempre prima nel mercato in cui sono hub.
- È una sequenza temporale, non un rapporto di causa; il ritardo dipende anche dall'attività del wallet.

**In sintesi**: Fragment non è fatto di mercati separati, ma nemmeno di un ecosistema guidato da un solo gruppo di attori. Esiste un piccolo gruppo di wallet molto attivi in entrambi i mercati, accanto a molti specialisti, e la maggior parte dei wallet resta in un solo mercato.

Figura: `e_evoluzione`.

## Limiti

- Un wallet non è necessariamente una persona, e la stessa persona può avere più wallet.
- L'81% dei passaggi degli username e il 65% di quelli dei numeri non ha un prezzo. Il prezzo assente non vuol dire regalo.
- L'elenco dei contratti è parziale: non tutti i contratti minori sono stati riconosciuti.
- I prezzi compaiono solo come mediane, nei profili delle comunità, perché nel file finale ci sono prezzi anomali (per esempio 14 vendite di numeri da oltre 1 milione di TON). Riguardano solo i passaggi tra wallet: le vendite primarie, quasi sempre a 10 TON negli username, sono escluse.
- Nessun risultato è confrontato con un modello nullo: non si può dire quanto ciascuno superi il caso, né separare gli effetti dell'attività da quelli del gruppo.
- Le sequenze temporali non indicano un rapporto di causa.

## Non fatto

- **Gift**: il dataset non è ancora disponibile.
- **Struttura del core**: k-core multilayer e rich-club, per capire se i wallet del core formano un nucleo collegato.
- **Link prediction**: facoltativa nel piano.
