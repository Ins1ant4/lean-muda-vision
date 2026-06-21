import os
from PIL import Image, ImageDraw, ImageOps

def generate_icons():
    assets_dir = os.path.dirname(__file__)
    os.makedirs(assets_dir, exist_ok=True)
    
    COLOR_PRIMARY = "#161629"  # theme.TEXT_PRIMARY
    COLOR_BLUE = "#1F20C3"     # theme.BRAND_PRIMARY
    
    # ── 1. LIVE MONITOR ICON ──
    # Size 96x96 (scaled down to 24x24 in CTkImage for high quality)
    img_live = Image.new("RGBA", (96, 96), (0, 0, 0, 0))
    draw_live = ImageDraw.Draw(img_live)
    
    # Draw L-shaped Axis
    draw_live.line([(16, 16), (16, 80), (80, 80)], fill=COLOR_PRIMARY, width=5, joint="round")
    
    # Draw Bars (rounded rectangles)
    # Bar 1
    draw_live.rounded_rectangle((26, 52, 38, 76), radius=3, outline=COLOR_PRIMARY, width=4)
    # Bar 2
    draw_live.rounded_rectangle((44, 36, 56, 76), radius=3, outline=COLOR_PRIMARY, width=4)
    # Bar 3
    draw_live.rounded_rectangle((62, 20, 74, 76), radius=3, outline=COLOR_PRIMARY, width=4)
    
    # Draw Trend Line
    draw_live.line([(22, 60), (40, 42), (58, 48), (76, 22)], fill=COLOR_PRIMARY, width=4, joint="round")
    
    # Draw Trend Line Nodes (small dots)
    nodes = [(22, 60), (40, 42), (58, 48), (76, 22)]
    for nx, ny in nodes:
        draw_live.ellipse((nx - 4, ny - 4, nx + 4, ny + 4), fill=COLOR_PRIMARY)
        
    img_live.save(os.path.join(assets_dir, "icon_live.png"), "PNG")
    
    # ── 2. PERFORMANCE HISTORY ICON ──
    # Clock face + wrapping arrow + hands
    img_hist = Image.new("RGBA", (96, 96), (0, 0, 0, 0))
    draw_hist = ImageDraw.Draw(img_hist)
    
    # Clock hands
    draw_hist.line([(48, 48), (48, 26)], fill=COLOR_PRIMARY, width=5, joint="round")
    draw_hist.line([(48, 48), (70, 48)], fill=COLOR_PRIMARY, width=5, joint="round")
    
    # Clock face (circular arc to make it look like a history loop)
    # start=-120, end=210 degrees
    draw_hist.arc((16, 16, 80, 80), start=-120, end=210, fill=COLOR_PRIMARY, width=5)
    
    # Draw arrow head at the end of the arc
    # Arrow head points counter-clockwise (downwards-left at the top-left of the circle)
    # Arrow head shape: triangle
    draw_hist.polygon([(24, 28), (34, 14), (20, 16)], fill=COLOR_PRIMARY)
    
    img_hist.save(os.path.join(assets_dir, "icon_hist.png"), "PNG")
    
    # ── 3. DETAILS INFO ICON ──
    # Blue circle outline with letter "i" in the center
    img_details = Image.new("RGBA", (96, 96), (0, 0, 0, 0))
    draw_details = ImageDraw.Draw(img_details)
    
    # Draw Circle
    draw_details.ellipse((16, 16, 80, 80), outline=COLOR_BLUE, width=5)
    
    # Draw letter "i" (dot and body)
    draw_details.ellipse((48 - 4, 32 - 4, 48 + 4, 32 + 4), fill=COLOR_BLUE)
    draw_details.line([(48, 42), (48, 64)], fill=COLOR_BLUE, width=6)
    
    img_details.save(os.path.join(assets_dir, "icon_details.png"), "PNG")
    
    # ── 4. SETTINGS GEAR ICON ──
    # Gear outline (centered 48, 48)
    img_settings = Image.new("RGBA", (96, 96), (0, 0, 0, 0))
    draw_settings = ImageDraw.Draw(img_settings)
    
    # Draw concentric circles
    draw_settings.ellipse((48 - 24, 48 - 24, 48 + 24, 48 + 24), outline=COLOR_PRIMARY, width=5)
    draw_settings.ellipse((48 - 12, 48 - 12, 48 + 12, 48 + 12), outline=COLOR_PRIMARY, width=5)
    
    # Draw 8 teeth radiating outwards
    import math
    for i in range(8):
        angle = math.radians(i * 45)
        x0 = 48 + 24 * math.cos(angle)
        y0 = 48 + 24 * math.sin(angle)
        x1 = 48 + 34 * math.cos(angle)
        y1 = 48 + 34 * math.sin(angle)
        draw_settings.line([(x0, y0), (x1, y1)], fill=COLOR_PRIMARY, width=7, joint="round")
        
    # Crop transparent margins and expand 4px border spacing
    bbox = img_settings.split()[3].getbbox()
    if bbox:
        img_settings = img_settings.crop(bbox)
    img_settings = ImageOps.expand(img_settings, border=4, fill=0)
    
    img_settings.save(os.path.join(assets_dir, "icon_settings.png"), "PNG")
    
    print("[GEN] Icons successfully generated!")

if __name__ == "__main__":
    generate_icons()
