import os
from PIL import Image, ImageOps

def convert_icon():
    assets_dir = os.path.dirname(__file__)
    src_path = os.path.join(assets_dir, "settingicon.png")
    dst_path = os.path.join(assets_dir, "icon_settings.png")
    
    if not os.path.exists(src_path):
        print(f"[ERR] File not found: {src_path}")
        return

    # Load source icon
    img = Image.open(src_path)
    
    # Check if the image has real transparency
    has_real_transparency = False
    if img.mode in ('RGBA', 'LA') or (img.mode == 'P' and 'transparency' in img.info):
        alpha = img.convert("RGBA").split()[3]
        min_val, max_val = alpha.getextrema()
        if min_val < 250:
            has_real_transparency = True
        
    gray_img = img.convert("L")
    
    if has_real_transparency:
        # Split channels
        r, g, b, alpha = img.convert("RGBA").split()
        # Crop transparent margins
        bbox = alpha.getbbox()
        if bbox:
            alpha = alpha.crop(bbox)
        # Add uniform border spacing
        alpha = ImageOps.expand(alpha, border=4, fill=0)
        
        # Create a new image colored with theme's TEXT_PRIMARY (22, 22, 41)
        img_png = Image.new("RGBA", alpha.size, (22, 22, 41))
        img_png.putalpha(alpha)
    else:
        # Dark lines on white background (or opaque RGBA)
        inverted = ImageOps.invert(gray_img)
        # Crop white margins
        bbox = inverted.getbbox()
        if bbox:
            inverted = inverted.crop(bbox)
        # Add uniform border spacing
        inverted = ImageOps.expand(inverted, border=4, fill=0)
        
        img_png = Image.new("RGBA", inverted.size, (22, 22, 41))
        img_png.putalpha(inverted)
        
    # Save as icon_settings.png
    img_png.save(dst_path, "PNG")
    print(f"[CONV] Successfully updated {dst_path} using {src_path} with transparent alpha channel and crop!")

if __name__ == "__main__":
    convert_icon()
