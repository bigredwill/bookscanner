// Track previous image count to avoid unnecessary updates
let previousImageCount = 0;
let currentViewingSession = null; // null means viewing current session

// Initialize Socket.IO connection
const socket = io();

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
      galleryHTML += `
            <div class="image-item">
                <img src="/img/${img.filename}" alt="${img.filename}">
                <div class="fileinfo">${img.filename}<br>${img.size}</div>
            </div>`;
    }
    gallery.innerHTML = galleryHTML;
    previousImageCount = data.image_count;
  }
});

function updateGallery() {
  fetch("/api/gallery-data")
    .then((r) => r.json())
    .then((data) => {
      // Update header info (camera ports, serials, session info)
      document.getElementById("left-port").textContent = data.left_cam_port;
      document.getElementById("right-port").textContent = data.right_cam_port;
      document.getElementById("left-serial").textContent =
        "Serial: " + data.left_cam_serial;
      document.getElementById("right-serial").textContent =
        "Serial: " + data.right_cam_serial;
      document.getElementById("session-name").textContent =
        data.session_name || "-";

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
          galleryHTML += `
                    <div class="image-item">
                        <img src="/img/${img.filename}" alt="${img.filename}">
                        <div class="fileinfo">${img.filename}<br>${img.size}</div>
                    </div>`;
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
        galleryHTML += `
                <div class="image-item">
                    <img src="/img/${sessionName}/${img.filename}" alt="${img.filename}">
                    <div class="fileinfo">${img.filename}<br>${img.size}</div>
                </div>`;
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
      document.getElementById("left-serial").textContent =
        "Serial: " + data.left.serial;
      document.getElementById("right-serial").textContent =
        "Serial: " + data.right.serial;
      btn.disabled = false;
      btn.textContent = "Refresh Serials";
    })
    .catch((e) => {
      console.log("Error querying serials:", e);
      btn.disabled = false;
      btn.textContent = "Retry";
    });
}

// Initial load and periodic refresh every 5 seconds (WebSocket handles real-time updates)
updateGallery();
setInterval(updateGallery, 5000);
