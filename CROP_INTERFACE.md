# Web-Based Crop Interface

## Overview

The scanner now includes a web-based interface for cropping images with live preview. This makes it much easier to set up and verify crop settings before processing all images.

## Features

### Interactive Crop Rectangle
- **Drag to move**: Click and drag the red rectangle to reposition the crop area
- **Resize handles**: Drag the red squares on corners and edges to resize
- **Live preview**: See exactly what will be cropped as you adjust

### Slider Controls
- Fine-tune each edge with pixel precision
- Left, Top, Right, Bottom sliders
- Real-time dimension display (width × height)

### Image Selection
- Browse all captured images via dropdown
- Preview crop on different images to ensure consistency
- Automatically loads image dimensions

### Crop Settings Persistence
- **Save Settings**: Stores crop coordinates to `crop_settings.json`
- **Load Settings**: Restores previously saved coordinates
- Settings persist across sessions

### Batch Processing
- **Apply to All Images**: Process entire session with one click
- Creates `cropped/` subdirectory with all cropped images
- Progress feedback and status messages

## Usage

### 1. Access the Interface

While `scan.py` is running, navigate to:
```
http://localhost:5001/crop
```

Or click the "✂️ Crop Images" button on the main scanner page.

### 2. Set Up Crop Area

1. Select an image from the dropdown (start with the first one)
2. Adjust the crop using either:
   - **Mouse**: Drag the rectangle or resize handles
   - **Sliders**: Use the Left/Top/Right/Bottom controls
3. Check the width and height to ensure dimensions look correct

### 3. Verify on Multiple Images

Select different images to verify the crop works well across all pages:
- First image
- Middle image
- Last image
- Any problematic pages

### 4. Save and Apply

1. Click **"💾 Save Settings"** to save your crop coordinates
2. Click **"✂️ Apply to All Images"** to process the entire session
3. Confirm the operation
4. Wait for completion message

### 5. Generate PDF

Return to the terminal and run:
```bash
./process.py create-pdf captures/SESSION_NAME --cropped
```

## Technical Details

### API Endpoints

- **GET /api/crop-settings**: Load saved crop settings
- **POST /api/crop-settings**: Save crop settings
- **POST /api/crop-preview**: Generate preview image with crop rectangle
- **POST /api/apply-crop**: Apply crop to all images

### Crop Settings Format

Stored in `crop_settings.json`:
```json
{
  "left": 100,
  "top": 150,
  "right": 3900,
  "bottom": 5800
}
```

All values are in pixels based on the original image dimensions.

### Output

Cropped images are saved to:
```
captures/SESSION_NAME/cropped/img00000_cropped.jpg
captures/SESSION_NAME/cropped/img00001_cropped.jpg
...
```

## Tips

- **Start with extremes**: Check the first and last images to account for any shift in positioning
- **Use sliders for precision**: The mouse is great for rough positioning, but use sliders for pixel-perfect adjustments
- **Save frequently**: Save your settings as you go so you don't lose your work
- **Check dimensions**: The width and height should be consistent with your expected page size

## Troubleshooting

**Rectangle not visible:**
- Ensure an image is selected from the dropdown
- Check that the image has loaded completely

**Crop seems offset:**
- Remember: coordinates are in original image pixels, not screen pixels
- The overlay automatically scales to match the displayed image size

**Apply to All fails:**
- Ensure you've saved settings first
- Check that the session directory contains images
- Verify you have write permissions

**Images in dropdown are empty:**
- Make sure you're running this while the scanner is active
- Check that images have been captured in the current session
