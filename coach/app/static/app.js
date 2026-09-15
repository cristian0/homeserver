(() => {
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
      });
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
  const copySummary = async () => {
    if (!summary || !summary.value) {
      if (copyStatus) copyStatus.textContent = "Finalizza il feedback per ottenere il riepilogo.";
      return;
    }
    try {
      await navigator.clipboard.writeText(summary.value);
      copyStatus.textContent = "Riepilogo copiato.";
      return;
    } catch (_clipboardError) {
      // Clipboard API is often unavailable on a local HTTP connection.
    }
    summary.focus();
    summary.select();
    let copied = false;
    try {
      copied = document.execCommand("copy");
    } catch (_legacyCopyError) {
      // Keep the visible text selected for the browser's manual copy action.
    }
    copyStatus.textContent = copied ? "Riepilogo copiato." : "Seleziona e copia manualmente";
  };
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
