#!/usr/bin/env python3
"""
Post-processing script for scanned images.
Handles cropping, crop preview, and PDF generation.
"""

import argparse
import glob
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw


def load_session_metadata(session_dir):
    """Load metadata from a session directory."""
    metadata_file = os.path.join(session_dir, "scan_metadata.json")
    if not os.path.exists(metadata_file):
        print(f"ERROR: No metadata file found at {metadata_file}")
        return None

    try:
        with open(metadata_file, "r") as f:
            return json.load(f)
    except Exception as e:
        print(f"ERROR: Could not load metadata: {e}")
        return None


def find_images(session_dir):
    """Find all images in a session directory."""
    pattern = os.path.join(session_dir, "img*.jpg")
    images = sorted(glob.glob(pattern))
    return images


def save_crop_settings(session_dir, crop_settings):
    """Save crop settings to JSON file."""
    crop_file = os.path.join(session_dir, "crop_settings.json")
    try:
        with open(crop_file, "w") as f:
            json.dump(crop_settings, f, indent=2)
        print(f"✓ Crop settings saved to {crop_file}")
    except Exception as e:
        print(f"ERROR: Could not save crop settings: {e}")


def load_crop_settings(session_dir):
    """Load crop settings from JSON file."""
    crop_file = os.path.join(session_dir, "crop_settings.json")
    if os.path.exists(crop_file):
        try:
            with open(crop_file, "r") as f:
                return json.load(f)
        except Exception as e:
            print(f"WARNING: Could not load crop settings: {e}")
    return None


def preview_crop(image_path, crop_box):
    """
    Create a preview of the crop by drawing a rectangle on the image.

    Args:
        image_path: Path to the image file
        crop_box: Tuple of (left, top, right, bottom) or dict with those keys

    Returns:
        Path to the preview image
    """
    if isinstance(crop_box, dict):
        crop_box = (
            crop_box["left"],
            crop_box["top"],
            crop_box["right"],
            crop_box["bottom"],
        )

    img = Image.open(image_path)
    draw = ImageDraw.Draw(img)

    # Draw a red rectangle showing the crop area
    draw.rectangle(crop_box, outline="red", width=10)

    # Save preview
    preview_path = image_path.replace(".jpg", "_crop_preview.jpg")
    img.save(preview_path, quality=95)

    return preview_path


def apply_crop(image_path, crop_box, output_dir=None):
    """
    Apply crop to an image and save it.

    Args:
        image_path: Path to the image file
        crop_box: Tuple of (left, top, right, bottom) or dict with those keys
        output_dir: Directory to save cropped images (default: same as input)

    Returns:
        Path to the cropped image
    """
    if isinstance(crop_box, dict):
        crop_box = (
            crop_box["left"],
            crop_box["top"],
            crop_box["right"],
            crop_box["bottom"],
        )

    img = Image.open(image_path)
    cropped = img.crop(crop_box)

    # Determine output path
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        basename = os.path.basename(image_path)
        output_path = os.path.join(output_dir, basename.replace(".jpg", "_cropped.jpg"))
    else:
        output_path = image_path.replace(".jpg", "_cropped.jpg")

    cropped.save(output_path, quality=95)

    return output_path


def create_pdf(image_paths, output_pdf, metadata=None):
    """
    Create a PDF from a list of images.

    Args:
        image_paths: List of image file paths
        output_pdf: Path to output PDF file
        metadata: Optional metadata dict to embed in PDF
    """
    if not image_paths:
        print("ERROR: No images to create PDF")
        return False

    print(f"Creating PDF with {len(image_paths)} images...")

    # Load all images
    images = []
    for i, img_path in enumerate(image_paths):
        try:
            img = Image.open(img_path)
            # Convert to RGB if needed (PDF doesn't support RGBA)
            if img.mode != "RGB":
                img = img.convert("RGB")
            images.append(img)
            if (i + 1) % 10 == 0:
                print(f"  Loaded {i + 1}/{len(image_paths)} images...")
        except Exception as e:
            print(f"WARNING: Could not load {img_path}: {e}")

    if not images:
        print("ERROR: No valid images loaded")
        return False

    # Save as PDF
    try:
        first_image = images[0]
        other_images = images[1:]

        first_image.save(
            output_pdf,
            "PDF",
            save_all=True,
            append_images=other_images,
            resolution=300.0,
            quality=95,
        )

        file_size = os.path.getsize(output_pdf) / (1024 * 1024)
        print(f"✓ PDF created: {output_pdf} ({file_size:.2f} MB)")
        return True
    except Exception as e:
        print(f"ERROR: Could not create PDF: {e}")
        return False


def interactive_crop_setup(session_dir, images):
    """
    Interactive setup for crop settings.
    Uses the first image to determine crop coordinates.
    """
    if not images:
        print("ERROR: No images found to set up crop")
        return None

    first_image = images[0]
    print(f"\nUsing first image for crop setup: {os.path.basename(first_image)}")

    # Get image dimensions
    img = Image.open(first_image)
    width, height = img.size
    print(f"Image size: {width} x {height}")

    print("\nEnter crop coordinates (in pixels):")
    print("  - left: distance from left edge")
    print("  - top: distance from top edge")
    print("  - right: distance from left edge to right side of crop")
    print("  - bottom: distance from top edge to bottom of crop")
    print(f"\nFor example, to crop 100px from each edge:")
    print(f"  left=100, top=100, right={width - 100}, bottom={height - 100}")

    try:
        left = int(input(f"\nLeft (0-{width}): "))
        top = int(input(f"Top (0-{height}): "))
        right = int(input(f"Right ({left}-{width}): "))
        bottom = int(input(f"Bottom ({top}-{height}): "))

        crop_box = {"left": left, "top": top, "right": right, "bottom": bottom}

        # Create preview
        print("\nGenerating crop preview...")
        preview_path = preview_crop(first_image, crop_box)
        print(f"✓ Preview saved: {preview_path}")
        print("\nPlease review the preview image to verify the crop.")
        print("The red rectangle shows what will be kept.")

        return crop_box

    except (ValueError, KeyboardInterrupt) as e:
        print("\nCrop setup cancelled")
        return None


def cmd_setup_crop(args):
    """Command: Set up crop settings for a session."""
    session_dir = os.path.abspath(args.session)

    if not os.path.isdir(session_dir):
        print(f"ERROR: Session directory not found: {session_dir}")
        return 1

    # Find images
    images = find_images(session_dir)
    if not images:
        print(f"ERROR: No images found in {session_dir}")
        return 1

    print(f"Found {len(images)} images in session")

    # Interactive crop setup
    crop_settings = interactive_crop_setup(session_dir, images)
    if not crop_settings:
        return 1

    # Save settings
    save_crop_settings(session_dir, crop_settings)

    return 0


def cmd_preview_crop(args):
    """Command: Preview crop on specific images."""
    session_dir = os.path.abspath(args.session)

    if not os.path.isdir(session_dir):
        print(f"ERROR: Session directory not found: {session_dir}")
        return 1

    # Load crop settings
    crop_settings = load_crop_settings(session_dir)
    if not crop_settings:
        print("ERROR: No crop settings found. Run 'setup-crop' first.")
        return 1

    # Find images
    images = find_images(session_dir)
    if not images:
        print(f"ERROR: No images found in {session_dir}")
        return 1

    # Preview specific images or sample
    if args.image_numbers:
        # Preview specific image numbers
        for img_num in args.image_numbers:
            # Find image with this number (e.g., img00001.jpg)
            pattern = f"img{img_num:05d}.jpg"
            matching = [img for img in images if pattern in img]
            if matching:
                preview_path = preview_crop(matching[0], crop_settings)
                print(f"✓ Preview: {preview_path}")
            else:
                print(f"WARNING: Image {img_num} not found")
    else:
        # Preview first, middle, and last images
        sample_indices = [0, len(images) // 2, len(images) - 1]
        for idx in sample_indices:
            preview_path = preview_crop(images[idx], crop_settings)
            print(f"✓ Preview: {preview_path}")

    return 0


def cmd_apply_crop(args):
    """Command: Apply crop to all images."""
    session_dir = os.path.abspath(args.session)

    if not os.path.isdir(session_dir):
        print(f"ERROR: Session directory not found: {session_dir}")
        return 1

    # Load crop settings
    crop_settings = load_crop_settings(session_dir)
    if not crop_settings:
        print("ERROR: No crop settings found. Run 'setup-crop' first.")
        return 1

    # Find images
    images = find_images(session_dir)
    if not images:
        print(f"ERROR: No images found in {session_dir}")
        return 1

    # Create output directory
    output_dir = os.path.join(session_dir, "cropped")
    os.makedirs(output_dir, exist_ok=True)

    print(f"Cropping {len(images)} images...")
    for i, img_path in enumerate(images):
        try:
            output_path = apply_crop(img_path, crop_settings, output_dir)
            if (i + 1) % 10 == 0:
                print(f"  Cropped {i + 1}/{len(images)} images...")
        except Exception as e:
            print(f"ERROR: Could not crop {img_path}: {e}")

    print(f"✓ All images cropped to: {output_dir}")

    return 0


def cmd_create_pdf(args):
    """Command: Create PDF from images."""
    session_dir = os.path.abspath(args.session)

    if not os.path.isdir(session_dir):
        print(f"ERROR: Session directory not found: {session_dir}")
        return 1

    # Load metadata
    metadata = load_session_metadata(session_dir)

    # Determine source directory (cropped or original)
    if args.use_cropped:
        source_dir = os.path.join(session_dir, "cropped")
        if not os.path.isdir(source_dir):
            print("ERROR: No cropped images found. Run 'apply-crop' first.")
            return 1
        pattern = os.path.join(source_dir, "img*_cropped.jpg")
    else:
        source_dir = session_dir
        pattern = os.path.join(source_dir, "img*.jpg")

    images = sorted(glob.glob(pattern))
    if not images:
        print(f"ERROR: No images found in {source_dir}")
        return 1

    # Determine output PDF name
    if args.output:
        output_pdf = args.output
    else:
        session_name = os.path.basename(session_dir)
        suffix = "_cropped" if args.use_cropped else ""
        output_pdf = os.path.join(session_dir, f"{session_name}{suffix}.pdf")

    # Create PDF
    success = create_pdf(images, output_pdf, metadata)

    return 0 if success else 1


def main():
    parser = argparse.ArgumentParser(
        description="Post-processing for scanned images: cropping and PDF generation"
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # setup-crop command
    setup_crop_parser = subparsers.add_parser(
        "setup-crop", help="Interactively set up crop settings for a session"
    )
    setup_crop_parser.add_argument(
        "session",
        help="Path to session directory (e.g., captures/20250102-143000-vogue-march-1985)",
    )

    # preview-crop command
    preview_crop_parser = subparsers.add_parser(
        "preview-crop", help="Preview crop on sample images"
    )
    preview_crop_parser.add_argument("session", help="Path to session directory")
    preview_crop_parser.add_argument(
        "--images",
        dest="image_numbers",
        type=int,
        nargs="+",
        help="Specific image numbers to preview (e.g., 1 5 10)",
    )

    # apply-crop command
    apply_crop_parser = subparsers.add_parser(
        "apply-crop", help="Apply crop to all images in a session"
    )
    apply_crop_parser.add_argument("session", help="Path to session directory")

    # create-pdf command
    create_pdf_parser = subparsers.add_parser(
        "create-pdf", help="Create PDF from images"
    )
    create_pdf_parser.add_argument("session", help="Path to session directory")
    create_pdf_parser.add_argument(
        "--cropped",
        dest="use_cropped",
        action="store_true",
        help="Use cropped images instead of originals",
    )
    create_pdf_parser.add_argument(
        "--output",
        help="Output PDF filename (default: auto-generated from session name)",
    )

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    # Dispatch to command handlers
    if args.command == "setup-crop":
        return cmd_setup_crop(args)
    elif args.command == "preview-crop":
        return cmd_preview_crop(args)
    elif args.command == "apply-crop":
        return cmd_apply_crop(args)
    elif args.command == "create-pdf":
        return cmd_create_pdf(args)

    return 0


if __name__ == "__main__":
    sys.exit(main())
