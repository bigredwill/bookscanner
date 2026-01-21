#!/usr/bin/env python3
#
# Scanning script for the Noisebridge book scanner with Flask web server.
import glob
import json
import os
import re
import select
import shutil
import subprocess
import sys
import termios
import time
import tty
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Thread

from flask import Flask, jsonify, render_template, request, send_file
from flask_socketio import SocketIO, emit
from PIL import Image, ImageDraw
from PIL.ExifTags import TAGS

# Get the directory where scan.py is located (for templates/static)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

GPHOTO = "gphoto2"
IMG_FORMAT = "img%05d.jpg"
TMP_FORMAT = "tmp%05d.jpg"
PORT = 5001
CAPTURE_KEY = "b"  # Key for foot pedal capture

# Global state for the web server
scanner_state = {
    "left_cam_port": "",
    "right_cam_port": "",
    "left_cam_serial": "",
    "right_cam_serial": "",
    "left_cam_battery": None,
    "right_cam_battery": None,
    "images": [],
    "status_color": "fff",
    "status_text": "Initializing...",
    "left_cam_locked": False,  # Track if we've locked the left camera
    "right_cam_locked": False,  # Track if we've locked the right camera
}

app = Flask(
    __name__,
    template_folder=os.path.join(SCRIPT_DIR, "templates"),
    static_folder=os.path.join(SCRIPT_DIR, "static"),
)

# Initialize SocketIO
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

# Global state for web-triggered captures
scanner_state["capture_requested"] = False


def emit_status_update(message, color=None):
    """Emit a status update via WebSocket."""
    if color:
        scanner_state["status_color"] = color
    scanner_state["status_text"] = message
    socketio.emit(
        "status_update",
        {"text": message, "color": color or scanner_state["status_color"]},
    )


def emit_gallery_update():
    """Emit gallery update via WebSocket."""
    update_image_list()
    images_data = []
    for img in sorted(scanner_state["images"]):
        img_metadata = get_image_metadata(img)
        images_data.append(img_metadata)

    socketio.emit(
        "gallery_update",
        {"images": images_data, "image_count": len(scanner_state["images"])},
    )


@app.route("/img/<filename>")
def serve_image(filename):
    """Serve images from current session directory."""
    try:
        return send_file(os.path.join(os.getcwd(), filename), mimetype="image/jpeg")
    except FileNotFoundError:
        return "Image not found", 404


@app.route("/img/<session_name>/<filename>")
def serve_session_image(session_name, filename):
    """Serve images from a specific session directory."""
    try:
        captures_dir = os.path.join(SCRIPT_DIR, "captures")
        session_path = os.path.join(captures_dir, session_name)
        image_path = os.path.join(session_path, filename)

        # Security: ensure we're still within captures directory
        if not os.path.abspath(image_path).startswith(os.path.abspath(captures_dir)):
            return "Invalid path", 403

        return send_file(image_path, mimetype="image/jpeg")
    except FileNotFoundError:
        return "Image not found", 404


@app.route("/api/camera-info")
def api_camera_info():
    """Query camera serial numbers and battery levels."""
    result = {
        "left": {
            "port": scanner_state["left_cam_port"],
            "serial": scanner_state["left_cam_serial"],
            "battery": scanner_state["left_cam_battery"],
        },
        "right": {
            "port": scanner_state["right_cam_port"],
            "serial": scanner_state["right_cam_serial"],
            "battery": scanner_state["right_cam_battery"],
        },
        "error": None,
        "status": "Using cached data",
    }

    # Only query if we don't have serials yet
    if not scanner_state["left_cam_serial"] or not scanner_state["right_cam_serial"]:
        result["status"] = "Querying (this may take a moment)..."
        try:
            # Query left camera only
            if scanner_state["left_cam_port"] and not scanner_state["left_cam_serial"]:
                try:
                    output = subprocess.check_output(
                        [GPHOTO, "--port", scanner_state["left_cam_port"], "--summary"],
                        timeout=3,
                        stderr=subprocess.DEVNULL,
                    ).decode()
                    serial_match = re.search(r"Serial Number:\s+(.+)", output)
                    if serial_match:
                        serial = serial_match.group(1).strip()
                        scanner_state["left_cam_serial"] = serial
                        result["left"]["serial"] = serial
                except subprocess.TimeoutExpired:
                    result["left"]["serial"] = "Timeout - try later"
                except Exception as e:
                    result["left"]["serial"] = "Unavailable"

            # Query right camera only
            if (
                scanner_state["right_cam_port"]
                and not scanner_state["right_cam_serial"]
            ):
                try:
                    output = subprocess.check_output(
                        [
                            GPHOTO,
                            "--port",
                            scanner_state["right_cam_port"],
                            "--summary",
                        ],
                        timeout=3,
                        stderr=subprocess.DEVNULL,
                    ).decode()
                    serial_match = re.search(r"Serial Number:\s+(.+)", output)
                    if serial_match:
                        serial = serial_match.group(1).strip()
                        scanner_state["right_cam_serial"] = serial
                        result["right"]["serial"] = serial
                except subprocess.TimeoutExpired:
                    result["right"]["serial"] = "Timeout - try later"
                except Exception as e:
                    result["right"]["serial"] = "Unavailable"

            result["status"] = "Query complete"
        except Exception as e:
            result["error"] = str(e)

    return json.dumps(result)


@app.route("/api/disk-usage")
def api_disk_usage():
    """Get disk usage for captures directory and USB backup."""

    def get_usage(path):
        """Get disk usage for a path, returns None if path doesn't exist."""
        if not os.path.exists(path):
            return None
        try:
            usage = shutil.disk_usage(path)
            return {
                "total": usage.total,
                "used": usage.used,
                "free": usage.free,
                "percent_used": round(usage.used / usage.total * 100, 1),
            }
        except Exception:
            return None

    captures_path = os.path.join(SCRIPT_DIR, "captures")
    usb_path = "/mnt/usb"

    result = {
        "captures": get_usage(captures_path),
        "captures_path": captures_path,
        "usb": get_usage(usb_path),
        "usb_path": usb_path,
    }

    return json.dumps(result)


@app.route("/api/battery-levels")
def api_battery_levels():
    """Query battery levels for both cameras."""
    result = {
        "left": {"port": scanner_state["left_cam_port"], "battery": None},
        "right": {"port": scanner_state["right_cam_port"], "battery": None},
        "error": None,
    }

    try:
        # Query left camera battery
        if scanner_state["left_cam_port"]:
            battery = get_battery_level(scanner_state["left_cam_port"])
            scanner_state["left_cam_battery"] = battery
            result["left"]["battery"] = battery

        # Query right camera battery
        if scanner_state["right_cam_port"]:
            battery = get_battery_level(scanner_state["right_cam_port"])
            scanner_state["right_cam_battery"] = battery
            result["right"]["battery"] = battery
    except Exception as e:
        result["error"] = str(e)

    return json.dumps(result)


@app.route("/api/notes", methods=["GET", "POST"])
def api_notes():
    """Get or update scan notes."""
    if request.method == "GET":
        notes = scanner_state.get("metadata", {}).get("notes", "")
        return json.dumps({"notes": notes})

    elif request.method == "POST":
        data = request.get_json()
        notes = data.get("notes", "")

        # Update in-memory metadata
        if "metadata" in scanner_state:
            scanner_state["metadata"]["notes"] = notes

            # Save to metadata file
            metadata_file = os.path.join(
                scanner_state.get("session_dir", ""), "scan_metadata.json"
            )
            if metadata_file and os.path.exists(os.path.dirname(metadata_file)):
                try:
                    with open(metadata_file, "w") as f:
                        json.dump(scanner_state["metadata"], f, indent=2)
                    return json.dumps({"success": True})
                except Exception as e:
                    return json.dumps({"success": False, "error": str(e)})

        return json.dumps({"success": False, "error": "No active session"})


@app.route("/api/gallery-data")
def api_gallery_data():
    """Return gallery data as JSON."""
    images_data = []
    for img in sorted(scanner_state["images"]):
        img_metadata = get_image_metadata(img)
        images_data.append(img_metadata)

    return json.dumps(
        {
            "left_cam_port": scanner_state["left_cam_port"],
            "right_cam_port": scanner_state["right_cam_port"],
            "left_cam_serial": scanner_state["left_cam_serial"],
            "right_cam_serial": scanner_state["right_cam_serial"],
            "left_cam_battery": scanner_state["left_cam_battery"],
            "right_cam_battery": scanner_state["right_cam_battery"],
            "images": images_data,
            "status_color": scanner_state["status_color"],
            "status_text": scanner_state["status_text"],
            "image_count": len(scanner_state["images"]),
            "session_name": scanner_state.get("session_name", ""),
            "metadata": scanner_state.get("metadata", {}),
        }
    )


@app.route("/api/sessions")
def api_sessions():
    """Return list of all capture sessions."""
    captures_dir = os.path.join(SCRIPT_DIR, "captures")
    sessions = []

    if os.path.exists(captures_dir):
        for session_name in sorted(os.listdir(captures_dir), reverse=True):
            session_path = os.path.join(captures_dir, session_name)
            if os.path.isdir(session_path):
                metadata_file = os.path.join(session_path, "scan_metadata.json")
                metadata = {}
                if os.path.exists(metadata_file):
                    try:
                        with open(metadata_file, "r") as f:
                            metadata = json.load(f)
                    except:
                        pass

                # Count images in session
                image_files = glob.glob(os.path.join(session_path, "img*.jpg"))

                sessions.append(
                    {
                        "session_name": session_name,
                        "metadata": metadata,
                        "image_count": len(image_files),
                        "is_current": session_name
                        == scanner_state.get("session_name", ""),
                    }
                )

    return json.dumps({"sessions": sessions})


@app.route("/api/session/<session_name>/images")
def api_session_images(session_name):
    """Return images for a specific session."""
    captures_dir = os.path.join(SCRIPT_DIR, "captures")
    session_path = os.path.join(captures_dir, session_name)

    if not os.path.exists(session_path):
        return json.dumps({"error": "Session not found"}), 404

    images_data = []
    image_files = sorted(glob.glob(os.path.join(session_path, "img*.jpg")))

    for img_path in image_files:
        img_metadata = get_image_metadata(img_path)
        images_data.append(img_metadata)

    return json.dumps({"images": images_data, "session_name": session_name})


@socketio.on("trigger_capture")
def handle_capture_trigger():
    """Handle capture request from web interface."""
    scanner_state["capture_requested"] = True
    emit_status_update("Capture requested from web...", "ff9")
    return {"status": "ok"}


@app.route("/")
def index():
    """Serve the main scanner interface."""
    return render_template("index.html")


@app.route("/crop")
def crop_interface():
    """Serve the crop interface."""
    return render_template("crop.html")


@app.route("/api/crop-settings", methods=["GET", "POST"])
def api_crop_settings():
    """Get or save crop settings for a session."""
    # Allow session to be specified via query parameter
    session_name = request.args.get("session")

    if session_name:
        captures_dir = os.path.join(SCRIPT_DIR, "captures")
        session_dir = os.path.join(captures_dir, session_name)
        if not os.path.isdir(session_dir):
            return jsonify({"status": "error", "message": "Session not found"}), 404
    else:
        session_dir = scanner_state.get("session_dir", os.getcwd())

    crop_file = os.path.join(session_dir, "crop_settings.json")

    if request.method == "POST":
        # Save crop settings
        crop_data = request.get_json()
        try:
            with open(crop_file, "w") as f:
                json.dump(crop_data, f, indent=2)
            return jsonify({"status": "ok", "message": "Crop settings saved"})
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500

    else:
        # Load crop settings
        if os.path.exists(crop_file):
            try:
                with open(crop_file, "r") as f:
                    crop_data = json.load(f)
                return jsonify(crop_data)
            except Exception as e:
                return jsonify({"status": "error", "message": str(e)}), 500
        else:
            return jsonify({"status": "none", "message": "No crop settings found"})


@app.route("/api/crop-preview", methods=["POST"])
def api_crop_preview():
    """Generate a crop preview image with the given coordinates."""
    data = request.get_json()
    image_filename = data.get("image")
    crop_box = data.get("crop")
    session_name = data.get("session")

    if not image_filename or not crop_box:
        return jsonify(
            {"status": "error", "message": "Missing image or crop data"}
        ), 400

    if session_name:
        captures_dir = os.path.join(SCRIPT_DIR, "captures")
        session_dir = os.path.join(captures_dir, session_name)
        if not os.path.isdir(session_dir):
            return jsonify({"status": "error", "message": "Session not found"}), 404
    else:
        session_dir = scanner_state.get("session_dir", os.getcwd())

    image_path = os.path.join(session_dir, image_filename)

    if not os.path.exists(image_path):
        return jsonify({"status": "error", "message": "Image not found"}), 404

    try:
        # Open image and draw crop rectangle
        img = Image.open(image_path)
        draw = ImageDraw.Draw(img)

        # Draw red rectangle
        left = crop_box.get("left", 0)
        top = crop_box.get("top", 0)
        right = crop_box.get("right", img.width)
        bottom = crop_box.get("bottom", img.height)

        draw.rectangle([left, top, right, bottom], outline="red", width=10)

        # Save preview
        preview_filename = image_filename.replace(".jpg", "_crop_preview.jpg")
        preview_path = os.path.join(session_dir, preview_filename)
        img.save(preview_path, quality=95)

        return jsonify(
            {
                "status": "ok",
                "preview_image": preview_filename,
                "message": "Preview generated",
            }
        )

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/apply-crop", methods=["POST"])
def api_apply_crop():
    """Apply crop to all images in the session."""
    data = request.get_json()
    crop_box = data.get("crop")
    session_name = data.get("session")

    if not crop_box:
        return jsonify({"status": "error", "message": "Missing crop data"}), 400

    if session_name:
        captures_dir = os.path.join(SCRIPT_DIR, "captures")
        session_dir = os.path.join(captures_dir, session_name)
        if not os.path.isdir(session_dir):
            return jsonify({"status": "error", "message": "Session not found"}), 404
    else:
        session_dir = scanner_state.get("session_dir", os.getcwd())

    # Find all images
    images = sorted(glob.glob(os.path.join(session_dir, "img*.jpg")))

    if not images:
        return jsonify({"status": "error", "message": "No images found"}), 404

    # Create output directory
    output_dir = os.path.join(session_dir, "cropped")
    os.makedirs(output_dir, exist_ok=True)

    try:
        left = crop_box.get("left", 0)
        top = crop_box.get("top", 0)
        right = crop_box.get("right")
        bottom = crop_box.get("bottom")

        cropped_count = 0
        for img_path in images:
            img = Image.open(img_path)
            cropped = img.crop((left, top, right, bottom))

            basename = os.path.basename(img_path)
            output_path = os.path.join(
                output_dir, basename.replace(".jpg", "_cropped.jpg")
            )
            cropped.save(output_path, quality=95)
            cropped_count += 1

        return jsonify(
            {
                "status": "ok",
                "message": f"Cropped {cropped_count} images",
                "output_dir": "cropped",
            }
        )

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


def get_file_size(filename):
    """Get file size in MB."""
    try:
        if os.path.exists(filename):
            size_bytes = os.path.getsize(filename)
            size_mb = size_bytes / (1024 * 1024)
            return f"{size_mb:.2f} MB"
    except:
        pass
    return "N/A"


def get_image_metadata(image_path):
    """Extract detailed metadata from image including EXIF data."""
    metadata = {
        "filename": os.path.basename(image_path),
        "size": get_file_size(image_path),
        "width": None,
        "height": None,
        "camera_make": None,
        "camera_model": None,
        "iso": None,
        "shutter_speed": None,
        "aperture": None,
        "focal_length": None,
        "date_taken": None,
    }

    try:
        with Image.open(image_path) as img:
            # Get basic dimensions
            metadata["width"] = img.width
            metadata["height"] = img.height
            metadata["megapixels"] = f"{(img.width * img.height) / 1000000:.1f} MP"

            # Extract EXIF data
            exif_data = img.getexif()
            if exif_data:
                for tag_id, value in exif_data.items():
                    tag = TAGS.get(tag_id, tag_id)

                    if tag == "Make":
                        metadata["camera_make"] = str(value).strip()
                    elif tag == "Model":
                        metadata["camera_model"] = str(value).strip()
                    elif tag == "ISOSpeedRatings":
                        metadata["iso"] = f"ISO {value}"
                    elif tag == "ExposureTime":
                        # Convert to fraction
                        if isinstance(value, tuple):
                            metadata["shutter_speed"] = f"{value[0]}/{value[1]}s"
                        else:
                            metadata["shutter_speed"] = f"{value}s"
                    elif tag == "FNumber":
                        if isinstance(value, tuple):
                            f_num = value[0] / value[1]
                            metadata["aperture"] = f"f/{f_num:.1f}"
                        else:
                            metadata["aperture"] = f"f/{value:.1f}"
                    elif tag == "FocalLength":
                        if isinstance(value, tuple):
                            fl = value[0] / value[1]
                            metadata["focal_length"] = f"{fl:.0f}mm"
                        else:
                            metadata["focal_length"] = f"{value:.0f}mm"
                    elif tag == "DateTimeOriginal" or tag == "DateTime":
                        if not metadata["date_taken"]:
                            metadata["date_taken"] = str(value)
    except Exception as e:
        print(f"Error extracting metadata from {image_path}: {e}")

    return metadata


def get_battery_level(port):
    """Get battery level for a camera via gphoto2 config."""
    try:
        output = subprocess.check_output(
            [GPHOTO, f"--port={port}", "--get-config", "/main/status/batterylevel"],
            timeout=3,
            stderr=subprocess.DEVNULL,
        ).decode()
        # Parse output like "Current: 100%" or "Current: 67%"
        match = re.search(r"Current:\s*(\d+)%?", output)
        if match:
            return int(match.group(1))
        # Some cameras return text like "Low", "Half", "Full"
        text_match = re.search(r"Current:\s*(.+)", output)
        if text_match:
            level_text = text_match.group(1).strip().lower()
            # Map common text values to percentages
            level_map = {"low": 20, "half": 50, "full": 100, "high": 80}
            return level_map.get(level_text, None)
    except subprocess.CalledProcessError:
        # Config option may not exist on this camera
        pass
    except Exception as e:
        print(f"DEBUG: Error getting battery level for {port}: {e}")
    return None


def get_camera_info(port):
    """Get camera model and other info from gphoto2."""
    info = {"serial": None, "model": None, "manufacturer": None, "battery": None}

    try:
        # Get camera summary which contains model info
        summary = subprocess.check_output(
            [GPHOTO, f"--port={port}", "--summary"], timeout=3, stderr=subprocess.STDOUT
        ).decode()

        # Extract model
        model_match = re.search(r"Model:\s+(.+)", summary)
        if model_match:
            info["model"] = model_match.group(1).strip()

        # Extract manufacturer
        mfr_match = re.search(r"Manufacturer:\s+(.+)", summary)
        if mfr_match:
            info["manufacturer"] = mfr_match.group(1).strip()

        # Extract serial
        serial_match = re.search(r"Serial Number:\s+(.+)", summary)
        if serial_match:
            info["serial"] = serial_match.group(1).strip()

        # Get battery level
        info["battery"] = get_battery_level(port)

    except Exception as e:
        print(f"DEBUG: Error getting camera info for {port}: {e}")

    return info


def query_single_port_serial(port):
    """Query serial number for a single port."""
    try:
        camera_info = get_camera_info(port)
        if camera_info["serial"]:
            return (port, camera_info["serial"], camera_info)
        else:
            print(f"DEBUG: No serial found for {port}")
            return (port, None, camera_info)
    except Exception as e:
        print(f"DEBUG: Error querying {port}: {e}")
        return (port, None, {})


def get_all_camera_serials():
    """Get all camera ports and their serials using parallel port queries."""
    try:
        output = subprocess.check_output(
            [GPHOTO, "--auto-detect"], timeout=3, stderr=subprocess.DEVNULL
        ).decode()
        # Find all usb ports
        ports = re.findall(r"usb:\d*,\d*", output)
        print(f"DEBUG: Found ports: {ports}")

        port_serial_map = {}
        port_info_map = {}  # Store full camera info

        # Query all ports in parallel
        with ThreadPoolExecutor(max_workers=len(ports)) as executor:
            future_to_port = {
                executor.submit(query_single_port_serial, port): port for port in ports
            }
            for future in as_completed(future_to_port):
                port, serial, camera_info = future.result()
                if serial:
                    print(f"DEBUG: {port} -> {serial}")
                    if camera_info.get("model"):
                        print(f"DEBUG: Camera model: {camera_info['model']}")
                    port_serial_map[port] = serial
                    port_info_map[port] = camera_info

        # Store camera info globally for later use
        scanner_state["camera_info_map"] = port_info_map
        return port_serial_map
    except Exception as e:
        print(f"DEBUG: Error in get_all_camera_serials: {e}")
        return {}


def update_image_list():
    """Scan for all captured images."""
    scanner_state["images"] = sorted(glob.glob(IMG_FORMAT.replace("%05d", "[0-9]*")))


def snap(camera, filename):
    """Starts a process to capture and save an image with the given camera."""
    return subprocess.Popen(
        [
            GPHOTO,
            "--capture-image-and-download",
            "--force-overwrite",
            "--port",
            camera,
            "--filename",
            filename,
        ]
    )


def wait(process1, process2):
    """Wait for the two processes to end."""
    while process1.poll() is None or process2.poll() is None:
        time.sleep(0.1)
    if process1.returncode != 0 or process2.returncode != 0:
        return False
    return True


def get_cameras():
    """Detect and return the two camera ports."""
    try:
        gphoto_output = subprocess.check_output([GPHOTO, "--auto-detect"]).decode()
        cameras = re.findall(r"usb:\d*,\d*", gphoto_output)
        if len(cameras) == 2:
            return cameras
    except Exception as e:
        print(f"Error detecting cameras: {e}")
    return None


def start_web_server():
    """Start Flask-SocketIO server in background."""
    import logging

    log = logging.getLogger("werkzeug")
    log.setLevel(logging.ERROR)
    log = logging.getLogger("socketio")
    log.setLevel(logging.ERROR)
    log = logging.getLogger("engineio")
    log.setLevel(logging.ERROR)

    # Run SocketIO server
    socketio.run(
        app, host="0.0.0.0", port=PORT, allow_unsafe_werkzeug=True, use_reloader=False
    )


def getch_nonblocking():
    """Get a single character without blocking (non-blocking mode)."""
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        # Set raw mode and disable echo
        tty.setraw(sys.stdin.fileno())
        new_settings = termios.tcgetattr(fd)
        new_settings[3] = new_settings[3] & ~termios.ECHO  # Disable echo
        termios.tcsetattr(fd, termios.TCSADRAIN, new_settings)

        # Check if input is available
        rlist, _, _ = select.select([sys.stdin], [], [], 0.1)
        if rlist:
            ch = sys.stdin.read(1)
            return ch
        return None
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


def getch_blocking():
    """Get a single character with blocking (wait for input)."""
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        # Set raw mode and disable echo (except for visible feedback during number entry)
        tty.setraw(sys.stdin.fileno())
        ch = sys.stdin.read(1)
        return ch
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


# Main execution
if __name__ == "__main__":
    from datetime import datetime

    # Prompt for project information
    print("=" * 60)
    print("Book Scanner - Project Setup")
    print("=" * 60)

    # Get human-readable identifier
    identifier = input(
        "Enter identifier for this scan (e.g., vogue-march-1985): "
    ).strip()
    if not identifier:
        print("ERROR: Identifier cannot be empty")
        sys.exit(1)

    magazine_name = input("Enter magazine name: ").strip()
    scanner_person = input("Enter name of person scanning: ").strip()

    # Create captures directory structure
    # Format: captures/YYYYMMDD-HHMMSS-identifier/
    scan_start_time = datetime.now()
    timestamp = scan_start_time.strftime("%Y%m%d-%H%M%S")
    session_name = f"{timestamp}-{identifier}"

    captures_dir = os.path.join(SCRIPT_DIR, "captures")
    session_dir = os.path.join(captures_dir, session_name)

    # Create directory
    try:
        os.makedirs(session_dir, exist_ok=True)
        print(f"\n✓ Created session: {session_name}")
        print(f"✓ Directory: {session_dir}")
    except Exception as e:
        print(f"ERROR: Could not create directory: {e}")
        sys.exit(1)

    # Change to the new directory
    os.chdir(session_dir)
    print(f"✓ Working directory: {os.getcwd()}\n")

    # Kill processes that interfere with camera access
    devnull = open(os.devnull, "w")
    # Mac
    subprocess.call(["killall", "PTPCamera"], stderr=devnull)
    # Linux - GVFS processes
    subprocess.call(["killall", "gvfs-gphoto2-volume-monitor"], stderr=devnull)
    subprocess.call(["killall", "gvfs-mtp-volume-monitor"], stderr=devnull)
    subprocess.call(["killall", "gvfsd-gphoto2"], stderr=devnull)
    devnull.close()

    # Give processes time to die
    time.sleep(0.5)

    # Start web server in background
    server_thread = Thread(target=start_web_server, daemon=True)
    server_thread.start()
    print(f"📡 Web server running at http://localhost:{PORT}")
    print("Open this URL in your browser to see live scanner updates\n")

    # Detect cameras and get serials (with retry loop)
    while True:
        print("Detecting cameras...")
        port_serial_map = get_all_camera_serials()

        if len(port_serial_map) == 2:
            break
        elif len(port_serial_map) == 0:
            print("No cameras found.")
        else:
            print(f"Found {len(port_serial_map)} camera(s), need 2:")
            for port, serial in port_serial_map.items():
                print(f"  {port} - {serial}")

        print(
            "\nPlease connect both cameras and press Enter to retry (or 'q' to quit)..."
        )
        resp = input().strip().lower()
        if resp == "q":
            print("Exiting.")
            sys.exit(0)
        print()

    # Display cameras and ask user to assign left/right
    print("\nDetected cameras:")
    ports = list(port_serial_map.keys())
    for i, (port, serial) in enumerate(port_serial_map.items(), 1):
        print(f"  {i}. {port} - Serial: {serial}")

    print()
    choice = input("Enter 1 or 2 for which camera is on the LEFT: ").strip()

    if choice == "1":
        left_cam = ports[0]
        right_cam = ports[1]
    elif choice == "2":
        left_cam = ports[1]
        right_cam = ports[0]
    else:
        print("Invalid choice, using detected order")
        left_cam, right_cam = ports

    previous_cameras = ports
    left_serial = port_serial_map[left_cam]
    right_serial = port_serial_map[right_cam]

    print(f"\nLeft camera:  {left_cam} - {left_serial}")
    print(f"Right camera: {right_cam} - {right_serial}")

    scanner_state["left_cam_serial"] = left_serial
    scanner_state["left_cam_locked"] = True
    scanner_state["right_cam_serial"] = right_serial
    scanner_state["right_cam_locked"] = True

    # Update global state
    scanner_state["left_cam_port"] = left_cam
    scanner_state["right_cam_port"] = right_cam

    # Get initial battery levels
    camera_info_map = scanner_state.get("camera_info_map", {})
    left_cam_info = camera_info_map.get(left_cam, {})
    right_cam_info = camera_info_map.get(right_cam, {})
    scanner_state["left_cam_battery"] = left_cam_info.get("battery")
    scanner_state["right_cam_battery"] = right_cam_info.get("battery")
    if scanner_state["left_cam_battery"] is not None:
        print(f"Left camera battery: {scanner_state['left_cam_battery']}%")
    if scanner_state["right_cam_battery"] is not None:
        print(f"Right camera battery: {scanner_state['right_cam_battery']}%")

    # Capture preview images
    print("Skipping preview - going straight to scanning")
    scanner_state["status_color"] = "9f9"
    scanner_state["status_text"] = "Ready to scan"

    # Save metadata to JSON file
    # Get camera info from the stored map
    camera_info_map = scanner_state.get("camera_info_map", {})
    left_cam_info = camera_info_map.get(left_cam, {})
    right_cam_info = camera_info_map.get(right_cam, {})

    metadata = {
        "session_name": session_name,
        "identifier": identifier,
        "magazine_name": magazine_name,
        "scanner_person": scanner_person,
        "scan_date": scan_start_time.strftime("%Y-%m-%d"),
        "scan_time": scan_start_time.strftime("%H:%M:%S"),
        "scan_start_timestamp": scan_start_time.isoformat(),
        "left_camera": {
            "port": left_cam,
            "serial": left_serial,
            "model": left_cam_info.get("model"),
            "manufacturer": left_cam_info.get("manufacturer"),
        },
        "right_camera": {
            "port": right_cam,
            "serial": right_serial,
            "model": right_cam_info.get("model"),
            "manufacturer": right_cam_info.get("manufacturer"),
        },
    }

    metadata_file = "scan_metadata.json"
    try:
        with open(metadata_file, "w") as f:
            json.dump(metadata, f, indent=2)
        print(f"\n✓ Metadata saved to {metadata_file}")
    except Exception as e:
        print(f"WARNING: Could not save metadata: {e}")

    # Store session info in global state for web interface
    scanner_state["session_name"] = session_name
    scanner_state["session_dir"] = session_dir
    scanner_state["metadata"] = metadata

    print()

    # Main scanning loop
    img_num = 0
    use_parallel = True  # Try parallel capture by default
    query_serials_before_capture = False  # Default to not querying serials each time

    print(f"\nReady. Press '{CAPTURE_KEY}' to capture both cameras")
    print(
        f"Commands: l/r=left/right only, s=toggle serial/parallel, q=toggle serial query, n=image number, x=quit\n"
    )

    try:
        while True:
            # Check for web-triggered capture
            if scanner_state["capture_requested"]:
                scanner_state["capture_requested"] = False
                x = CAPTURE_KEY  # Simulate 'b' press from web
                print(f"[Web trigger: {x}]")
            else:
                # Non-blocking input - check for keypresses
                ch = getch_nonblocking()

                if ch is None:
                    # No input, continue loop
                    time.sleep(0.05)
                    continue

                # Handle special characters
                if ch == "\r" or ch == "\n":
                    ch = ""  # Treat Enter as empty string
                elif ch == "\x03":  # Ctrl+C
                    print("\n\nInterrupted by user")
                    break

                x = ch

            if x == "x":  # clean up and quit
                print("\nExiting...")
                break

            if x == "s":  # toggle serial/parallel mode
                use_parallel = not use_parallel
                mode = "parallel" if use_parallel else "serial"
                print(f"\nSwitched to {mode} capture mode")
                continue

            if x == "q":  # toggle serial query before capture
                query_serials_before_capture = not query_serials_before_capture
                status = "enabled" if query_serials_before_capture else "disabled"
                print(f"\nSerial query before capture: {status}")
                continue

            if x == "n":  # jump to image number
                print("\nEnter image number: ", end="", flush=True)
                # Switch to blocking mode for number input
                num_str = ""
                while True:
                    ch = getch_blocking()
                    if ch == "\r" or ch == "\n":
                        print()
                        break
                    elif ch == "\x7f" or ch == "\x08":  # Backspace
                        if num_str:
                            num_str = num_str[:-1]
                            print("\b \b", end="", flush=True)
                    elif ch.isdigit():
                        num_str += ch
                        print(ch, end="", flush=True)
                try:
                    new_num = int(num_str)
                    img_num = new_num // 2 * 2  # convert to even number
                    print(f"Next image will be {img_num}")
                except ValueError:
                    print("Invalid number")
                continue

            if x == "l":  # capture left camera only
                if query_serials_before_capture:
                    port_serial_map = get_all_camera_serials()
                else:
                    port_serial_map = get_all_camera_serials()
                left_cam = None
                for port, serial in port_serial_map.items():
                    if serial == scanner_state["left_cam_serial"]:
                        left_cam = port

                if not left_cam:
                    print("ERROR: Could not find left camera.")
                    print(f"  Expected serial: {scanner_state['left_cam_serial']}")
                    print(f"  Available ports: {port_serial_map}")
                    continue

                print(f"Capturing LEFT camera only ({left_cam})...")
                cmd = [
                    GPHOTO,
                    "--capture-image-and-download",
                    "--force-overwrite",
                    "--port",
                    left_cam,
                    "--filename",
                    IMG_FORMAT % img_num,
                ]
                print(f"  Command: {' '.join(cmd)}")
                p1 = snap(left_cam, IMG_FORMAT % img_num)
                returncode = p1.wait()
                if returncode == 0:
                    print(f"✓ Left camera captured: {IMG_FORMAT % img_num}")
                    emit_status_update(f"Captured: {IMG_FORMAT % img_num}", "9f9")
                    emit_gallery_update()
                    img_num += 1
                else:
                    print(
                        f"✗ Left camera capture failed with return code: {returncode}"
                    )
                    print(f"  Port: {left_cam}")
                    print(f"  Serial: {scanner_state['left_cam_serial']}")
                continue

            if x == "r":  # capture right camera only
                if query_serials_before_capture:
                    port_serial_map = get_all_camera_serials()
                else:
                    port_serial_map = get_all_camera_serials()
                right_cam = None
                for port, serial in port_serial_map.items():
                    if serial == scanner_state["right_cam_serial"]:
                        right_cam = port

                if not right_cam:
                    print("ERROR: Could not find right camera.")
                    print(f"  Expected serial: {scanner_state['right_cam_serial']}")
                    print(f"  Available ports: {port_serial_map}")
                    continue

                print(f"Capturing RIGHT camera only ({right_cam})...")
                cmd = [
                    GPHOTO,
                    "--capture-image-and-download",
                    "--force-overwrite",
                    "--port",
                    right_cam,
                    "--filename",
                    IMG_FORMAT % img_num,
                ]
                print(f"  Command: {' '.join(cmd)}")
                p1 = snap(right_cam, IMG_FORMAT % img_num)
                returncode = p1.wait()
                if returncode == 0:
                    print(f"✓ Right camera captured: {IMG_FORMAT % img_num}")
                    emit_status_update(f"Captured: {IMG_FORMAT % img_num}", "9f9")
                    emit_gallery_update()
                    img_num += 1
                else:
                    print(
                        f"✗ Right camera capture failed with return code: {returncode}"
                    )
                    print(f"  Port: {right_cam}")
                    print(f"  Serial: {scanner_state['right_cam_serial']}")
                continue

            if x == "" or x == CAPTURE_KEY:  # Empty input or 'b' = capture both cameras
                print(f"\n[Capture #{img_num // 2 + 1}]", flush=True)

                # Optionally re-query serials before capture
                if query_serials_before_capture:
                    print("Querying camera serials...")
                    port_serial_map = get_all_camera_serials()
                else:
                    # Just use the stored serials and find current ports
                    port_serial_map = get_all_camera_serials()

                left_cam = None
                right_cam = None
                for port, serial in port_serial_map.items():
                    if serial == scanner_state["left_cam_serial"]:
                        left_cam = port
                    elif serial == scanner_state["right_cam_serial"]:
                        right_cam = port

                if not left_cam or not right_cam:
                    print("ERROR: Could not find both cameras.")
                    print(f"  Expected left: {scanner_state['left_cam_serial']}")
                    print(f"  Expected right: {scanner_state['right_cam_serial']}")
                    print(f"  Available: {port_serial_map}")
                    continue

                # Check if ports have shifted and update display
                ports = list(port_serial_map.keys())
                if ports != previous_cameras:
                    print(f"⚠️  Camera ports shifted: {previous_cameras} → {ports}")
                    print(f"   Left={left_cam}, Right={right_cam}")
                    previous_cameras = ports
                    scanner_state["left_cam_port"] = left_cam
                    scanner_state["right_cam_port"] = right_cam

                if use_parallel:
                    # Try parallel capture
                    print(f"Capturing BOTH cameras in parallel mode...")
                    print(f"  LEFT: {left_cam}")
                    print(f"  RIGHT: {right_cam}")
                    emit_status_update("Capturing both cameras...", "ff9")

                    p1 = snap(left_cam, IMG_FORMAT % img_num)
                    p2 = snap(right_cam, IMG_FORMAT % (img_num + 1))

                    # Wait for both to complete
                    success = wait(p1, p2)

                    if success:
                        print(f"✓ Both captures successful")
                    else:
                        print(
                            f"✗ Parallel capture failed (left={p1.returncode}, right={p2.returncode})"
                        )
                        print(
                            f"  Hint: Use 's' to switch to serial mode if parallel isn't working"
                        )
                        continue
                else:
                    # Serial capture mode
                    print(f"Capturing LEFT: {left_cam}")
                    p1 = snap(left_cam, IMG_FORMAT % img_num)
                    returncode1 = p1.wait()
                    if returncode1 == 0:
                        print(f"✓ Left capture successful: {IMG_FORMAT % img_num}")
                    else:
                        print(
                            f"✗ Left camera capture failed with return code: {returncode1}"
                        )
                        print(
                            f"  Port: {left_cam}, Serial: {scanner_state['left_cam_serial']}"
                        )
                        continue

                    # Wait for USB to settle
                    print("Waiting for USB to settle...")
                    time.sleep(1.0)

                    # Re-detect before second camera if querying serials
                    if query_serials_before_capture:
                        port_serial_map = get_all_camera_serials()
                        right_cam = None
                        for port, serial in port_serial_map.items():
                            if serial == scanner_state["right_cam_serial"]:
                                right_cam = port

                        if not right_cam:
                            print(
                                "ERROR: Could not find right camera before second capture."
                            )
                            print(
                                f"  Expected serial: {scanner_state['right_cam_serial']}"
                            )
                            print(f"  Available: {port_serial_map}")
                            continue

                    # Capture right camera
                    print(f"Capturing RIGHT: {right_cam}")
                    p2 = snap(right_cam, IMG_FORMAT % (img_num + 1))
                    returncode2 = p2.wait()
                    if returncode2 == 0:
                        print(
                            f"✓ Right capture successful: {IMG_FORMAT % (img_num + 1)}"
                        )
                    else:
                        print(
                            f"✗ Right camera capture failed with return code: {returncode2}"
                        )
                        print(
                            f"  Port: {right_cam}, Serial: {scanner_state['right_cam_serial']}"
                        )
                        continue

                # Auto-rotate images
                rightpic = "img" + str(img_num).zfill(5) + ".jpg"
                leftpic = "img" + str(img_num + 1).zfill(5) + ".jpg"
                os.system("jpegtran -rot 270 " + rightpic + " > opt-" + rightpic)
                os.system("cp opt-" + rightpic + " " + rightpic)
                os.system("rm opt-" + rightpic)
                os.system("jpegtran -rot 90 " + leftpic + " > opt-" + leftpic)
                os.system("cp opt-" + leftpic + " " + leftpic)
                os.system("rm opt-" + leftpic)

                # Update image list and status
                emit_status_update(f"Captured: {rightpic}, {leftpic}", "9f9")
                emit_gallery_update()
                print(f"✓ Saved: {rightpic}, {leftpic}")
                print(f"Ready.\n")

                img_num += 2
                continue

            try:  # assume x is an image number to jump to
                img_num = int(x) // 2 * 2  # convert to even number
            except ValueError:
                print("unrecognized command")
                continue

    except KeyboardInterrupt:
        print("\n\nInterrupted by keyboard (Ctrl+C)")

    finally:
        # Save stop time to metadata
        scan_stop_time = datetime.now()
        duration_seconds = (scan_stop_time - scan_start_time).total_seconds()
        metadata["scan_stop_timestamp"] = scan_stop_time.isoformat()
        metadata["scan_duration_seconds"] = duration_seconds
        metadata["total_images_captured"] = img_num

        try:
            with open(metadata_file, "w") as f:
                json.dump(metadata, f, indent=2)
        except Exception as e:
            print(f"WARNING: Could not update metadata: {e}")

        # Print session summary
        duration_mins = int(duration_seconds // 60)
        duration_secs = int(duration_seconds % 60)
        num_pages = img_num // 2
        current_notes = metadata.get("notes", "")

        print("\n" + "=" * 50)
        print("SESSION SUMMARY")
        print("=" * 50)
        print(f"Session:    {session_name}")
        if magazine_name:
            print(f"Magazine:   {magazine_name}")
        if scanner_person:
            print(f"Scanned by: {scanner_person}")
        print(f"Duration:   {duration_mins}m {duration_secs}s")
        print(f"Images:     {img_num}")
        print(f"Pages:      {num_pages}")
        if num_pages > 0 and duration_seconds > 0:
            secs_per_page = duration_seconds / num_pages
            print(f"Avg pace:   {secs_per_page:.1f}s per page")
        print(f"Output:     {session_dir}/")
        print("=" * 50)

        # Prompt for notes
        if current_notes:
            print(f"\nCurrent notes: {current_notes}")
        print("Add/amend notes (Enter to keep, or type new notes):")
        try:
            new_notes = input("> ").strip()
            if new_notes:
                metadata["notes"] = new_notes
                try:
                    with open(metadata_file, "w") as f:
                        json.dump(metadata, f, indent=2)
                    print(f"Notes saved.")
                except Exception as e:
                    print(f"WARNING: Could not save notes: {e}")
            elif current_notes:
                print("Notes unchanged.")
        except (EOFError, KeyboardInterrupt):
            print("\nSkipping notes.")
