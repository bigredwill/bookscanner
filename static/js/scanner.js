// Track previous image count to avoid unnecessary updates
let previousImageCount = 0;
let currentViewingSession = null; // null means viewing current session

// Debounce state for foot pedal input
let lastCaptureTime = 0;
const DEBOUNCE_MS = 500; // Minimum time between captures in milliseconds

// Initialize Socket.IO connection
const socket = io();

function formatBytes(bytes) {
  if (bytes === 0) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + " " + sizes[i];
}

function updateDiskUsage() {
  fetch("/api/disk-usage")
    .then((r) => r.json())
    .then((data) => {
      if (data.captures) {
        const local = `${formatBytes(data.captures.free)} free`;
        document.getElementById("disk-local").textContent = local;
      } else {
        document.getElementById("disk-local").textContent = "-";
      }

      if (data.usb) {
        const usb = `${formatBytes(data.usb.free)} free`;
        document.getElementById("disk-usb").textContent = usb;
      } else {
        document.getElementById("disk-usb").textContent = "not mounted";
      }
    })
    .catch((e) => console.log("Error fetching disk usage:", e));
}

function loadNotes() {
  fetch("/api/notes")
    .then((r) => r.json())
    .then((data) => {
      document.getElementById("notes-input").value = data.notes || "";
    })
    .catch((e) => console.log("Error loading notes:", e));
}

function saveNotes() {
  const notes = document.getElementById("notes-input").value;
  fetch("/api/notes", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ notes: notes }),
  })
    .then((r) => r.json())
    .then((data) => {
      if (!data.success) {
        console.log("Error saving notes:", data.error);
      }
    })
    .catch((e) => console.log("Error saving notes:", e));
}

// Add keyboard listener for 'b' key (foot pedal)
document.addEventListener("keydown", function (event) {
  // Ignore if typing in an input field
  if (event.target.tagName === "INPUT" || event.target.tagName === "TEXTAREA") {
    return;
  }
  if (event.key === "b" || event.key === "B") {
    const now = Date.now();
    if (now - lastCaptureTime >= DEBOUNCE_MS) {
      lastCaptureTime = now;
      triggerCapture();
    }
  }
});

function triggerCapture() {
  console.log("Triggering capture from webapp...");
  socket.emit("trigger_capture");
}

socket.on("connect", function () {
  console.log("WebSocket connected");
});

socket.on("disconnect", function () {
  console.log("WebSocket disconnected");
});

socket.on("status_update", function (data) {
  document.getElementById("status-text").textContent = data.text;
  document.body.style.backgroundColor = "#" + data.color;
});

socket.on("gallery_update", function (data) {
  if (!currentViewingSession) {
    document.getElementById("image-count").textContent = data.image_count;

    // Update gallery with reversed images (most recent first)
    let gallery = document.getElementById("gallery");
    let galleryHTML = "";
    for (let img of data.images.slice().reverse()) {
      galleryHTML += buildImageHTML(img, "");
    }
    gallery.innerHTML = galleryHTML;
    previousImageCount = data.image_count;
  }
});

function buildImageHTML(img, sessionPrefix) {
  let exifHTML = "";

  if (img.width && img.height) {
    exifHTML += `<div class="meta-row"><span class="meta-label">Resolution:</span> ${img.width}×${img.height} (${img.megapixels})</div>`;
  }
  if (img.camera_model) {
    exifHTML += `<div class="meta-row"><span class="meta-label">Camera:</span> ${img.camera_model}</div>`;
  }

  let settings = [];
  if (img.iso) settings.push(img.iso);
  if (img.shutter_speed) settings.push(img.shutter_speed);
  if (img.aperture) settings.push(img.aperture);
  if (img.focal_length) settings.push(img.focal_length);

  if (settings.length > 0) {
    exifHTML += `<div class="exif-data">${settings.join(" • ")}</div>`;
  }

  return `
      <div class="image-item">
          <img src="${sessionPrefix}/img/${img.filename}" alt="${img.filename}">
          <div class="fileinfo">
              <div class="meta-row"><strong>${img.filename}</strong> (${img.size})</div>
              ${exifHTML}
          </div>
      </div>`;
}

function formatBatteryLevel(level) {
  if (level === null || level === undefined) {
    return "";
  }
  let icon = "🔋";
  if (level <= 20) {
    icon = "🪫";
  }
  return `${icon} ${level}%`;
}

function updateBatteryDisplay(leftBattery, rightBattery) {
  document.getElementById("left-battery").textContent =
    formatBatteryLevel(leftBattery);
  document.getElementById("right-battery").textContent =
    formatBatteryLevel(rightBattery);
}

function refreshBatteryLevels() {
  let btn = event.target;
  btn.disabled = true;
  btn.textContent = "Checking...";

  fetch("/api/battery-levels")
    .then((r) => r.json())
    .then((data) => {
      updateBatteryDisplay(data.left.battery, data.right.battery);
      btn.disabled = false;
      btn.textContent = "Refresh Battery";
    })
    .catch((e) => {
      console.log("Error fetching battery levels:", e);
      btn.disabled = false;
      btn.textContent = "Retry";
    });
}

function updateGallery() {
  fetch("/api/gallery-data")
    .then((r) => r.json())
    .then((data) => {
      // Update header info (camera ports, serials, session info)
      document.getElementById("left-port").textContent = data.left_cam_port;
      document.getElementById("right-port").textContent = data.right_cam_port;
      document.getElementById("left-serial").textContent = data.left_cam_serial
        ? "(" + data.left_cam_serial + ")"
        : "";
      document.getElementById("right-serial").textContent =
        data.right_cam_serial ? "(" + data.right_cam_serial + ")" : "";
      document.getElementById("session-name").textContent =
        data.session_name || "-";

      // Update battery levels
      updateBatteryDisplay(data.left_cam_battery, data.right_cam_battery);

      // Update session metadata
      if (data.metadata) {
        let metaHTML = "";
        if (data.metadata.magazine_name) {
          metaHTML += `📖 ${data.metadata.magazine_name} `;
        }
        if (data.metadata.scanner_person) {
          metaHTML += `👤 ${data.metadata.scanner_person}`;
        }
        document.getElementById("session-metadata").innerHTML = metaHTML;
      }

      // Initial gallery load only (WebSocket handles updates)
      if (
        !currentViewingSession &&
        previousImageCount === 0 &&
        data.image_count > 0
      ) {
        previousImageCount = data.image_count;
        let gallery = document.getElementById("gallery");
        let galleryHTML = "";
        for (let img of data.images.slice().reverse()) {
          galleryHTML += buildImageHTML(img, "");
        }
        gallery.innerHTML = galleryHTML;
        document.getElementById("image-count").textContent = data.image_count;
      }
    })
    .catch((e) => console.log("Error fetching gallery data:", e));
}

function toggleSessionBrowser() {
  let browser = document.getElementById("session-browser");
  if (browser.style.display === "none") {
    browser.style.display = "block";
    loadSessions();
  } else {
    browser.style.display = "none";
  }
}

function loadSessions() {
  fetch("/api/sessions")
    .then((r) => r.json())
    .then((data) => {
      let sessionList = document.getElementById("session-list");
      let html = "";

      if (data.sessions.length === 0) {
        html = "<p>No sessions found.</p>";
      } else {
        for (let session of data.sessions) {
          let currentBadge = session.is_current
            ? ' <span style="color: #007bff;">(Current)</span>'
            : "";
          let currentClass = session.is_current ? "current" : "";

          html += `
                    <div class="session-item ${currentClass}" onclick="viewSession('${session.session_name}')">
                        <h3>${session.session_name}${currentBadge}</h3>
                        <div class="session-meta">
                            ${session.metadata.magazine_name || "No magazine name"} •
                            ${session.metadata.scanner_person || "Unknown scanner"} •
                            ${session.metadata.scan_date || "Unknown date"}
                        </div>
                        <div class="session-stats">📷 ${session.image_count} images</div>
                    </div>`;
        }
      }

      sessionList.innerHTML = html;
    })
    .catch((e) => console.log("Error loading sessions:", e));
}

function viewSession(sessionName) {
  currentViewingSession = sessionName;
  toggleSessionBrowser();

  fetch(`/api/session/${sessionName}/images`)
    .then((r) => r.json())
    .then((data) => {
      let gallery = document.getElementById("gallery");
      let galleryHTML = "";

      // Reverse the array to show most recent first
      for (let img of data.images.slice().reverse()) {
        galleryHTML += buildImageHTML(img, `/${sessionName}`);
      }

      gallery.innerHTML = galleryHTML;
      document.getElementById("session-name").textContent =
        sessionName + " (Viewing)";
    })
    .catch((e) => console.log("Error loading session images:", e));
}

function querySerials() {
  let btn = event.target;
  btn.disabled = true;
  btn.textContent = "Querying...";

  fetch("/api/camera-info")
    .then((r) => r.json())
    .then((data) => {
      document.getElementById("left-serial").textContent = data.left.serial
        ? "(" + data.left.serial + ")"
        : "";
      document.getElementById("right-serial").textContent = data.right.serial
        ? "(" + data.right.serial + ")"
        : "";
      btn.disabled = false;
      btn.textContent = "Refresh Serials";
    })
    .catch((e) => {
      console.log("Error querying serials:", e);
      btn.disabled = false;
      btn.textContent = "Retry";
    });
}

// Initial load and periodic refresh
updateGallery();
updateDiskUsage();
loadNotes();
setInterval(updateGallery, 5000);
setInterval(updateDiskUsage, 30000); // Disk usage every 30 seconds
