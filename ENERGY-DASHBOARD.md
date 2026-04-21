# Energy Dashboard — Boiler "notte" tracking

Spiegazione del calcolo corrente del consumo elettrico del boiler Ariston
Velis ("boiler notte") nella Energy Dashboard di Home Assistant.

---

## Problema risolto

La Energy Dashboard mostrava barre **negative** sotto "Consumo non
tracciato" in corrispondenza dei cicli del boiler.

Causa: il sensore cloud
`sensor.ariston_domestic_hot_water_total_energy_consumption_2` usato
come "Boiler zona notte" nella dashboard ha tre comportamenti che
rompono il calcolo dell'untracked:

1. **Non monotonico**: lo stato va da `0` → `X kWh` a fine ciclo, poi
   torna a `0` prima del ciclo successivo. HA lo gestisce come
   statistica `TOTAL` con `last_reset`, accumulando correttamente nel
   `sum` cumulativo ma attribuendo ogni delta a una sola ora.
2. **Pubblicazione ritardata**: il cloud Ariston pubblica il dato
   cumulativo del ciclo ~2 ore dopo l'inizio del ciclo.
3. **Misura energia termica, non elettrica**: dal confronto con il
   meter Shelly a monte, il valore Ariston è circa il 50% del consumo
   elettrico reale (probabile unità di misura termica utile).

Effetto combinato: un'intera ora di `sum` del boiler viene attribuita
a una singola ora — spesso dopo che il ciclo è terminato — mentre la
grid misurata da Shelly distribuisce il consumo reale nelle ore in cui
il boiler ha effettivamente riscaldato. Risultato: per quell'ora la
somma dei device tracciati supera la grid, e l'untracked diventa
negativo.

---

## Nuovo calcolo

### Principio

Il consumo elettrico del boiler viene **stimato** in tempo reale a
partire dal meter generale (Shelly Pro EM50 canale 0). Il segnale è
chiamato **"Boiler notte estimated power"** per evidenziare che si
tratta di una stima derivata, non di una misura diretta.

Durante i cicli di riscaldamento viene calcolato come:

```
boiler_W = max(
    grid_W - Σ(other_power_sensors_W) - baseline_W ,
    0
)
```

dove `Σ(other_power_sensors_W)` **non è una lista fissa** ma viene
derivata al volo da Home Assistant iterando tutte le entità
`sensor.*` con `device_class: power` ed escludendo una piccola lista
di helper interni:

- `sensor.energy_meter_0_power` (la grid stessa, che è il minuendo)
- `sensor.boiler_notte_estimated_power` (il sensore stesso,
  anti-feedback)
- `sensor.untracked_power_while_boiler_off` (helper intermedio)
- `sensor.untracked_baseline_while_boiler_off` (helper statistics)

Di conseguenza **aggiungere un nuovo sensore di potenza** (nuova presa
smart, canale EM, Shelly plug) lo include automaticamente nella
sottrazione, senza toccare la configurazione. Se l'entità nuova espone
`device_class: power` viene presa in carico al prossimo cambio di
stato, senza restart HA.

Il termine `baseline_W` è la media mobile del consumo **non tracciato**
misurato mentre il boiler era **spento** (finestra di 6 ore, calcolata
dal sensore built-in HA `statistics` a partire dal template intermedio
`sensor.untracked_power_while_boiler_off`).

Un helper di integrazione Riemann trasforma il segnale di potenza (W)
in un contatore cumulativo di energia (kWh) monotonico, nel sensore
`sensor.boiler_notte_estimated_energy`, compatibile con la Energy
Dashboard.

### Cosa cattura la baseline

Carichi "di fondo" sostanzialmente costanti con boiler acceso o
spento:

- Frigo (media del duty cycle)
- Router, switch di rete, access point
- Consumi standby di TV, decoder, caricabatterie
- Illuminazione LED always-on

Questi carichi **non** vengono più attribuiti al boiler.

### Cosa NON cattura la baseline

Carichi non tracciati che si accendono o si spengono **in coincidenza**
con un ciclo boiler (es. climatizzatore che parte a inizio ciclo)
continuano a essere attribuiti al boiler per la durata del ciclo.
L'unica mitigazione è installare un sensore di potenza (presa smart,
canale EM) sul dispositivo "colpevole". Grazie all'iterazione
dinamica di `states.sensor` nel template, il nuovo sensore viene
automaticamente incluso nella sottrazione senza modifiche al file
`configuration.yaml`.

### Proprietà matematica

Per costruzione:

```
boiler_kWh  ≤  grid_kWh - Σ(other_tracked_kWh)
```

Quindi:

```
untracked  =  grid_kWh - Σ(all_tracked_kWh)
           =  grid_kWh - [boiler_kWh + Σ(other_tracked_kWh)]
           ≥  0
```

La barra "Consumo non tracciato" **non può** diventare negativa a
causa di questa stima.

### Cold start

All'avvio di HA il sensore `statistics` della baseline parte da
`unknown` finché non accumula un numero sufficiente di campioni con
boiler spento. In quel caso il template fa fallback a `0` tramite
`float(0)` e usa la formula grid - tracciati (senza sottrazione
baseline). Safe default: il boiler risulta leggermente sovrastimato
per pochi minuti dopo un restart, ma la dashboard resta consistente.

### Vantaggi rispetto ad altre alternative

- **Zero costanti fisse**: niente potenza nominale stimata, niente EMA
  empirico, niente soglie stagionali.
- **Misurazione reale**: Shelly misura elettroni veri, la stima
  riflette il mix attivo (resistenza vs pompa di calore) in
  automatico.
- **Auto-adattiva nel tempo**: la baseline si ricalcola continuamente
  sulla finestra di 6 ore, segue le variazioni del consumo di base
  (stagione, cambio abitudini, nuovi dispositivi).
- **Auto-adattiva alle entità**: lista dei sensori di potenza da
  sottrarre generata dinamicamente. Aggiungere un nuovo device
  monitorato (presa smart, canale EM) non richiede modifiche al file
  di configurazione.
- **Robusta a outage cloud**: se `binary_sensor.ariston_is_heating_2`
  va in `unavailable`, la potenza stimata cade a `0` (fail-safe).
- **Distribuzione oraria proporzionale** al tempo di riscaldamento
  effettivo, non all'istante di pubblicazione del dato cloud.

### Caveat noti

- La stima riflette il **mix elettrico reale**, che è più alto del
  valore termico riportato dal sensore cloud Ariston (rapporto ~2x
  nel nostro caso). La nuova cifra è quella corretta per la bolletta.
- Come sopra, carichi non tracciati attivi **solo durante** i cicli
  boiler rimangono assorbiti nella stima. Tracciare quei dispositivi
  è l'unica mitigazione.
- La finestra `max_age` del sensore statistics è fissata a 6 ore. Se
  ci sono periodi >6h di boiler continuamente acceso (raro: i cicli
  tipici durano 30-110 min), la baseline diventerebbe `unknown` e il
  sensore fallback a 0. Non problematico per l'uso tipico.

---

## Entità esposte

| Entità | Tipo | Scopo |
|--------|------|-------|
| `sensor.untracked_power_while_boiler_off` | template | Potenza non tracciata esposta solo quando boiler spento. Sorgente della baseline |
| `sensor.untracked_baseline_while_boiler_off` | statistics | Media mobile 6h della precedente. È la "baseline" |
| `sensor.boiler_notte_estimated_power` | template | **Stima istantanea** potenza elettrica boiler (W) |
| `sensor.boiler_notte_estimated_energy` | integration | **Stima cumulativa** energia elettrica boiler (kWh) — entità da usare nella Energy Dashboard |

---

## Modifiche al repository

File toccati:

| File | Modifica |
|------|----------|
| `homeassistant/.gitignore` | Autorizza il tracking di `configuration.yaml` (prima l'intera directory era ignorata). |
| `homeassistant/configuration.yaml` | **Nuovo nel repo.** Copia della configurazione in produzione con l'aggiunta dei blocchi descritti sopra. |

Tutte le costanti runtime di HA (`.storage`, database recorder, log,
custom components, ecc.) restano git-ignored.

---

## Deploy

Lo stato di produzione coincide con `main`. Per applicare future
modifiche alla configurazione di HA:

```bash
# 1. modifica configuration.yaml nel repo, commit, push
git add homeassistant/configuration.yaml
git commit -m "..."
git push origin main

# 2. apply su mulo
ssh mulo 'cd /srv/docker && git pull && docker compose restart homeassistant'
```

Validazione pre-deploy (consigliata per cambi non banali):

```bash
ssh mulo 'docker exec homeassistant hass --script check_config -c /config'
```

Restituisce exit code `0` se la configurazione è valida, senza toccare
lo stato runtime.

---

## Step UI una-tantum

La configurazione della Energy Dashboard (scelta delle entità da
mostrare) vive in `.storage/energy`, **non** è YAML-trackable via git.
Dopo il deploy è richiesto un passaggio manuale:

1. **Impostazioni → Dashboard Energia → Consumi individuali**
2. Voce "Boiler zona notte" → **Modifica** (matita)
3. Cambiare il sensore in
   `sensor.boiler_notte_estimated_energy`
4. **Salva**

Da quel momento la dashboard usa il nuovo calcolo.

---

## Rollback

```bash
git revert <commit-hash>
git push origin main
ssh mulo 'cd /srv/docker && git pull && docker compose restart homeassistant'
```

Poi da UI reimpostare il sensore Ariston originale sulla dashboard.
