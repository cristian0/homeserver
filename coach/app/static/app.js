(() => {
  if (document.documentElement && document.documentElement.classList) document.documentElement.classList.add("js");
  const page = document.querySelector("[data-session-id]");
  const csrf = document.querySelector('meta[name="csrf-token"]');

  if (page && page.dataset.completionEnabled === "true") {
    const error = document.querySelector("[data-completion-error]");
    const progressText = document.querySelector("[data-progress-text]");
    const progress = document.querySelector("[data-progress]");
    const checkboxes = Array.from(page.querySelectorAll('input[type="checkbox"]'));
    let confirmedIds = new Set(checkboxes.filter((item) => item.checked).map((item) => item.value));
    let desiredIds = new Set(confirmedIds);
    let saveInFlight = false;

    // Modalità "esercizio in corso": un esercizio alla volta, per seguirlo senza distrazioni.
    const rows = Array.from(page.querySelectorAll(".exercise-item"));
    const rowCheckbox = (row) => row.querySelector('input[type="checkbox"]');
    const firstUncheckedIndex = () => {
      if (!rows.length) return -1;
      const index = rows.findIndex((row) => !rowCheckbox(row).checked);
      return index === -1 ? rows.length - 1 : index;
    };
    const segments = Array.from(document.querySelectorAll("[data-seg] span"));
    const continueButton = document.querySelector("[data-focus-enter]");
    const feedbackCta = document.querySelector("[data-feedback-cta]");
    const currentIndexLabel = document.querySelector("[data-focus-current-index]");
    const currentNameLabel = document.querySelector("[data-focus-current-name]");
    const allDone = () => rows.length > 0 && rows.every((row) => rowCheckbox(row).checked);
    const renderSegments = (currentIndex) => {
      segments.forEach((segment, i) => {
        const done = rows[i] ? rowCheckbox(rows[i]).checked : false;
        segment.className = done ? "on" : (i === currentIndex ? "cur" : "");
      });
    };
    const renderListBar = () => {
      const done = allDone();
      const index = firstUncheckedIndex();
      const name = rows[index] ? rows[index].querySelector(".item-name") : null;
      if (currentIndexLabel) currentIndexLabel.textContent = String(index + 1);
      if (currentNameLabel) currentNameLabel.textContent = name ? name.textContent : "";
      if (continueButton) continueButton.hidden = done;
      if (feedbackCta) feedbackCta.hidden = !done;
    };
    const highlightCurrent = () => {
      const index = allDone() ? -1 : firstUncheckedIndex();
      rows.forEach((row, i) => row.classList.toggle("is-current", i === index));
      renderSegments(index);
      renderListBar();
    };

    const selectedIds = () => checkboxes.filter((item) => item.checked).map((item) => item.value);
    const sameSelection = (first, second) => first.size === second.size && [...first].every((item) => second.has(item));
    document.querySelectorAll('a[href^="/"], form').forEach((control) => {
      control.addEventListener(control.tagName === "FORM" ? "submit" : "click", (event) => {
        if (saveInFlight || !sameSelection(desiredIds, confirmedIds)) {
          event.preventDefault();
          error.textContent = "Attendi il salvataggio delle spunte prima di continuare.";
          error.hidden = false;
        }
      });
    });
    const restoreConfirmedUi = () => {
      checkboxes.forEach((item) => { item.checked = confirmedIds.has(item.value); });
      progressText.textContent = `${confirmedIds.size} di ${checkboxes.length} completati`;
      progress.value = confirmedIds.size;
      progress.max = checkboxes.length;
    };

    const saveLatestSelection = async () => {
      if (saveInFlight) return;
      saveInFlight = true;
      const snapshot = new Set(desiredIds);
      let saveSucceeded = false;
      try {
        const response = await fetch(`/sessions/${encodeURIComponent(page.dataset.sessionId)}/completion`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-CSRFToken": csrf ? csrf.content : "",
          },
          body: JSON.stringify({ completed_item_ids: checkboxes.filter((item) => snapshot.has(item.value)).map((item) => item.value) }),
        });
        let payload = null;
        try {
          payload = await response.json();
        } catch (_parseError) {
          // Error pages and network intermediaries may not return JSON.
        }
        if (!response.ok) {
          throw new Error(payload && typeof payload.error === "string" ? payload.error : "Impossibile salvare la spunta.");
        }
        confirmedIds = snapshot;
        progressText.textContent = `${payload.completed} di ${payload.total} completati`;
        progress.value = payload.completed;
        progress.max = payload.total;
        error.hidden = true;
        saveSucceeded = true;
      } catch (_saveError) {
        desiredIds = new Set(confirmedIds);
        restoreConfirmedUi();
        error.textContent = "Impossibile salvare la spunta. Riprova.";
        error.hidden = false;
      } finally {
        saveInFlight = false;
      }
      if (saveSucceeded && !sameSelection(snapshot, desiredIds)) saveLatestSelection();
    };

    checkboxes.forEach((checkbox) => {
      checkbox.addEventListener("change", () => {
        desiredIds = new Set(selectedIds());
        saveLatestSelection();
        if (page.dataset.view !== "focus") highlightCurrent();
      });
    });

    const focusPosition = document.querySelector("[data-focus-position]");
    const focusSection = document.querySelector("[data-focus-section]");
    let focusIndex = -1;

    const renderFocus = () => {
      rows.forEach((row, index) => row.classList.toggle("is-current", index === focusIndex));
      renderSegments(focusIndex);
      if (focusPosition) focusPosition.textContent = rows.length ? `${focusIndex + 1} di ${rows.length}` : "";
      const current = rows[focusIndex];
      if (focusSection) focusSection.textContent = current ? (current.dataset.section || "") : "";
      window.scrollTo(0, 0);
    };

    const enterFocus = (index) => {
      if (!rows.length) return;
      focusIndex = typeof index === "number" ? index : firstUncheckedIndex();
      page.dataset.view = "focus";
      document.body.dataset.focusMode = "on";
      renderFocus();
    };

    const exitFocus = () => {
      page.dataset.view = "list";
      document.body.removeAttribute("data-focus-mode");
      highlightCurrent();
    };

    const move = (delta) => {
      if (!rows.length) return;
      focusIndex = Math.min(Math.max(focusIndex + delta, 0), rows.length - 1);
      renderFocus();
    };

    document.querySelectorAll("[data-focus-enter]").forEach((button) => button.addEventListener("click", () => enterFocus()));
    rows.forEach((row, index) => {
      const open = row.querySelector("[data-focus-open]");
      if (open) open.addEventListener("click", () => enterFocus(index));
    });
    const focusExit = document.querySelector("[data-focus-exit]");
    if (focusExit) focusExit.addEventListener("click", exitFocus);
    const focusPrev = document.querySelector("[data-focus-prev]");
    const focusNext = document.querySelector("[data-focus-next]");
    if (focusPrev) focusPrev.addEventListener("click", () => move(-1));
    if (focusNext) focusNext.addEventListener("click", () => move(1));

    const focusDone = document.querySelector("[data-focus-done]");
    if (focusDone) {
      focusDone.addEventListener("click", () => {
        const current = rows[focusIndex];
        if (!current) return;
        const checkbox = rowCheckbox(current);
        if (checkbox && !checkbox.disabled && !checkbox.checked) {
          checkbox.checked = true;
          checkbox.dispatchEvent(new Event("change", { bubbles: true }));
        }
        move(1);
      });
    }
    const focusSkip = document.querySelector("[data-focus-skip]");
    if (focusSkip) focusSkip.addEventListener("click", () => move(1));

    // Timer facoltativo e locale per le dosi a tempo: nessun dato viene salvato.
    document.querySelectorAll("[data-timer]").forEach((timer) => {
      const totalSeconds = parseInt(timer.dataset.timerSeconds, 10);
      const display = timer.querySelector("[data-timer-display]");
      const ring = timer.querySelector("[data-timer-ring]");
      const startButton = timer.querySelector("[data-timer-start]");
      const resetButton = timer.querySelector("[data-timer-reset]");
      let remaining = totalSeconds;
      let intervalId = null;
      const format = (seconds) => `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
      const render = () => {
        if (display) display.textContent = format(remaining);
        if (ring) ring.style.setProperty("--pct", String(Math.round(((totalSeconds - remaining) / totalSeconds) * 100)));
      };
      const stop = () => {
        if (intervalId !== null) { clearInterval(intervalId); intervalId = null; }
      };
      const tick = () => {
        remaining -= 1;
        render();
        if (remaining <= 0) {
          stop();
          if (startButton) startButton.textContent = "✓ Tempo finito";
        }
      };
      if (startButton) {
        startButton.addEventListener("click", () => {
          if (intervalId !== null) {
            stop();
            startButton.textContent = "▶ Riprendi";
            return;
          }
          if (remaining <= 0) remaining = totalSeconds;
          startButton.textContent = "⏸ Pausa";
          intervalId = setInterval(tick, 1000);
        });
      }
      if (resetButton) {
        resetButton.addEventListener("click", () => {
          stop();
          remaining = totalSeconds;
          if (startButton) startButton.textContent = "▶ Avvia";
          render();
        });
      }
      render();
    });
  }

  let videoFrame = null;
  let activeVideoButton = null;
  document.querySelectorAll("[data-video-embed]").forEach((button) => {
    button.addEventListener("click", () => {
      if (activeVideoButton === button && videoFrame) {
        videoFrame.hidden = !videoFrame.hidden;
        button.setAttribute("aria-expanded", String(!videoFrame.hidden));
        return;
      }
      if (!videoFrame) {
        videoFrame = document.createElement("iframe");
        videoFrame.title = "Video dimostrativo dell'esercizio";
        videoFrame.loading = "lazy";
        videoFrame.allowFullscreen = true;
        videoFrame.referrerPolicy = "strict-origin-when-cross-origin";
        videoFrame.className = "video-frame";
      }
      if (activeVideoButton) activeVideoButton.setAttribute("aria-expanded", "false");
      videoFrame.hidden = false;
      videoFrame.src = button.dataset.videoEmbed;
      button.insertAdjacentElement("afterend", videoFrame);
      button.setAttribute("aria-expanded", "true");
      activeVideoButton = button;
    });
  });

  document.querySelectorAll("form[data-confirm]").forEach((form) => {
    form.addEventListener("submit", (event) => {
      if (event.defaultPrevented) return;
      if (!window.confirm(form.dataset.confirm)) event.preventDefault();
    });
  });

  // Scala 0–10 a tessere: l'input numerico resta la sorgente del dato inviato.
  document.querySelectorAll("[data-scale-for]").forEach((scale) => {
    const input = document.getElementById(scale.dataset.scaleFor);
    if (!input) return;
    const tiles = Array.from(scale.querySelectorAll("button"));
    const sync = () => tiles.forEach((tile) => tile.setAttribute("aria-pressed", String(tile.dataset.value === input.value)));
    tiles.forEach((tile) => {
      tile.addEventListener("click", () => {
        input.value = tile.dataset.value;
        input.dispatchEvent(new Event("input", { bubbles: true }));
        sync();
      });
    });
    input.addEventListener("input", sync);
    sync();
  });

  const redWarning = document.querySelector("[data-red-warning]");
  const redFlags = Array.from(document.querySelectorAll("[data-red-flag]"));
  redFlags.forEach((flag) => {
    flag.addEventListener("change", () => {
      if (redWarning) redWarning.hidden = !redFlags.some((item) => item.checked);
    });
  });

  const summary = document.querySelector("[data-coach-summary]");
  const copyStatus = document.querySelector("[data-copy-status]");
  const copyButton = document.querySelector("[data-copy-summary]");
  const finalizeForm = document.querySelector("[data-finalize-form]");
  // Copia da una textarea di sola lettura: Clipboard API, poi execCommand, poi selezione manuale.
  const copyFrom = async (source, status, doneMessage) => {
    const setStatus = (message) => { if (status) status.textContent = message; };
    try {
      await navigator.clipboard.writeText(source.value);
      setStatus(doneMessage);
      return;
    } catch (_clipboardError) {
      // Clipboard API is often unavailable on a local HTTP connection.
    }
    source.focus();
    source.select();
    let copied = false;
    try {
      copied = document.execCommand("copy");
    } catch (_legacyCopyError) {
      // Keep the visible text selected for the browser's manual copy action.
    }
    setStatus(copied ? doneMessage : "Seleziona e copia manualmente");
  };
  const copySummary = async () => {
    if (!summary || !summary.value) {
      if (copyStatus) copyStatus.textContent = "Finalizza il feedback per ottenere il riepilogo.";
      return;
    }
    await copyFrom(summary, copyStatus, "Riepilogo copiato.");
  };
  document.querySelectorAll("[data-copy-text]").forEach((button) => {
    button.addEventListener("click", () => {
      const source = document.getElementById(button.dataset.copyTarget);
      if (!source || !source.value) {
        if (copyStatus) copyStatus.textContent = "Niente da copiare.";
        return;
      }
      return copyFrom(source, copyStatus, "Testo copiato.");
    });
  });
  if (copyButton) copyButton.addEventListener("click", copySummary);
  if (finalizeForm) {
    let finalizing = false;
    finalizeForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (finalizing || !window.confirm("Finalizzare il feedback? Tutti i dati diventeranno di sola lettura.")) return;
      finalizing = true;
      let failureMessage = "Impossibile finalizzare. Riprova.";
      copyStatus.textContent = "Finalizzazione in corso…";
      try {
        const response = await fetch(finalizeForm.action, {
          method: "POST",
          headers: { "X-CSRFToken": csrf ? csrf.content : "", "Accept": "application/json" },
          body: new FormData(finalizeForm),
        });
        const payload = await response.json();
        if (!response.ok) {
          if (payload && typeof payload.error === "string") failureMessage = payload.error;
          throw new Error(failureMessage);
        }
        if (payload.status !== "complete" || typeof payload.summary !== "string") throw new Error("Impossibile finalizzare. Riprova.");
        summary.value = payload.summary;
        summary.readOnly = true;
        summary.hidden = false;
        document.querySelectorAll("[data-session-edit-control]").forEach((control) => { control.disabled = true; });
        finalizeForm.hidden = true;
        await copySummary();
      } catch (_finalizeError) {
        copyStatus.textContent = failureMessage;
      } finally {
        finalizing = false;
      }
    });
  }
})();
