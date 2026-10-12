"""Uso: python unisci_categorie.py dataset.csv usernames_categories.csv output.csv [colonna_username] [--senza-intestazione]

Aggiunge al dataset UNA colonna "categories" con la lista (JSON) delle categorie dell'username,
es. ["5 Letters", "5 Letters Palindrome"]; ["No_Categories"] se non ne ha nessuna. Le categorie sono:
  1) categorie "da elenco": l'username e' presente in usernames_categories.csv
  2) categorie "da regex": N Letters (4-10) e N Letters Palindrome (5-10), calcolate sul nome
     (lettere a-z, numeri 0-9 e underscore - gli unici caratteri ammessi in uno username Telegram/Fragment)
Le due fonti si combinano (basta una per avere 1). Nell'output la colonna username ha sempre la '@'.
colonna_username: nome o numero (0 = prima). Default: 2 (la terza)."""
import re, sys, pandas as pd

args = [a for a in sys.argv[1:] if not a.startswith("--")]
senza_head = "--senza-intestazione" in sys.argv
dati, cats, out = args[:3]
col = args[3] if len(args) > 3 else "2"

CHARSET = "a-z0-9_"   # unici caratteri ammessi in uno username Telegram/Fragment

def regex_palindromo(n):
    meta = n // 2
    parti = "".join(f"([{CHARSET}])" for _ in range(meta))
    centro = f"[{CHARSET}]" if n % 2 else ""
    rif = "".join(f"\\{i}" for i in range(meta, 0, -1))
    return re.compile(f"^{parti}{centro}{rif}$")

REGEX = {}
for n in range(4, 11):
    REGEX[f"{n} Letters"] = re.compile(f"^[{CHARSET}]{{{n}}}$")
for n in range(5, 11):
    REGEX[f"{n} Letters Palindrome"] = regex_palindromo(n)

df = pd.read_csv(dati, header=None if senza_head else "infer", dtype=str)
col = df.columns[int(col)] if col.isdigit() else col
pulito = df[col].str.strip().str.lstrip("@").str.lower()
orig = df[col]
df[col] = orig.where(orig.str.startswith("@"), "@" + orig.str.strip())   # username originale invariato; aggiunge la @ solo se manca

cat = pd.read_csv(cats, dtype={"usernames": str}).drop_duplicates("usernames").set_index("usernames")
elenco = cat.reindex(pulito.values).fillna(0).astype(int)
elenco.index = df.index
for nome, rx in REGEX.items():                           # regex: OR con l'elenco
    r = pulito.map(lambda u: int(bool(rx.match(u))))
    elenco[nome] = (elenco[nome] | r) if nome in elenco else r

import json
df["categories"] = [json.dumps([c for c in elenco.columns if riga[c] == 1] or ["No_Categories"], ensure_ascii=False)
                    for _, riga in elenco.iterrows()]
df.columns = ["" if str(c).startswith("Unnamed: ") else c for c in df.columns]   # mantiene vuoto il nome della colonna indice
df.to_csv(out, index=False)
print(f"{len(df)} righe -> {out}")
print("Righe senza categoria:", int(df["categories"].apply(lambda c: c == '["No_Categories"]').sum()))