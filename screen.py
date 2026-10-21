"""小さい画面（ラズパイのタッチディスプレイ）向けの1枚ウィンドウ表示。

上部に画像、下部にステータスとボタンを並べる。ボタンはタッチ（クリック）で操作できる。
"""
import cv2
import numpy as np

from config import DISPLAY_FULLSCREEN, DISPLAY_SIZE

BAR_HEIGHT = 56
BUTTON_WIDTH = 90


def open_window(name, on_button, buttons):
    """ウィンドウを開き、ボタンが押されたら on_button(ボタン名) を呼ぶ。"""
    cv2.namedWindow(name, cv2.WINDOW_NORMAL)
    if DISPLAY_FULLSCREEN:
        cv2.setWindowProperty(name, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
    else:
        cv2.resizeWindow(name, *DISPLAY_SIZE)

    def on_mouse(event, x, y, flags, param):
        if event != cv2.EVENT_LBUTTONDOWN:
            return
        for button, (bx, by, bw, bh) in _button_rects(buttons).items():
            if bx <= x < bx + bw and by <= y < by + bh:
                on_button(button)

    cv2.setMouseCallback(name, on_mouse)


def _button_rects(buttons):
    w, h = DISPLAY_SIZE
    y = h - BAR_HEIGHT
    return {
        name: (w - BUTTON_WIDTH * (len(buttons) - i), y, BUTTON_WIDTH, BAR_HEIGHT)
        for i, name in enumerate(buttons)
    }


def compose(image, status_text, status_color, sub_text, buttons):
    """画像を画面サイズに収め、下部にステータス・補足・ボタンを描いた表示用画像を返す。"""
    w, h = DISPLAY_SIZE
    canvas = np.full((h, w, 3), 20, np.uint8)

    area_h = h - BAR_HEIGHT
    scale = min(w / image.shape[1], area_h / image.shape[0])
    resized = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    ox, oy = (w - resized.shape[1]) // 2, (area_h - resized.shape[0]) // 2
    canvas[oy:oy + resized.shape[0], ox:ox + resized.shape[1]] = resized

    font = cv2.FONT_HERSHEY_SIMPLEX
    cv2.putText(canvas, status_text, (10, h - 30), font, 0.7, status_color, 2, cv2.LINE_AA)
    cv2.putText(canvas, sub_text, (10, h - 8), font, 0.5, (200, 200, 200), 1, cv2.LINE_AA)
    for name, (x, y, bw, bh) in _button_rects(buttons).items():
        cv2.rectangle(canvas, (x + 3, y + 4), (x + bw - 3, y + bh - 4), (70, 70, 70), -1)
        (tw, th), _ = cv2.getTextSize(name, font, 0.7, 2)
        cv2.putText(canvas, name, (x + (bw - tw) // 2, y + (bh + th) // 2), font, 0.7,
                    (255, 255, 255), 2, cv2.LINE_AA)
    return canvas
