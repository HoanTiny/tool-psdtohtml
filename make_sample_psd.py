"""
Sinh 1 file PSD mau nhieu layer de test parser (chi dung khi chua co PSD that).
Dung PIL ve tung layer roi nhoi vao pytoshop lam layer pixel.
"""
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import pytoshop
from pytoshop.user import nested_layers
from pytoshop.enums import ColorMode, Compression

W, H = 800, 600


def solid(w, h, rgba):
    return Image.new("RGBA", (w, h), rgba)


def with_text(w, h, rgba, text, fill, size=28):
    img = Image.new("RGBA", (w, h), rgba)
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("arial.ttf", size)
    except Exception:
        font = ImageFont.load_default()
    tb = d.textbbox((0, 0), text, font=font)
    tw, th = tb[2] - tb[0], tb[3] - tb[1]
    d.text(((w - tw) / 2, (h - th) / 2 - tb[1]), text, fill=fill, font=font)
    return img


def to_layer(name, pil_img, left, top):
    """Chuyen PIL RGBA -> nested_layers.Image cua pytoshop."""
    arr = np.asarray(pil_img)  # (h, w, 4)
    h, w = arr.shape[:2]
    channels = {
        0: arr[:, :, 0],
        1: arr[:, :, 1],
        2: arr[:, :, 2],
        -1: arr[:, :, 3],
    }
    return nested_layers.Image(
        name=name, visible=True, opacity=255,
        top=top, left=left, bottom=top + h, right=left + w,
        channels=channels,
    )


layers = [
    # Ve tu tren xuong; pytoshop xep layer[0] o TREN cung.
    to_layer("Button - Dang nhap", with_text(200, 50, (37, 99, 235, 255), "Dang nhap", (255, 255, 255, 255), 22), 300, 400),
    to_layer("Subtitle", with_text(500, 40, (0, 0, 0, 0), "Chao mung tro lai", (100, 100, 100, 255), 20), 150, 300),
    to_layer("Title", with_text(600, 60, (0, 0, 0, 0), "PSD to HTML", (17, 24, 39, 255), 40), 100, 210),
    to_layer("Header bar", solid(800, 90, (17, 24, 39, 255)), 0, 0),
    to_layer("Background", solid(800, 600, (243, 244, 246, 255)), 0, 0),
]

psd = nested_layers.nested_layers_to_psd(layers, color_mode=ColorMode.rgb, compression=Compression.raw)
with open("sample.psd", "wb") as f:
    psd.write(f)
print("Da tao sample.psd", W, "x", H)
