(() => {
  "use strict";

  document.querySelectorAll(".confirm-delete").forEach((form) => {
    form.addEventListener("submit", (event) => {
      if (!window.confirm(form.dataset.confirm || "Delete this item?")) {
        event.preventDefault();
      }
    });
  });

  const selectForm = document.getElementById("select-form");
  if (selectForm) {
    const boxes = [...selectForm.querySelectorAll('input[name="files"]')];
    const all = document.getElementById("select-all");
    const button = document.getElementById("dl-selected");
    const count = document.getElementById("sel-count");

    const updateSelection = () => {
      const selected = boxes.filter((box) => box.checked).length;
      count.textContent = selected;
      button.disabled = selected === 0;
      all.checked = selected === boxes.length;
      all.indeterminate = selected > 0 && selected < boxes.length;
      boxes.forEach((box) => {
        box.closest(".media-card").classList.toggle("selected", box.checked);
      });
    };

    boxes.forEach((box) => box.addEventListener("change", updateSelection));
    all.addEventListener("change", () => {
      boxes.forEach((box) => {
        box.checked = all.checked;
      });
      updateSelection();
    });
    updateSelection();
  }

  const lightbox = document.getElementById("lightbox");
  const mediaCards = [...document.querySelectorAll(".media-card")];
  if (lightbox && mediaCards.length) {
    const image = lightbox.querySelector(".lightbox-stage img");
    const video = lightbox.querySelector(".lightbox-stage video");
    const name = lightbox.querySelector(".lightbox-name");
    const position = lightbox.querySelector(".lightbox-position");
    const download = lightbox.querySelector(".lightbox-download");
    const deleteForm = lightbox.querySelector(".lightbox-delete");
    const closeButton = lightbox.querySelector(".lightbox-close");
    let current = 0;
    let previousFocus = null;

    const stopVideo = () => {
      video.pause();
      video.removeAttribute("src");
      video.load();
    };

    const show = (index) => {
      current = (index + mediaCards.length) % mediaCards.length;
      const data = mediaCards[current].dataset;
      name.textContent = data.name;
      position.textContent =
        String(current + 1) +
        " of " +
        String(mediaCards.length) +
        " · " +
        (data.kind === "video" ? "Video" : "Photo");
      download.href = data.download;
      if (deleteForm) deleteForm.action = data.delete;

      if (data.kind === "video") {
        image.hidden = true;
        image.removeAttribute("src");
        video.src = data.preview;
        video.hidden = false;
      } else {
        stopVideo();
        video.hidden = true;
        image.src = data.preview;
        image.alt = data.name;
        image.hidden = false;
      }

      lightbox.hidden = false;
      document.body.classList.add("no-scroll");
      closeButton.focus();
    };

    const close = () => {
      if (lightbox.hidden) return;
      stopVideo();
      image.removeAttribute("src");
      lightbox.hidden = true;
      document.body.classList.remove("no-scroll");
      if (previousFocus) previousFocus.focus();
    };

    mediaCards.forEach((card, index) => {
      card.querySelector(".media-open").addEventListener("click", (event) => {
        previousFocus = event.currentTarget;
        show(index);
      });
    });
    closeButton.addEventListener("click", close);
    lightbox.querySelector("[data-close-lightbox]").addEventListener("click", close);
    lightbox.querySelector(".lightbox-prev").addEventListener("click", () => show(current - 1));
    lightbox.querySelector(".lightbox-next").addEventListener("click", () => show(current + 1));

    document.addEventListener("keydown", (event) => {
      if (lightbox.hidden) return;
      if (event.key === "Escape") close();
      if (event.key === "ArrowLeft") show(current - 1);
      if (event.key === "ArrowRight") show(current + 1);
    });
  }

  const uploadForm = document.getElementById("upload-form");
  if (uploadForm) {
    const input = uploadForm.querySelector('input[type="file"]');
    const button = uploadForm.querySelector('button[type="submit"]');
    const progress = uploadForm.querySelector("progress");
    const status = uploadForm.querySelector(".upload-status");

    uploadForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      const files = [...input.files];
      if (!files.length) return;

      button.disabled = true;
      input.disabled = true;
      progress.hidden = false;
      progress.max = files.length;
      progress.value = 0;
      let saved = 0;
      const skipped = [];

      try {
        // One file per request keeps large videos below the configured request limit.
        for (let index = 0; index < files.length; index += 1) {
          status.textContent =
            "Uploading " + String(index + 1) + " of " + String(files.length) + "…";
          const payload = new FormData();
          payload.append("csrf", uploadForm.querySelector('[name="csrf"]').value);
          payload.append("media", files[index]);

          const response = await fetch(uploadForm.action, {
            method: "POST",
            body: payload,
            headers: { "X-Requested-With": "XMLHttpRequest" },
          });
          const result = await response.json().catch(() => ({}));
          if (!response.ok) {
            throw new Error(result.error || "Upload failed (" + String(response.status) + ")");
          }
          saved += result.saved || 0;
          skipped.push(...(result.skipped || []));
          progress.value = index + 1;
        }

        status.textContent = skipped.length
          ? "Uploaded " + String(saved) + ". Skipped: " + skipped.join("; ")
          : "Uploaded " + String(saved) + " file" + (saved === 1 ? "" : "s") + ". Refreshing…";
        window.setTimeout(() => window.location.reload(), skipped.length ? 1800 : 450);
      } catch (error) {
        status.textContent = error.message;
        status.classList.add("error-text");
        button.disabled = false;
        input.disabled = false;
      }
    });
  }
})();
