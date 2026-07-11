from PIL import Image
import os

# ── User settings ──────────────────────────────────────────────────────────────
INPUT_FOLDER  = "/path/to/input"
OUTPUT_FOLDER = "/path/to/output"
MIN_WIDTH     = 200
MIN_HEIGHT    = 200
# ──────────────────────────────────────────────────────────────────────────────

SUPPORTED = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tiff"}

def resize_image(img, min_w, min_h):
    orig_w, orig_h = img.size
    scale = max(min_w / orig_w, min_h / orig_h)
    if scale >= 1:
        return img  # already large enough, skip upscaling
    new_w = round(orig_w * scale)
    new_h = round(orig_h * scale)
    return img.resize((new_w, new_h), Image.LANCZOS)

def main():
    os.makedirs(OUTPUT_FOLDER, exist_ok=True)
    files = [f for f in os.listdir(INPUT_FOLDER)
             if os.path.splitext(f)[1].lower() in SUPPORTED]

    if not files:
        print("No supported images found in input folder.")
        return

    for filename in files:
        name, ext = os.path.splitext(filename)
        input_path = os.path.join(INPUT_FOLDER, filename)

        with Image.open(input_path) as img:
            resized = resize_image(img, MIN_WIDTH, MIN_HEIGHT)
            w, h = resized.size
            out_name = f"{name}-{w}x{h}{ext}"
            out_path = os.path.join(OUTPUT_FOLDER, out_name)
            resized.save(out_path)
            print(f"{filename} → {out_name}  ({img.size[0]}x{img.size[1]} → {w}x{h})")

    print(f"\nDone. {len(files)} image(s) processed.")

main()
