(() => {
  // ---- Select photos + download selected as zip
  const selectForm = document.getElementById("select-form");
  if (selectForm) {
    const boxes = [...selectForm.querySelectorAll('input[name="files"]')];
    const all = document.getElementById("select-all");
    const button = document.getElementById("dl-selected");
    const count = document.getElementById("sel-count");
    const update = () => {
      const n = boxes.filter((b) => b.checked).length;
      count.textContent = n;
      button.disabled = n === 0;
      all.checked = n === boxes.length;
      all.indeterminate = n > 0 && n < boxes.length;
      boxes.forEach((b) => b.closest(".photo").classList.toggle("selected", b.checked));
    };
    boxes.forEach((b) => b.addEventListener("change", update));
    all.addEventListener("change", () => {
      boxes.forEach((b) => (b.checked = all.checked));
      update();
    });
    update(); // browsers can restore checkbox state when going back
  }

  // ---- Lightbox viewer
  const lb = document.getElementById("lightbox");
  const photos = [...document.querySelectorAll(".photo")];
  if (lb && photos.length) {
    const img = lb.querySelector("img");
    const name = lb.querySelector(".lb-name");
    const download = lb.querySelector(".lb-download");
    const del = lb.querySelector(".lb-delete");
    let current = 0;

    const show = (i) => {
      current = (i + photos.length) % photos.length;
      const d = photos[current].dataset;
      img.src = d.preview;
      name.textContent = `${d.name} (${current + 1} of ${photos.length})`;
      download.href = d.download;
      if (del) del.action = d.delete;
      lb.hidden = false;
      document.body.classList.add("no-scroll");
    };
    const close = () => {
      lb.hidden = true;
      img.removeAttribute("src");
      document.body.classList.remove("no-scroll");
    };

    photos.forEach((p, i) => p.querySelector("img").addEventListener("click", () => show(i)));
    lb.querySelector(".lb-prev").addEventListener("click", () => show(current - 1));
    lb.querySelector(".lb-next").addEventListener("click", () => show(current + 1));
    lb.querySelector(".lb-close").addEventListener("click", close);
    lb.addEventListener("click", (e) => { if (e.target === lb) close(); });
    document.addEventListener("keydown", (e) => {
      if (lb.hidden) return;
      if (e.key === "Escape") close();
      else if (e.key === "ArrowLeft") show(current - 1);
      else if (e.key === "ArrowRight") show(current + 1);
    });

    let touchX = null; // swipe left/right on phones
    lb.addEventListener("touchstart", (e) => (touchX = e.touches[0].clientX), { passive: true });
    lb.addEventListener("touchend", (e) => {
      if (touchX === null) return;
      const dx = e.changedTouches[0].clientX - touchX;
      if (Math.abs(dx) > 50) show(current + (dx < 0 ? 1 : -1));
      touchX = null;
    });
  }

  // ---- Upload in small batches with a progress bar (avoids huge single requests)
  const uploadForm = document.getElementById("upload-form");
  if (uploadForm) {
    const BATCH = 5;
    const input = uploadForm.querySelector('input[type="file"]');
    const button = uploadForm.querySelector("button");
    const bar = uploadForm.querySelector("progress");
    const status = uploadForm.querySelector(".upload-status");
    const csrf = uploadForm.querySelector('input[name="csrf"]').value;

    const sendBatch = (files, onProgress) =>
      new Promise((resolve, reject) => {
        const data = new FormData();
        data.append("csrf", csrf);
        files.forEach((f) => data.append("photos", f));
        const xhr = new XMLHttpRequest();
        xhr.open("POST", uploadForm.action);
        xhr.setRequestHeader("X-Requested-With", "XMLHttpRequest");
        xhr.upload.onprogress = (e) => onProgress(e.loaded);
        xhr.onload = () => {
          let body = {};
          try { body = JSON.parse(xhr.responseText); } catch {}
          if (xhr.status === 200) resolve(body);
          else reject(new Error(body.error || `Upload failed (error ${xhr.status}).`));
        };
        xhr.onerror = () => reject(new Error("Network error — check your connection."));
        xhr.send(data);
      });

    uploadForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const files = [...input.files];
      if (!files.length) return;
      const totalBytes = files.reduce((s, f) => s + f.size, 0) || 1;
      let doneBytes = 0, saved = 0;
      const skipped = [];

      button.disabled = input.disabled = true;
      bar.hidden = false;
      try {
        for (let i = 0; i < files.length; i += BATCH) {
          const batch = files.slice(i, i + BATCH);
          status.textContent = `Uploading ${Math.min(i + BATCH, files.length)} of ${files.length}…`;
          const res = await sendBatch(batch, (loaded) => {
            bar.value = Math.min(1, (doneBytes + loaded) / totalBytes);
          });
          doneBytes += batch.reduce((s, f) => s + f.size, 0);
          saved += res.saved || 0;
          skipped.push(...(res.skipped || []));
        }
      } catch (err) {
        status.textContent = `${err.message} ${saved} uploaded before the error.`;
        button.disabled = input.disabled = false;
        return;
      }

      bar.value = 1;
      if (skipped.length) {
        status.innerHTML = "";
        status.append(`Uploaded ${saved}. Skipped: ${skipped.join(", ")}. `);
        const link = document.createElement("a");
        link.href = location.href;
        link.textContent = "Refresh page";
        status.append(link);
      } else {
        status.textContent = `Uploaded ${saved} photo${saved === 1 ? "" : "s"}.`;
        location.reload();
      }
    });
  }
})();
