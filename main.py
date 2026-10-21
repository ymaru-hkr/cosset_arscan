"""コセット測定アプリ（カメラ）。普段はこれだけを起動しておく。

1. ライブプレビュー: 重なり・交差している箇所をリアルタイムに表示する
     赤: 交差している物体（丸印が交差点）
     橙: 交差点は無いが幅が太すぎる物体（横並びに重なっている疑い）
2. SHOT ボタン・タクトスイッチ・'s' キーのいずれかで高解像度の静止画を撮影する
   （4つのARマーカーが読めていないときは撮影できない）
3. 測定画面でしきい値を調整し、SAVE で results/日付/時刻/ に保存（BACK で保存せずに戻る）
4. ライブプレビューに戻る

操作: 画面下のボタン、またはキー '-' / '+' (しきい値), 's' (撮影), 'q' (終了)
保存済みの画像を測定するときは measure_image.py を使う。
"""
import os
import time

import cv2
import numpy as np

from config import (
    CAPTURE_BUTTON_GPIO,
    DEFAULT_THRESHOLD,
    LIVE_CAMERA_INDEX,
    LIVE_CAPTURE_SIZE,
)
from crossing import separate_strips
from marker_detection import detect_and_transform
from measure_image import measure_frame
from measurement import binarize, preprocess_backlit
from screen import WINDOW_NAME, compose, open_window

BUTTONS = ["-", "+", "SHOT", "QUIT"]
MESSAGE_SECONDS = 3  # 保存結果のメッセージを表示しておく秒数

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


def _open_capture_switch(on_press):
    """タクトスイッチ (GPIO) を開く。gpiozero が無い環境 (Macなど) や未設定なら何もしない。"""
    if CAPTURE_BUTTON_GPIO is None:
        return None
    try:
        from gpiozero import Button
    except ImportError:
        return None
    switch = Button(CAPTURE_BUTTON_GPIO, pull_up=True, bounce_time=0.05)
    switch.when_pressed = on_press
    return switch


def _shoot_and_measure(camera, threshold_val):
    """静止画を撮影して測定画面に移る。戻り値: (ステータス文字列, ステータス色)"""
    frame = camera.capture_still()
    if frame is None or not detect_and_transform(frame.copy()).success:
        print("撮影した静止画でARマーカーが読めなかったため、測定できませんでした。")
        return "SHOT FAILED: markers not found", (0, 0, 255)

    output_dir = measure_frame(frame, "capture.jpg", cancel_label="BACK",
                               save_original=True, initial_threshold=threshold_val)
    if output_dir is None:
        return "NOT SAVED", (0, 200, 255)
    # 表示は「日付/時刻」だけにする
    return f"SAVED {os.path.relpath(output_dir, os.path.dirname(os.path.dirname(output_dir)))}", (0, 220, 0)


def analyze_frame(frame, threshold_val):
    """1フレーム分の重なり検出を行い、(表示画像, ステータス文字列, ステータス色, マーカー検出成否) を返す。

    マーカーが読めないときもカメラ映像をそのまま返す（プレビューは常に表示する）。
    """
    result = detect_and_transform(frame)
    if not result.success:
        return frame, "MARKERS NOT FOUND - cannot shoot", (0, 200, 255), False

    gray = cv2.cvtColor(result.bird_eye_view, cv2.COLOR_BGR2GRAY)
    darkness = preprocess_backlit(gray, result.ar_marker_mask)
    separation = separate_strips(binarize(darkness, threshold_val), reconstruct=False)

    n_cross, n_wide = len(separation.crossings), int(cv2.connectedComponents(separation.wide_mask)[0] - 1)
    if n_cross == 0 and n_wide == 0:
        return _annotate(result.bird_eye_view, separation), "OK: no overlap", (0, 220, 0), True
    return (_annotate(result.bird_eye_view, separation),
            f"OVERLAP {n_cross}  WIDE {n_wide}", CROSSING_COLOR, True)


def main():
    camera = Camera()
    state = {"threshold": DEFAULT_THRESHOLD, "action": None, "message": None}

    def on_button(name):
        state["action"] = name

    def on_switch():
        # 測定画面を表示している間のスイッチ操作は無視する
        if not state["measuring"]:
            on_button("SHOT")

    state["measuring"] = False
    open_window(WINDOW_NAME, on_button, BUTTONS)
    switch = _open_capture_switch(on_switch)

    try:
        while True:
            frame = camera.read()
            if frame is None:
                print("エラー: カメラから画像を取得できませんでした。")
                break

            view, status, color, can_shoot = analyze_frame(frame, state["threshold"])
            message = state["message"]
            if message and time.monotonic() < message[2]:
                status, color = message[0], message[1]
            cv2.imshow(WINDOW_NAME, compose(
                view, status, color, f"threshold {state['threshold']}", BUTTONS,
                disabled=() if can_shoot else ("SHOT",)
            ))

            key = cv2.waitKey(1) & 0xFF
            action = {ord("-"): "-", ord("+"): "+", ord("="): "+", ord("s"): "SHOT", ord("q"): "QUIT"}.get(key)
            action, state["action"] = action or state["action"], None

            if action == "-":
                state["threshold"] = max(state["threshold"] - 5, 0)
            elif action == "+":
                state["threshold"] = min(state["threshold"] + 5, 255)
            elif action == "SHOT":
                if not can_shoot:
                    print("ARマーカーが読めていないため撮影できません。")
                    continue
                state["measuring"] = True
                status, color = _shoot_and_measure(camera, state["threshold"])
                state["measuring"] = False
                state["message"] = (status, color, time.monotonic() + MESSAGE_SECONDS)
                # 測定画面がボタンの割り当てを変えているので、ライブプレビュー用に戻す
                open_window(WINDOW_NAME, on_button, BUTTONS)
                state["action"] = None
            elif action == "QUIT":
                break
    finally:
        if switch is not None:
            switch.close()
        camera.close()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
