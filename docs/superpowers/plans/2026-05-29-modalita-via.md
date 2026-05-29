# Modalità "Via per molti giorni" — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implementare una modalità "casa vuota per molti giorni" su Home Assistant che spegne il boiler della casa principale, porta le tapparelle al 50% e sospende le automazioni giornaliere; con pre-riscaldamento automatico e ripristino allo stato precedente in base a una data/ora di rientro.

**Architecture:** 3 helper di stato (`input_boolean`, `input_datetime`, `input_number`), 2 scene snapshot create a runtime con `scene.create`, e 4 automazioni (gestione on/off, pre-heat, rientro programmato, mirror boiler giorno). Lo stato vive interamente negli helper; nessun template sensor. Vincolo assoluto: **nessuna entità bilo** (casa separata) viene toccata.

**Tech Stack:** Home Assistant (automations.yaml git-tracked + helper via config flow / configuration.yaml), MCP `home-assistant` per scrittura validata; fallback REST API (`http://192.168.1.10:8123/api/...`).

**Spec di riferimento:** `docs/superpowers/specs/2026-05-29-modalita-via-design.md`

---

## Costanti condivise

**Tapparelle in scope (9 fisiche, tutte tranne la tenda veranda):**
```
cover.cucina_tapp_finestra
cover.cucina_tapp_finestra_2
cover.cucina_tapp_portafinestra
cover.notte_tapp_terrazzo_tapp_terrazzo
cover.shellyshutter_48f6ee8ed8bc
cover.shellyshutter_48f6ee8f065c
cover.soggiorno_tapp_portafinestra_destra
cover.tapparella_giacomo
cover.tapparella_scala
```
(`cover.gruppo_tapparelle_zona_notte` è solo un aggregatore dei 4 membri notte → NON usato. `cover.soggiorno_tenda_veranda` → ESCLUSA.)

**Boiler in scope (casa principale = suffisso `_2`):** `water_heater.boiler_notte`, `switch.ariston_power_2`, `switch.ariston_eco_mode_2`, `switch.boiler_giorno`, `number.boiler_giorno_turn_off_in`, `binary_sensor.ariston_is_heating_2`.

**Boiler ESCLUSI (bilo):** `water_heater.boiler_bilo`, `switch.ariston_power`, `switch.ariston_eco_mode`, `switch.ariston_anti_legionella`, `number.ariston_max_setpoint_temperature`, `binary_sensor.ariston_is_heating`. **Mai referenziati.**

**Automazioni da sospendere/riattivare:** `automation.buongiorno`, `automation.boiler_giorno_accensione_schedule`, `automation.boiler_giorno_spegnimento_schedule`.

---

## File coinvolti

- **Modify:** config Home Assistant runtime (via MCP/REST) — helper e automazioni.
- **Modify:** `homeassistant/automations.yaml` (git-tracked) — vi finiranno le 4 nuove automazioni; va committato a fine lavoro per riallinearlo al runtime.
- **Modify (eventuale):** `homeassistant/configuration.yaml` — solo se gli helper si creano via YAML invece che via config flow.
- **No file nuovi** lato repo per scene (create a runtime) e dashboard (storage-mode).

---

## Task 0: Ripristinare l'accesso di scrittura a Home Assistant

**Files:** nessuno (ambiente).

Il server MCP `home-assistant` (`uvx ha-mcp`) non si connette: macOS blocca l'accesso alla rete locale al subprocess. La REST API invece funziona da questa macchina (verificato).

- [ ] **Step 1: Verificare lo stato dell'MCP**

Provare una chiamata read dell'MCP, es. `ha_get_overview`.
Atteso: errore `CONNECTION_FAILED` (conferma il problema) oppure successo (problema già risolto → salta al Path A).

- [ ] **Step 2: Scegliere il path**

- **Path A — sistemare l'MCP (preferito, config validata):** System Settings → Privacy & Security → Local Network → abilitare l'app che esegue Claude Code (Terminal/iTerm). Poi riavviare Claude Code così il subprocess `uvx` viene rilanciato. Ri-eseguire `ha_get_overview`: atteso successo con elenco entità.
- **Path B — REST API (fallback):** usare il token già noto. Helper di shell:
```bash
TOKEN=$(python3 /tmp/ha_token.py)   # legge il token da ~/.claude.json
curl -s -H "Authorization: Bearer $TOKEN" http://192.168.1.10:8123/api/ -w "\nHTTP %{http_code}\n"
```
Atteso: `{"message":"API running."}` HTTP 200.

> Nota: gli helper `input_*` si creano in modo pulito solo via MCP (config flow) o via YAML in `configuration.yaml`. La REST API può chiamare servizi e leggere stati ma non "crea helper". Se si resta su Path B, gli helper vanno creati via YAML (vedi Task 1, variante B).

- [ ] **Step 3: Registrare il path scelto** nel messaggio di commit/handoff così i task successivi usano lo strumento giusto.

---

## Task 1: Creare i 3 helper

**Files:** runtime HA (config flow) **oppure** `homeassistant/configuration.yaml` (variante B).

- [ ] **Step 1 (Variante A — MCP): creare gli helper via config flow**

`ha_config_set_helper` ×3:

```yaml
# input_boolean
domain: input_boolean
name: "Modalità via"
# → entity_id atteso: input_boolean.modalita_via
icon: mdi:home-export-outline
```
```yaml
# input_datetime
domain: input_datetime
name: "Rientro previsto"
has_date: true
has_time: true
# → input_datetime.rientro
icon: mdi:calendar-clock
```
```yaml
# input_number
domain: input_number
name: "Anticipo riscaldamento ore"
min: 1
max: 12
step: 0.5
initial: 4
unit_of_measurement: "h"
mode: box
# → input_number.anticipo_riscaldamento_ore
icon: mdi:timer-sand
```
```yaml
# input_text — backup operation_mode del boiler notte (vedi Task 3, nota fix)
domain: input_text
name: "Modalità via boiler mode"
max: 20
# → input_text.modalita_via_boiler_mode
icon: mdi:water-boiler
```

**Step 1 (Variante B — YAML):** aggiungere a `homeassistant/configuration.yaml`:
```yaml
input_boolean:
  modalita_via:
    name: "Modalità via"
    icon: mdi:home-export-outline

input_datetime:
  rientro:
    name: "Rientro previsto"
    has_date: true
    has_time: true

input_number:
  anticipo_riscaldamento_ore:
    name: "Anticipo riscaldamento ore"
    min: 1
    max: 12
    step: 0.5
    initial: 4
    unit_of_measurement: "h"
    mode: box
```
poi ricaricare: REST `POST /api/services/input_boolean/reload` (+ `input_datetime/reload`, `input_number/reload`) o `ha_reload_core`.

- [ ] **Step 2: Verificare gli entity_id risultanti**

MCP: `ha_search_entities` (domain_filter `input_boolean`/`input_datetime`/`input_number`).
REST: `curl -s -H "Authorization: Bearer $TOKEN" http://192.168.1.10:8123/api/states/input_boolean.modalita_via`
Atteso: i tre entity_id `input_boolean.modalita_via`, `input_datetime.rientro`, `input_number.anticipo_riscaldamento_ore` esistono. `input_number` a 4.0.

> Se l'entity_id generato differisce (es. `input_boolean.modalita_via_2`), annotarlo e usare quello reale in tutti i task seguenti.

- [ ] **Step 3: Commit (solo se Variante B)**

```bash
git add homeassistant/configuration.yaml
git commit -m "Add modalità via helpers (input_boolean/datetime/number)"
```

---

## Task 2: Automazione mirror boiler giorno (creata disabilitata)

Va creata **prima** della gestione, perché la gestione la referenzia. Triggera sul boiler notte e specchia sul boiler giorno; attiva solo durante il pre-heat.

**Files:** runtime HA (`ha_config_set_automation`) → persistito in `homeassistant/automations.yaml`.

- [ ] **Step 1: Creare l'automazione**

```yaml
id: modalita_via_mirror_boiler_giorno
alias: Modalità via - mirror boiler giorno
description: >
  Durante il pre-heat il boiler giorno (presa senza setpoint) segue il boiler
  notte: ON mentre notte scalda, OFF quando smette. Abilitata solo nella
  finestra di pre-heat dalla automazione pre-heat; disabilitata al ripristino.
mode: single
triggers:
  - trigger: state
    entity_id: binary_sensor.ariston_is_heating_2
    to: "on"
    id: heating_on
  - trigger: state
    entity_id: binary_sensor.ariston_is_heating_2
    to: "off"
    id: heating_off
conditions: []
actions:
  - choose:
      - conditions:
          - condition: trigger
            id: heating_on
        sequence:
          - action: switch.turn_on
            target:
              entity_id: switch.boiler_giorno
          - action: number.set_value
            target:
              entity_id: number.boiler_giorno_turn_off_in
            data:
              value: 120
    default:
      - action: switch.turn_off
        target:
          entity_id: switch.boiler_giorno
```

- [ ] **Step 2: Validare la config**

`ha_check_config` (o REST `POST /api/config/core/check_config` non valida automazioni; preferire MCP `ha_check_config`).
Atteso: `result: valid`.

- [ ] **Step 3: Disabilitarla (stato off, available)**

MCP: `ha_call_service` `automation.turn_off` su `automation.modalita_via_mirror_boiler_giorno`.
REST: `curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"entity_id":"automation.modalita_via_mirror_boiler_giorno"}' http://192.168.1.10:8123/api/services/automation/turn_off`

- [ ] **Step 4: Verificare lo stato**

`ha_get_state automation.modalita_via_mirror_boiler_giorno`.
Atteso: `state: off`. (Lo stato off persiste tra i riavvii via RestoreState.)

---

## Task 3: Automazione gestione (ingresso ① / ripristino ③)

**Files:** runtime HA → `homeassistant/automations.yaml`.

- [ ] **Step 1: Creare l'automazione**

```yaml
id: modalita_via_gestione
alias: Modalità via - gestione
description: >
  All'accensione di input_boolean.modalita_via: snapshot, spegne il boiler della
  casa principale, tapparelle al 50%, sospende le automazioni giornaliere.
  Allo spegnimento: ripristina lo stato esatto precedente e riattiva tutto.
  Non tocca alcuna entità bilo.
mode: single
triggers:
  - trigger: state
    entity_id: input_boolean.modalita_via
    to: "on"
    id: attiva
  - trigger: state
    entity_id: input_boolean.modalita_via
    to: "off"
    id: ripristina
conditions: []
actions:
  - choose:
      # ───────── ① INGRESSO ─────────
      - conditions:
          - condition: trigger
            id: attiva
        sequence:
          - action: input_text.set_value
            target:
              entity_id: input_text.modalita_via_boiler_mode
            data:
              value: "{{ states('water_heater.boiler_notte') }}"
          - action: scene.create
            data:
              scene_id: snapshot_via_boiler
              snapshot_entities:
                - water_heater.boiler_notte
                - switch.ariston_power_2
                - switch.ariston_eco_mode_2
                - switch.boiler_giorno
          - action: scene.create
            data:
              scene_id: snapshot_via_tapparelle
              snapshot_entities:
                - cover.cucina_tapp_finestra
                - cover.cucina_tapp_finestra_2
                - cover.cucina_tapp_portafinestra
                - cover.notte_tapp_terrazzo_tapp_terrazzo
                - cover.shellyshutter_48f6ee8ed8bc
                - cover.shellyshutter_48f6ee8f065c
                - cover.soggiorno_tapp_portafinestra_destra
                - cover.tapparella_giacomo
                - cover.tapparella_scala
          - action: water_heater.turn_off
            target:
              entity_id: water_heater.boiler_notte
          - action: switch.turn_off
            target:
              entity_id:
                - switch.ariston_power_2
                - switch.boiler_giorno
          - action: cover.set_cover_position
            target:
              entity_id:
                - cover.cucina_tapp_finestra
                - cover.cucina_tapp_finestra_2
                - cover.cucina_tapp_portafinestra
                - cover.notte_tapp_terrazzo_tapp_terrazzo
                - cover.shellyshutter_48f6ee8ed8bc
                - cover.shellyshutter_48f6ee8f065c
                - cover.soggiorno_tapp_portafinestra_destra
                - cover.tapparella_giacomo
                - cover.tapparella_scala
            data:
              position: 50
          - action: automation.turn_off
            target:
              entity_id:
                - automation.buongiorno
                - automation.boiler_giorno_accensione_schedule
                - automation.boiler_giorno_spegnimento_schedule
                - automation.modalita_via_mirror_boiler_giorno
          - action: notify.mobile_app_iphone_cristiano
            data:
              title: "🏠 Modalità via attivata"
              message: >
                Boiler spento, tapparelle al 50%, automazioni giornaliere
                sospese. Imposta la data di rientro per il pre-riscaldamento.
      # ───────── ③ RIPRISTINO ─────────
      - conditions:
          - condition: trigger
            id: ripristina
        sequence:
          - action: automation.turn_off
            target:
              entity_id: automation.modalita_via_mirror_boiler_giorno
          - action: scene.turn_on
            continue_on_error: true
            target:
              entity_id:
                - scene.snapshot_via_tapparelle
                - scene.snapshot_via_boiler
          # La scena NON ripristina l'operation_mode del water_heater Ariston
          # (verificato in test): ripristino esplicito dal backup input_text.
          - if:
              - condition: template
                value_template: "{{ states('input_text.modalita_via_boiler_mode') in ['MANUAL','PROGRAM','BOOST'] }}"
            then:
              - action: water_heater.set_operation_mode
                target:
                  entity_id: water_heater.boiler_notte
                data:
                  operation_mode: "{{ states('input_text.modalita_via_boiler_mode') }}"
          - action: automation.turn_on
            target:
              entity_id:
                - automation.buongiorno
                - automation.boiler_giorno_accensione_schedule
                - automation.boiler_giorno_spegnimento_schedule
          - action: notify.mobile_app_iphone_cristiano
            data:
              title: "🏠 Modalità via disattivata"
              message: "Casa ripristinata allo stato precedente."
```

- [ ] **Step 2: Validare la config**

`ha_check_config`. Atteso: `result: valid`.

- [ ] **Step 3: Verificare che l'automazione sia caricata e on**

`ha_get_state automation.modalita_via_gestione`. Atteso: `state: on`.

---

## Task 4: Automazione pre-heat (②)

A `rientro − anticipo` riaccende il boiler notte in MANUAL e abilita il mirror. Trigger template basato su `now()` (l'engine HA ricalcola i template con `now()` ~ogni minuto, quindi scatta al minuto in cui la condizione diventa vera).

**Files:** runtime HA → `homeassistant/automations.yaml`.

- [ ] **Step 1: Creare l'automazione**

```yaml
id: modalita_via_preheat
alias: Modalità via - pre-heat
description: >
  A (rientro − anticipo ore) riaccende il boiler notte in MANUAL per portarlo a
  temperatura prima dell'arrivo, e abilita il mirror del boiler giorno. Niente
  BOOST, niente anti-legionella. Solo casa principale.
mode: single
triggers:
  - trigger: template
    value_template: >
      {% set ts = state_attr('input_datetime.rientro', 'timestamp') | float(0) %}
      {% set anticipo = states('input_number.anticipo_riscaldamento_ore') | float(4) %}
      {{ ts > 0 and now().timestamp() >= (ts - anticipo * 3600) }}
conditions:
  - condition: state
    entity_id: input_boolean.modalita_via
    state: "on"
  - condition: state
    entity_id: switch.ariston_power_2
    state: "off"
actions:
  - action: switch.turn_on
    target:
      entity_id: switch.ariston_power_2
  - action: water_heater.set_operation_mode
    target:
      entity_id: water_heater.boiler_notte
    data:
      operation_mode: MANUAL
  - action: automation.turn_on
    target:
      entity_id: automation.modalita_via_mirror_boiler_giorno
  - action: notify.mobile_app_iphone_cristiano
    data:
      title: "♨️ Pre-riscaldamento rientro"
      message: "Boiler notte in riscaldamento per il tuo rientro."
```

- [ ] **Step 2: Validare la config**

`ha_check_config`. Atteso: `result: valid`.

- [ ] **Step 3: Testare il template del trigger isolatamente**

`ha_eval_template` con (impostando prima `input_datetime.rientro` a tra 1 ora e `anticipo`=4):
```jinja
{% set ts = state_attr('input_datetime.rientro', 'timestamp') | float(0) %}
{% set anticipo = states('input_number.anticipo_riscaldamento_ore') | float(4) %}
{{ ts > 0 and now().timestamp() >= (ts - anticipo * 3600) }}
```
Atteso: `True` (rientro tra 1h e anticipo 4h → `now ≥ rientro−4h` è vero).
Poi impostare `rientro` a tra 10 ore → ri-valutare → atteso `False`.

- [ ] **Step 4: Verificare lo stato dell'automazione**

`ha_get_state automation.modalita_via_preheat`. Atteso: `state: on`.

---

## Task 5: Automazione rientro programmato (③ automatico)

All'orario esatto di `rientro` spegne `input_boolean.modalita_via`, che fa partire il ripristino via Task 3. Trigger nativo su entità datetime.

**Files:** runtime HA → `homeassistant/automations.yaml`.

- [ ] **Step 1: Creare l'automazione**

```yaml
id: modalita_via_rientro
alias: Modalità via - rientro programmato
description: >
  All'orario di input_datetime.rientro spegne la modalità via, innescando il
  ripristino completo (gestito dall'automazione "Modalità via - gestione").
mode: single
triggers:
  - trigger: time
    at: input_datetime.rientro
conditions:
  - condition: state
    entity_id: input_boolean.modalita_via
    state: "on"
actions:
  - action: input_boolean.turn_off
    target:
      entity_id: input_boolean.modalita_via
```

- [ ] **Step 2: Validare la config**

`ha_check_config`. Atteso: `result: valid`.

- [ ] **Step 3: Verificare lo stato**

`ha_get_state automation.modalita_via_rientro`. Atteso: `state: on`.

---

## Task 6: Card in dashboard

La dashboard HA è storage-mode: la card si aggiunge via UI o via `ha_config_set_dashboard`. Raggruppa toggle + data rientro + anticipo.

**Files:** dashboard storage-mode (no file di repo).

- [ ] **Step 1: Aggiungere una card entities**

Config card:
```yaml
type: entities
title: Modalità via
icon: mdi:home-export-outline
entities:
  - entity: input_boolean.modalita_via
    name: Attiva modalità via
  - entity: input_datetime.rientro
    name: Rientro previsto
  - entity: input_number.anticipo_riscaldamento_ore
    name: Anticipo riscaldamento (h)
```
Via UI: Dashboard → Modifica → Aggiungi card → Entities → incollare YAML.
Via MCP: `ha_config_get_dashboard` per leggere la dashboard target, inserire la card, `ha_config_set_dashboard`.

- [ ] **Step 2: Verificare in UI** che la card mostri i 3 controlli e che il toggle/data/slider siano operabili.

---

## Task 7: Verifica end-to-end (test controllato live)

⚠️ **Effetti fisici reali:** questo test spegne il boiler notte e muove 9 tapparelle al 50%. Eseguirlo solo quando gli effetti sono accettabili (es. di giorno, presenti in casa). Lo snapshot garantisce il ripristino esatto.

**Files:** nessuno.

- [ ] **Step 1: Snapshot manuale dello stato pre-test**

Annotare con `ha_get_state` lo stato di partenza di: `water_heater.boiler_notte` (operation_mode + temperature), `switch.ariston_power_2`, `switch.boiler_giorno`, e la `current_position` delle 9 tapparelle.

- [ ] **Step 2: Attivare la modalità**

`input_boolean.turn_on` su `input_boolean.modalita_via`.
Attendere ~10s, poi verificare:
- `water_heater.boiler_notte` → `off` (o non heating), `switch.ariston_power_2` → `off`, `switch.boiler_giorno` → `off`.
- Le 9 tapparelle → `current_position` ~50.
- `automation.buongiorno`, `..._accensione_schedule`, `..._spegnimento_schedule`, `...mirror_boiler_giorno` → `off`.
- Esistono `scene.snapshot_via_boiler` e `scene.snapshot_via_tapparelle`.
- ⚠️ Verificare che **nessuna** entità bilo sia cambiata: `switch.ariston_power`, `water_heater.boiler_bilo` invariati.

- [ ] **Step 3: Testare il pre-heat**

Impostare `input_datetime.rientro` a ~`now + (anticipo - 0.05h)` (così `now ≥ rientro−anticipo` è già vero) e attendere al massimo 1 minuto (rieval template).
Verificare con `ha_get_automation_traces` per `modalita_via_preheat` che sia scattata, e:
- `switch.ariston_power_2` → `on`, `water_heater.boiler_notte` operation_mode → `MANUAL`.
- `automation.modalita_via_mirror_boiler_giorno` → `on`.

- [ ] **Step 4: Testare il rientro programmato**

Impostare `input_datetime.rientro` a `now + ~2 min`. Attendere lo scoccare.
Verificare con trace di `modalita_via_rientro` che abbia spento `input_boolean.modalita_via`, e che la gestione (③) abbia:
- riportato le 9 tapparelle alla `current_position` dello Step 1,
- riportato `water_heater.boiler_notte` al modo dello Step 1 (es. `PROGRAM`), `switch.ariston_power_2`/`switch.boiler_giorno` allo stato dello Step 1,
- riattivato `buongiorno` + le 2 schedule boiler giorno (stato `on`),
- disattivato il mirror (`off`),
- `input_boolean.modalita_via` → `off`.

- [ ] **Step 5: Testare l'uscita manuale**

Riattivare `input_boolean.modalita_via` (on) → attendere ① → poi spegnerlo a mano (off) senza pre-heat.
Verificare che il ripristino (③) funzioni anche senza pre-heat avvenuto (scene boiler ripristina comunque lo stato originale).

- [ ] **Step 6: Confermare lo stato finale = stato iniziale**

Confrontare con lo Step 1: boiler, prese e 9 tapparelle devono coincidere. Bilo invariato.

- [ ] **Step 7: Commit di automations.yaml**

Riallineare il file git-tracked al runtime (le 4 automazioni nuove). Se si è usato l'MCP, scaricare/sincronizzare `automations.yaml` aggiornato nel repo, poi:
```bash
git add homeassistant/automations.yaml
git commit -m "Add modalità via automations (gestione, pre-heat, rientro, mirror)"
```

---

## Self-review (esito)

**Copertura spec:** helper (T1), scene snapshot (T3 runtime), 4 automazioni (T2–T5), dashboard (T6), bilo escluso (costanti + T7 step 2/4 di verifica), anti-legionella assente (nessun BOOST/legionella in T3/T4), trigger nativo rientro (T5), template pre-heat (T4), casi limite rientro vuoto/passato (gestiti da `ts > 0` nel template e dalla condizione su `time at`). ✓

**Placeholder:** nessuno; tutti i config sono completi.

**Coerenza nomi:** entity_id e id automazioni coerenti tra i task; il mirror è creato (T2) prima di essere referenziato (T3 turn_off, T4 turn_on). Gli helper (T1) precedono ogni riferimento. ✓

**Rischio noto:** l'entity_id reale degli helper va confermato in T1 step 2 e propagato se differisce.

---

## Esito esecuzione (2026-05-29)

Eseguito via API diretta (MCP bloccato da macOS): helper via WebSocket, automazioni via REST config API (`POST /api/config/automation/config/<id>`). Tutto su casa principale, bilo mai toccato (verificato in test).

**entity_id reali** (HA li deriva dall'alias, non dal config id):
- `automation.modalita_via_gestione`, `automation.modalita_via_mirror_boiler_giorno` (= config id)
- `automation.modalita_via_pre_heat` (config id `modalita_via_preheat`)
- `automation.modalita_via_rientro_programmato` (config id `modalita_via_rientro`)
- I riferimenti incrociati usano solo `...mirror_boiler_giorno`, che coincide → nessun fixup.

**Fix emerso dal test:** `scene.turn_on` non ripristina l'`operation_mode` del `water_heater` Ariston. Aggiunto helper `input_text.modalita_via_boiler_mode` (backup in ①) + `water_heater.set_operation_mode` esplicito in ③. `water_heater.turn_off` resta un no-op: lo spegnimento reale è `switch.ariston_power_2` off.

**Test live end-to-end superato:** attivazione (boiler off, tapparelle 50%, automazioni sospese, scene create), pre-heat (power_2 on, boiler MANUAL, mirror on), rientro (modalità off, tapparelle 100%, automazioni on, boiler tornato a PROGRAM, mirror off). Stato finale = baseline. Bilo invariato per l'intero test.
