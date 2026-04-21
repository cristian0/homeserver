# Boiler giorno — schedule dedicato

Spiegazione dell'automazione di controllo del boiler dumb della zona
giorno, comandato tramite la presa smart TP-Link Tapo
`switch.boiler_giorno`.

---

## Problema risolto

Fino a questo commit la presa del boiler giorno era pilotata da due
automazioni "mirror 1:1" (`boiler giorno on` / `boiler giorno off`) che
seguivano esattamente il sensore `binary_sensor.ariston_is_heating_2`
del boiler notte: quando il boiler notte riscaldava, la presa era ON;
appena si fermava, OFF. La logica era semplice da scrivere ma aveva
tre problemi:

1. **Finestra troppo corta per il tank**. I cicli del boiler notte in
   modalità `PROGRAM` durano in media ~42 min. Con un tank da 80 L e
   una resistenza da 1200 W quei 42 min scaldano l'acqua di appena
   ~9 °C, quindi il termostato meccanico interno del boiler giorno
   quasi mai raggiunge il setpoint. Risultato: la resistenza resta
   accesa per tutta la finestra (~1.68 kWh/giorno di consumo pieno)
   senza portare il tank a temperatura confortevole.
2. **Orari sfalsati rispetto all'uso**. Il ciclo serale del boiler
   notte termina intorno alle 18:42, mentre l'uso reale dell'acqua
   calda in zona giorno (cena, lavaggio stoviglie / mani) è verso le
   19:30-20:30. Il tank passava ~1 h in standby perdendo calore
   prima del primo prelievo.
3. **Accoppiamento indebito**. Qualunque variazione futura dello
   schedule del boiler notte (es. solo doccia serale) avrebbe
   trascinato con sé anche la zona giorno, senza alcuna motivazione
   funzionale.

L'uso reale della zona giorno è basso (lavaggio viso la mattina
07:00-08:00, acqua cena 19:30-20:30, totale ~10-15 L/giorno di acqua
tiepida), quindi il costo fisso della presa accesa dominava il
consumo utile.

---

## Nuovo schema

### Principio

Decouple completo dal boiler notte: la presa giorno viene accesa e
spenta secondo due finestre fisse basate sull'orario reale d'uso,
dimensionate sul tempo di warm-up del tank.

- **Finestra mattina**: `ON` 05:30 → `OFF` 07:00 (90 min)
- **Finestra sera**:    `ON` 18:00 → `OFF` 19:30 (90 min)

Lo spegnimento coincide con l'inizio della finestra di utilizzo in
modo che al primo prelievo il tank sia al punto più caldo, e il
raffreddamento avvenga durante l'uso utile invece che in standby.

### Dimensionamento della finestra

Capacità termica dell'acqua: `c · ρ ≈ 1.163 Wh / (L · °C)`.

Tempo di warm-up completo a 1200 W partendo da 15 °C:

| Setpoint | ΔT | Tempo |
|----------|----|-------|
| 40 °C    | 25 | 1h 56m |
| 45 °C    | 30 | 2h 19m |
| 50 °C    | 35 | 2h 42m |
| 55 °C    | 40 | 3h 05m |

Partendo però da un tank tiepido (~30 °C dopo 11 h di standing loss
contenuta grazie al nuovo setpoint basso), il warm-up reale a 45 °C
richiede solo:

```
ΔT 15 °C × 80 L × 1.163 Wh / 1200 W ≈ 77 min
```

La finestra da 90 min copre il warm-up con margine. Il termostato
meccanico interno taglia la resistenza negli ultimi 10-15 min: quando
le due finestre sono consecutive (11 h di gap) la seconda trova il
tank ancora a ~35-38 °C e chiude in 40-60 min di resistenza attiva.

### Ruolo del termostato meccanico

Il risparmio reale nasce dall'abbassare il setpoint del termostato
meccanico del boiler a **~45 °C** (azione manuale fisica, una
tantum). Motivazione: lo standing loss è quasi lineare con ΔT
tank-ambiente. Per un tank 80 L EcoDesign classe C con
`UA ≈ 1.9 W/°C`:

| Setpoint | Perdita 24 h a 20 °C amb |
|----------|--------------------------|
| 55 °C    | ~1.6 kWh |
| 50 °C    | ~1.4 kWh |
| 45 °C    | ~1.1 kWh |
| 40 °C    | ~0.9 kWh |

A 45 °C il tank resta comodamente sufficiente per lavaggio viso e
stoviglie (miscelato con acqua fredda al rubinetto) e lo standing
loss cala del ~30 % rispetto a 55 °C.

### Safety net hardware

Ogni `turn_on` dell'automazione scrive anche
`number.boiler_giorno_turn_off_in = 120` (minuti). La presa Tapo ha un
countdown di auto-spegnimento on-device: se Home Assistant si ferma
(crash, update, rete persa) tra il turn_on e il turn_off pianificato,
la presa si autospegne dopo 2 h senza lasciare il boiler acceso
indefinitamente. 120 min copre la finestra 90 min + margine.

### Legionella

Il rischio Legionella in un tank 80 L usato quotidianamente è basso
(no stagnazione, biofilm limitato). Setpoint 45 °C resta nella zona
"tiepida" ma il ricambio giornaliero riduce il rischio pratico. Se
in futuro si volesse aggiungere un ciclo settimanale a 60 °C
occorrerà ruotare manualmente la manopola del termostato: non è
automatizzabile con la presa smart, perché il controllo della
temperatura è meccanico a bordo del boiler.

---

## Consumo atteso

- **Attuale (mirror)**: ~1.68 kWh/giorno (resistenza quasi sempre
  attiva nelle finestre di 42 min × 2)
- **Nuovo schema + setpoint 45 °C**: ~1.0-1.2 kWh/giorno
- **Delta**: ~0.5-0.7 kWh/giorno → ~15-20 kWh/mese → ~€4-6/mese a
  €0.30/kWh

In assoluto è un risparmio modesto; in percentuale sul consumo del
boiler giorno è ~30-40 %.

---

## Entità coinvolte

| Entità | Ruolo |
|--------|-------|
| `switch.boiler_giorno` | Presa TP-Link Tapo che alimenta il boiler dumb |
| `number.boiler_giorno_turn_off_in` | Countdown hardware on-device, usato come safety net |
| `automation.boiler_giorno_accensione_schedule` | Accende la presa alle 05:30 e 18:00 |
| `automation.boiler_giorno_spegnimento_schedule` | Spegne la presa alle 07:00 e 19:30 |
| `binary_sensor.ariston_is_heating_2` | Non più usato per pilotare la zona giorno |

### Automazioni rimosse

- `automation.boiler_giorno_on`  (alias "boiler giorno on")
- `automation.boiler_giorno_off` (alias "boiler giorno off")

Erano entrambe generate via UI con trigger `device`, il che
rendeva opachi sia il dispositivo triggerante sia quello pilotato.

---

## Modifiche al repository

File toccati:

| File | Modifica |
|------|----------|
| `homeassistant/.gitignore` | Autorizza il tracking di `automations.yaml` (prima l'intero contenuto della cartella HA era ignorato tranne `configuration.yaml`) |
| `homeassistant/automations.yaml` | **Nuovo nel repo.** Copia della configurazione in produzione con la sostituzione delle 2 automazioni mirror. Altre automazioni del file restano invariate |

Tutte le costanti runtime HA (`.storage`, database recorder, log,
custom components, ecc.) restano git-ignored come prima.

---

## Deploy

Lo stato di produzione coincide con `main`. Per applicare future
modifiche alle automazioni:

```bash
# 1. modifica il file nel repo, commit, push
git add homeassistant/automations.yaml
git commit -m "..."
git push origin main

# 2. apply su mulo
ssh mulo 'cd /srv/docker && git pull && docker compose restart homeassistant'
```

Validazione pre-deploy (consigliata):

```bash
ssh mulo 'docker exec homeassistant hass --script check_config -c /config'
```

Restituisce exit code `0` se la configurazione è valida, senza
toccare lo stato runtime.

### Note sul parsing YAML

Gli orari nei trigger `time` **devono essere quotati** (`at: '07:00:00'`).
Senza quote il parser YAML 1.1 di Home Assistant interpreta stringhe
come `18:00:00` o `19:30:00` come interi sessagesimali (cifra iniziale
1-9 matcha il pattern base-60), mentre orari con leading zero come
`05:30:00` o `07:00:00` restano stringhe e passano la validazione. Il
risultato sarebbe un fallimento silenzioso per alcuni orari e non per
altri. La quotatura esplicita uniforma il comportamento.

---

## Step manuale una-tantum

Per rendere effettivo il risparmio serve un intervento fisico sul
boiler: la manopola del termostato meccanico va ruotata su **~45 °C**.
Nessun modo di automatizzarlo — il controllo di temperatura è
on-device, la presa smart si limita a dare corrente alla resistenza.

---

## Verifica

Non essendoci un sensore di potenza sulla presa Tapo P100, il consumo
del boiler giorno non è misurato direttamente. Validazione indiretta:

1. **Storico switch**: HA → History → `switch.boiler_giorno` — deve
   seguire le finestre 05:30-07:00 e 18:00-19:30, non più i cicli
   Ariston
2. **Durata ON**: `sensor.boiler_giorno_on_since` per controllare la
   durata effettiva delle finestre
3. **Delta grid**: durante la fascia 05:30-06:00 il boiler notte è
   ancora off; un picco di ~1.2 kW su `sensor.energy_meter_0_power`
   in quella fascia corrisponde alla resistenza del boiler giorno
   attiva. Il picco deve esaurirsi entro 40-80 min quando il
   termostato taglia
4. **Comfort soggettivo**: osservare 5-7 giorni. Se l'acqua non è
   abbastanza calda al mattino, anticipare a 05:00 o alzare setpoint a
   48-50 °C. Se è troppo calda, ridurre finestra o abbassare ancora

---

## Rollback

```bash
git revert <commit-hash>
git push origin main
ssh mulo 'cd /srv/docker && git pull && docker compose restart homeassistant'
```

Il file `automations.yaml.bak.20260421` su mulo conserva la
versione pre-modifica del solo file delle automazioni, utile come
copia di sicurezza locale.

Dopo il rollback occorre ripristinare manualmente il setpoint del
termostato del boiler giorno al valore precedente per tornare al
comportamento completo di prima.
