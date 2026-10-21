"""カメラ映像を見ながらコセットを並べるためのライブプレビュー。

重なり・交差している箇所をリアルタイムに表示する。
  赤: 交差している物体（丸印が交差点）
  橙: 交差点は無いが幅が太すぎる物体（横並びに重なっている疑い）
並べ終わったら SAVE（または 's' キー）で高解像度の静止画を保存し、main.py で測定する。

操作: 画面下のボタン、またはキー '-' / '+' (しきい値), 's' (保存), 'q' (終了)
"""
import datetime
import os

import cv2
import numpy as np

from config import (
    DEFAULT_THRESHOLD,
    LIVE_CAMERA_INDEX,
    LIVE_CAPTURE_SIZE,
    LIVE_SAVE_DIR,
)
from crossing import separate_strips
from marker_detection import detect_and_transform
from measurement import binarize, preprocess_backlit
from screen import compose, open_window

WINDOW_NAME = "Cossette Live"
BUTTONS = ["-", "+", "SAVE", "QUIT"]

CROSSING_COLOR = (0, 0, 255)
WIDE_COLOR = (0, 140, 255)


class Camera:
    """ラズパイのカメラ (Picamera2) を優先し、無ければOpenCVのVideoCaptureを使う。"""

    def __init__(self):
        try:
            from picamera2 import Picamera2
        except ImportError:
            Picamera2 = None

        if Picamera2 is not None:
            self._picam = Picamera2()
            # "RGB888" はメモリ上BGR順なのでOpenCVでそのまま扱える
            self._preview_config = self._picam.create_preview_configuration(
                main={"size": LIVE_CAPTURE_SIZE, "format": "RGB888"})
            self._still_config = self._picam.create_still_configuration(main={"format": "RGB888"})
            self._picam.configure(self._preview_config)
            self._picam.start()
            self._cap = None
        else:
            self._picam = None
            self._cap = cv2.VideoCapture(LIVE_CAMERA_INDEX)
            self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, LIVE_CAPTURE_SIZE[0])
            self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, LIVE_CAPTURE_SIZE[1])
            if not self._cap.isOpened():
                raise IOError(f"カメラ {LIVE_CAMERA_INDEX} を開けませんでした。")

    def read(self):
        if self._picam is not None:
            return self._picam.capture_array()
        ok, frame = self._cap.read()
        return frame if ok else None

    def capture_still(self):
        """測定用に最大解像度の静止画を撮影する。"""
        if self._picam is not None:
            return self._picam.switch_mode_and_capture_array(self._still_config)
        return self.read()

    def close(self):
        if self._picam is not None:
            self._picam.stop()
        else:
            self._cap.release()


def _annotate(bird_eye_view, separation):
    view = bird_eye_view.copy()
    for mask, color in ((separation.crossing_mask, CROSSING_COLOR), (separation.wide_mask, WIDE_COLOR)):
        tinted = (view * 0.4 + np.array(color) * 0.6).astype(np.uint8)
        view[mask > 0] = tinted[mask > 0]
    for x, y in separation.crossings:
        cv2.circle(view, (int(x), int(y)), 10, CROSSING_COLOR, 2)
    return view


def _save_still(camera):
    frame = camera.capture_still()
    os.makedirs(LIVE_SAVE_DIR, exist_ok=True)
    path = os.path.join(LIVE_SAVE_DIR, datetime.datetime.now().strftime("live_%Y%m%d_%H%M%S.jpg"))
    # 日本語パスにも対応するためエンコードしてから書き込む
    cv2.imencode(".jpg", frame)[1].tofile(path)
    print(f"'{path}' を保存しました。測定するには: uv run python main.py \"{path}\"")


def analyze_frame(frame, threshold_val):
    """1フレーム分の重なり検出を行い、(表示画像, ステータス文字列, ステータス色) を返す。"""
    result = detect_and_transform(frame)
    if not result.success:
        return frame, "MARKERS NOT FOUND", (0, 200, 255)

    gray = cv2.cvtColor(result.bird_eye_view, cv2.COLOR_BGR2GRAY)
    darkness = preprocess_backlit(gray, result.ar_marker_mask)
    separation = separate_strips(binarize(darkness, threshold_val), reconstruct=False)

    n_cross, n_wide = len(separation.crossings), int(cv2.connectedComponents(separation.wide_mask)[0] - 1)
    if n_cross == 0 and n_wide == 0:
        return _annotate(result.bird_eye_view, separation), "OK: no overlap", (0, 220, 0)
    return (_annotate(result.bird_eye_view, separation),
            f"OVERLAP {n_cross}  WIDE {n_wide}", CROSSING_COLOR)


def main():
    camera = Camera()
    state = {"threshold": DEFAULT_THRESHOLD, "action": None}

    def on_button(name):
        state["action"] = name

    open_window(WINDOW_NAME, on_button, BUTTONS)

    try:
        while True:
            frame = camera.read()
            if frame is None:
                print("エラー: カメラから画像を取得できませんでした。")
                break

            view, status, color = analyze_frame(frame, state["threshold"])
            cv2.imshow(WINDOW_NAME, compose(view, status, color, f"threshold {state['threshold']}", BUTTONS))

            key = cv2.waitKey(1) & 0xFF
            action = {ord("-"): "-", ord("+"): "+", ord("="): "+", ord("s"): "SAVE", ord("q"): "QUIT"}.get(key)
            action, state["action"] = action or state["action"], None

            if action == "-":
                state["threshold"] = max(state["threshold"] - 5, 0)
            elif action == "+":
                state["threshold"] = min(state["threshold"] + 5, 255)
            elif action == "SAVE":
                _save_still(camera)
            elif action == "QUIT":
                break
    finally:
        camera.close()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
