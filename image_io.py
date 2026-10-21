import tkinter as tk
from tkinter import filedialog

import cv2
import numpy as np


def select_image_path():
    """ファイルダイアログを開いて画像ファイルのパスを選択する。未選択ならNone。"""
    root = tk.Tk()
    root.withdraw()  # 小さなtkウィンドウを表示しない
    image_path = filedialog.askopenfilename(
        title="画像ファイルを選択してください",
        filetypes=[("Image files", "*.jpg *.jpeg *.png *.bmp *.gif"), ("All files", "*.*")]
    )
    return image_path or None


def load_image(image_path):
    """画像を読み込む。UTF-8などのマルチバイト文字パスに対応するためバイナリ経由でデコードする。"""
    n = np.fromfile(image_path, np.uint8)
    frame = cv2.imdecode(n, cv2.IMREAD_COLOR)
    if frame is None:
        raise IOError("ファイルをデコードできません。画像ファイルが破損しているか、非対応のフォーマットの可能性があります。")
    return frame
