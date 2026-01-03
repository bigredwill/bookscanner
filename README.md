# Book Scanner

A dual-camera scanning system with web interface for digitizing books and magazines.

## Overview

This scanner uses two cameras (left and right) to capture pages simultaneously. It includes:
- Real-time web interface for monitoring scans
- Automatic image rotation and metadata tracking
- Post-processing tools for cropping and PDF generation

## Scanning Workflow

### 1. Start a Scanning Session

```bash
python3 scan.py
```

You'll be prompted to enter:
- **Identifier**: Short name for the scan (e.g., `vogue-march-1985`)
- **Magazine name**: Full name of the publication
- **Scanner person**: Your name

The script will:
1. Create a session directory: `captures/YYYYMMDD-HHMMSS-identifier/`
2. Detect cameras and let you assign left/right
3. Start a web interface at `http://localhost:5001`
4. Begin capturing images

### 2. Capture Images

**Keyboard commands during scanning:**
- `b` or Enter: Capture both cameras
- `l`: Capture left camera only
- `r`: Capture right camera only
- `s`: Toggle serial/parallel capture mode
- `n`: Jump to specific image number
- `x`: Exit cleanly
- `Ctrl+C`: Exit (also saves stop time)

**Web interface:**
- View live gallery of captured images
- See camera information and session metadata
- Trigger captures remotely

### 3. Stop Scanning

When you're done scanning, press:
- `x` to exit cleanly, or
- `Ctrl+C` to interrupt

Both methods now save a stop timestamp and duration to the metadata file.

## Post-Processing

After scanning, use the web interface to crop images and generate PDFs.

### Web-Based Cropping (Recommended)

The easiest way to crop images is through the web interface:

1. **Open the crop interface** at `http://localhost:5001/crop` or click the "✂️ Crop Images" button on the main scanner page

2. **Select an image** from the dropdown to preview

3. **Adjust the crop area** using:
   - **Sliders**: Fine-tune each edge (left, top, right, bottom)
   - **Mouse drag**: Click and drag the red rectangle to move it
   - **Resize handles**: Drag the red squares on the corners and edges to resize

4. **Preview on multiple images**: Select different images to verify the crop works for all pages

5. **Save settings**: Click "💾 Save Settings" to save your crop coordinates

6. **Apply to all images**: Click "✂️ Apply to All Images" to crop every image in the session

The cropped images are saved to the `cropped/` subdirectory.

### Command-Line Cropping (Alternative)

You can also use the `process.py` script for cropping:

```bash
# Interactive crop setup
./process.py setup-crop captures/20250102-143000-vogue-march-1985

# Preview crop on specific images
./process.py preview-crop captures/20250102-143000-vogue-march-1985 --images 1 10 20

# Apply crop to all images
./process.py apply-crop captures/20250102-143000-vogue-march-1985
```

### Generate PDF

Create a PDF from the scanned images:

```bash
# PDF from original images
./process.py create-pdf captures/20250102-143000-vogue-march-1985

# PDF from cropped images
./process.py create-pdf captures/20250102-143000-vogue-march-1985 --cropped

# Custom output filename
./process.py create-pdf captures/20250102-143000-vogue-march-1985 --cropped --output my-magazine.pdf
```

## Complete Example Workflow

```bash
# 1. Scan
python3 scan.py
# Enter: vogue-march-1985, Vogue Magazine, John Doe
# Open http://localhost:5001 in your browser
# Press 'b' repeatedly (or use web button) to capture pages
# Press 'x' when done

# 2. Crop images via web interface
# Navigate to http://localhost:5001/crop
# Select first image, adjust crop rectangle with mouse or sliders
# Preview on several images (first, middle, last)
# Click "Save Settings" then "Apply to All Images"

# 3. Generate final PDF
./process.py create-pdf captures/20250102-143000-vogue-march-1985 --cropped --output vogue-march-1985.pdf
```

## Session Metadata

Each session includes a `scan_metadata.json` file with:
- Session name and identifier
- Magazine name and scanner person
- Camera information (model, serial numbers)
- Scan start time
- Scan stop time (added when you exit)
- Scan duration and total images captured

## Directory Structure

```
scanner/
├── scan.py                    # Main scanning script
├── process.py                 # Post-processing script
├── captures/                  # All scanning sessions
│   └── YYYYMMDD-HHMMSS-identifier/
│       ├── scan_metadata.json    # Session metadata
│       ├── crop_settings.json    # Crop coordinates (after setup-crop)
│       ├── img00000.jpg          # Captured images
│       ├── img00001.jpg
│       ├── ...
│       ├── cropped/              # Cropped images (after apply-crop)
│       │   ├── img00000_cropped.jpg
│       │   └── ...
│       └── session-name.pdf      # Generated PDF (after create-pdf)
└── templates/                 # Web interface templates
    └── index.html
```

## Requirements

- Python 3
- gphoto2
- Flask
- Flask-SocketIO
- Pillow (PIL)
- jpegtran (for image rotation)

## Troubleshooting

**Cameras not detected:**
- Ensure cameras are in PTP mode
- Check USB connections
- Try running `gphoto2 --auto-detect` manually

**Parallel capture fails:**
- Press `s` to toggle to serial capture mode
- Serial mode is slower but more reliable

**USB ports shifting:**
- The script tracks cameras by serial number
- Port changes are automatically detected and handled

**Web interface not loading:**
- Check that port 5001 is not in use
- Navigate to `http://localhost:5001`
