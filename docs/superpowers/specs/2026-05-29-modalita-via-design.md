# Modalità "Via per molti giorni" — Design

**Data:** 2026-05-29
**Stato:** approvato (design), in attesa di piano di implementazione

## Obiettivo

Una modalità "casa vuota per molti giorni" attivabile manualmente che:
spegne completamente il boiler della casa principale, abbassa le tapparelle
a metà e sospende le automazioni giornaliere; poi, in base a una data/ora di
rientro impostata dall'utente, ri-scalda l'acqua in tempo per l'arrivo e
ripristina tutto allo stato precedente in automatico (o a comando manuale in
qualsiasi momento).

## Vincoli fondamentali

- **BILO è escluso.** Bilo è una casa fisicamente separata con regole proprie.
  Nessuna entità bilo deve essere toccata. Convenzione di naming Ariston:
  - **Bilo (ESCLUSO)** = entità *senza* suffisso `_2`: `water_heater.boiler_bilo`,
    `switch.ariston_power`, `switch.ariston_eco_mode`,
    `switch.ariston_anti_legionella`, `number.ariston_max_setpoint_temperature`,
    `binary_sensor.ariston_is_heating`.
  - **Notte / casa principale (INCLUSO)** = entità *con* suffisso `_2`:
    `water_heater.boiler_notte`, `switch.ariston_power_2`,
    `switch.ariston_eco_mode_2`, `binary_sensor.ariston_is_heating_2`.
  - Verificare sempre il `friendly_name` ("boiler bilo" vs "boiler notte") prima
    di agire, perché la convenzione `_2` dipende dall'ordine di registrazione.
- **Anti-legionella: escluso.** Nessun ciclo di sanificazione automatico.
- **Trigger solo manuale.** Niente attivazione automatica su presenza (il tracker
  di Fabiola è inaffidabile).
- **Nessun light/climate.** L'impianto non espone domini `light` né `climate`;
  l'acqua calda è gestita via `water_heater` + prese `switch`.

## Entità coinvolte

### In scope
| Entità | Ruolo |
|---|---|
| `water_heater.boiler_notte` | Boiler principale (Ariston). Modi: MANUAL/PROGRAM/BOOST. Stato attuale: PROGRAM @65°C. |
| `switch.ariston_power_2` | Alimentazione boiler notte. |
| `switch.ariston_eco_mode_2` | Eco mode boiler notte (solo snapshot). |
| `switch.boiler_giorno` | Presa Tapo boiler giorno (senza setpoint). |
| `number.boiler_giorno_turn_off_in` | Countdown hardware auto-off Tapo (safety net). |
| `binary_sensor.ariston_is_heating_2` | "Boiler notte sta scaldando" — usato dal mirror del boiler giorno. |
| `cover.*` (10, tutte tranne `cover.soggiorno_tenda_veranda`) | Tapparelle da portare al 50%. |
| `automation.buongiorno` | Scena giorno feriale 07:00 — da sospendere. |
| `automation.boiler_giorno_accensione_schedule` | Schedule boiler giorno — da sospendere. |
| `automation.boiler_giorno_spegnimento_schedule` | Schedule boiler giorno — da sospendere. |

### Esplicitamente fuori scope
- Tutte le entità **bilo** (vedi vincoli).
- `cover.soggiorno_tenda_veranda` e `automation.ritira_tenda_veranda_prima_della_pioggia`
  (la protezione meteo della tenda resta attiva — è più utile da via).
- Media player (Sonos, LG TV, Chromecast, proiettore), `switch.sonos_alarm_1`.
- Notifiche lavatrice/asciugatrice.

## Helper da creare

| Helper | Tipo | Default | Ruolo |
|---|---|---|---|
| `input_boolean.modalita_via` | input_boolean | off | Interruttore principale della modalità. |
| `input_datetime.rientro` | input_datetime (date + time) | — | Data e ora di arrivo previsto. |
| `input_number.anticipo_riscaldamento_ore` | input_number (min 1, max 12, step 0.5) | 4 | Ore di anticipo del pre-heat rispetto al rientro. |

Niente template/helper di stato aggiuntivi: lo stato della modalità è interamente
in `input_boolean.modalita_via`.

## Scene snapshot (create a runtime all'attivazione)

Create con `scene.create` (snapshot dello stato corrente) all'ingresso in modalità,
così il ripristino riporta lo stato **esatto** precedente.

- **`scene.snapshot_via_boiler`** — snapshot di: `water_heater.boiler_notte`,
  `switch.ariston_power_2`, `switch.ariston_eco_mode_2`, `switch.boiler_giorno`.
- **`scene.snapshot_via_tapparelle`** — snapshot di tutte le tapparelle in scope
  (tutte le `cover.*` tranne `cover.soggiorno_tenda_veranda`).

Due scene separate per poter ripristinare i boiler (in ② / rientro) senza toccare
le tapparelle, e viceversa.

## Automazioni

### A. `Modalità via - gestione` (`mode: single`)
- **Trigger:** stato di `input_boolean.modalita_via`.
- **Azioni:** `choose` sul nuovo stato.
  - **→ on (ingresso ①):**
    1. `scene.create` di `snapshot_via_boiler` e `snapshot_via_tapparelle`.
    2. Boiler OFF totale: `switch.turn_off` su `switch.ariston_power_2` e
       `switch.boiler_giorno`; `water_heater.turn_off` su `water_heater.boiler_notte`.
    3. `cover.set_cover_position` a `50` su tutte le tapparelle in scope.
    4. `automation.turn_off` su `buongiorno`,
       `boiler_giorno_accensione_schedule`, `boiler_giorno_spegnimento_schedule`.
    5. Assicura il mirror disabilitato (`automation.turn_off` su
       `modalita_via_mirror_boiler_giorno`).
    6. Notifica push (iPhone Cristiano).
  - **→ off (ripristino ③):**
    1. `automation.turn_off` del mirror boiler giorno.
    2. `scene.turn_on` di `snapshot_via_tapparelle` e `snapshot_via_boiler`
       (boiler notte torna al modo originale, es. PROGRAM; idempotente se il
       pre-heat è già avvenuto).
    3. `automation.turn_on` su `buongiorno`,
       `boiler_giorno_accensione_schedule`, `boiler_giorno_spegnimento_schedule`.
    4. Notifica push.

### B. `Modalità via - pre-heat` (`mode: single`)
- **Trigger:** `template` — `now() >= (rientro − anticipo_ore)`.
  (Nessun trigger nativo per "N ore prima di una datetime dinamica"; il template
  è la sola opzione corretta — accettato dalla best-practice in assenza di nativo.)
- **Condizioni:** `input_boolean.modalita_via` è `on` **e** il pre-heat non è già
  avvenuto (guardia idempotente, es. `switch.ariston_power_2` ancora `off`).
- **Azioni:**
  1. `switch.turn_on` su `switch.ariston_power_2`.
  2. `water_heater.set_operation_mode` a `MANUAL` su `water_heater.boiler_notte`
     (riscalda in continuo fino al setpoint impostato; **niente BOOST**, niente
     legionella).
  3. `automation.turn_on` su `modalita_via_mirror_boiler_giorno` (il boiler giorno
     segue il boiler notte durante il pre-heat).
  4. Notifica push ("boiler in riscaldamento per il rientro").
- **Caso limite:** se `rientro − anticipo` è già passato al momento dell'attivazione,
  il trigger è vero subito e il pre-heat parte immediatamente.

### C. `Modalità via - rientro programmato` (`mode: single`)
- **Trigger:** `time` con `at: input_datetime.rientro` (trigger nativo su entità
  datetime).
- **Condizioni:** `input_boolean.modalita_via` è `on`.
- **Azioni:** `input_boolean.turn_off` su `input_boolean.modalita_via`.
  (Il ripristino vero e proprio avviene per cascata tramite l'automazione A → off.
  Una sola logica di restore, niente duplicazioni.)

### D. `Modalità via - mirror boiler giorno` (`mode: single`, **creata disabilitata**)
- **Trigger:** stato di `binary_sensor.ariston_is_heating_2`.
- **Azioni:** `choose`:
  - se `binary_sensor.ariston_is_heating_2` è `on` → `switch.turn_on`
    `switch.boiler_giorno` + `number.set_value` `number.boiler_giorno_turn_off_in` a
    `120` (safety net Tapo).
  - se `off` → `switch.turn_off` `switch.boiler_giorno`.
- Abilitata solo durante il pre-heat (da B), disabilitata al ripristino (da A→off).
- Replica il comportamento "a specchio" storico, ma solo nella finestra di pre-heat.

## Flusso end-to-end

```
① ATTIVAZIONE (manuale)          modalita_via → on
   ├─ snapshot boiler + tapparelle (2 scene)
   ├─ boiler notte OFF totale (ariston_power_2 off, water_heater off)
   ├─ boiler giorno OFF
   ├─ tapparelle → 50%
   └─ sospendi: buongiorno, schedule boiler giorno, (mirror off)

   [utente imposta input_datetime.rientro nella dashboard]

② PRE-HEAT                       a (rientro − anticipo), modalita_via ancora on
   ├─ boiler notte → MANUAL @ setpoint (riscalda in continuo)
   ├─ ariston_power_2 ON
   └─ abilita mirror boiler giorno (giorno segue notte)

③ RIPRISTINO                     a (rientro esatto)  OPPURE  toggle off manuale
   ├─ disabilita mirror boiler giorno
   ├─ scene.turn_on tapparelle  → posizione precedente
   ├─ scene.turn_on boiler       → boiler notte torna a PROGRAM (modo originale)
   ├─ riattiva: buongiorno, schedule boiler giorno
   └─ modalita_via → off
```

## Dashboard

Una card che raggruppa:
- toggle `input_boolean.modalita_via`,
- campo `input_datetime.rientro`,
- slider/box `input_number.anticipo_riscaldamento_ore`.

Nota UX: il toggle non apre un popup che "chiede" la data; la data si imposta nel
campo accanto. Se `input_datetime.rientro` è lasciato vuoto, pre-heat (B) e rientro
programmato (C) non agiscono: vale solo lo spegnimento manuale.

## Caso limite: rientro vuoto / nel passato
- **Rientro non impostato:** B e C non scattano (B richiede una data valida; C non
  ha un orario a cui agganciarsi). La modalità si chiude solo manualmente.
- **Rientro tra meno di `anticipo` ore:** il pre-heat parte subito (vedi B).
- **Rientro nel passato:** B vero subito (pre-heat immediato); C scatta solo su
  un orario futuro, quindi in pratica si esce a mano.

## Rischio noto accettato
Con boiler notte ripristinato a `PROGRAM` in ③, l'acqua è già calda dal pre-heat
MANUAL; PROGRAM riprende solo la gestione ordinaria successiva. Il pre-heat MANUAL
@ setpoint elimina il rischio "acqua tiepida" della versione precedente.

## Nota di implementazione
Il server MCP `home-assistant` è attualmente bloccato da macOS (permesso Local
Network del subprocess `uvx ha-mcp`). L'applicazione della config avverrà via
**API REST** di Home Assistant col token (`http://192.168.1.10:8123/api/...`,
verificato funzionante durante l'analisi) oppure dopo aver concesso il permesso
Local Network e riavviato l'MCP. Non blocca la progettazione.

## Fuori da questo intervento (eventuale fase 2)
Alert "consumo elettrico anomalo mentre sei via" basato su
`sensor.energy_meter_0_power` (Shelly Pro EM50). Non ci sono sensori
porta/finestra/movimento, quindi nessun rilevamento intrusione.
