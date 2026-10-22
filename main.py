"""コセット測定アプリ（カメラ）。普段はこれだけを起動しておく。

1. ライブプレビュー: 重なり・交差している箇所をリアルタイムに表示する
     赤: 交差している物体（丸印が交差点）
     橙: 交差点は無いが幅が太すぎる物体（横並びに重なっている疑い）
   しきい値はここで調整する（測定にもこのしきい値を使う）
2. SHOT ボタン・タクトスイッチ・'s' キーのいずれかで高解像度の静止画を撮影する
   （4つのARマーカーが読めていないときは撮影できない）
3. 今のしきい値で自動で測定し、results/日付/時刻/ に保存する（CSVはGoogle Driveにも送る）
4. すぐにライブプレビューに戻り、結果のメッセージを数秒表示する

操作: 画面下のボタン、またはキー '-' / '+' (しきい値), 's' (撮影), 'q' (終了)
保存済みの画像を測定するときは measure_image.py を使う。
"""
import os
import threading
import time

import cv2
import numpy as np

from camera import open_camera
from config import CAPTURE_BUTTON_GPIO, DEFAULT_THRESHOLD, MESSAGE_SECONDS
from crossing import separate_strips
from marker_detection import detect_and_transform
from gdrive import gdrive_enabled, save_csv_to_gdrive
from measure_image import measure_and_save
from measurement import binarize, preprocess_backlit
from screen import WINDOW_NAME, compose, draw_banner, open_window

BUTTONS = ["-", "+", "SHOT", "QUIT"]
THRESHOLD_STEP = 2

CROSSING_COLOR = (0, 0, 255)
WIDE_COLOR = (0, 140, 255)


def _annotate(bird_eye_view, separation):
    view = bird_eye_view.copy()
    for mask, color in ((separation.crossing_mask, CROSSING_COLOR), (separation.wide_mask, WIDE_COLOR)):
        tinted = (view * 0.4 + np.array(color) * 0.6).astype(np.uint8)
        view[mask > 0] = tinted[mask > 0]
    for x, y in separation.crossings:
        cv2.circle(view, (int(x), int(y)), 10, CROSSING_COLOR, 2)
    return view


def _open_capture_switch(on_press):
    """タクトスイッチ (GPIO) を開く。使えない環境 (Macなど) や未設定なら理由を表示して None を返す。"""
    if CAPTURE_BUTTON_GPIO is None:
        print("タクトスイッチ: 無効 (CAPTURE_BUTTON_GPIO = None)")
        return None
    try:
        from gpiozero import Button
    except ImportError:
        print("タクトスイッチ: 無効 (gpiozero を読み込めません。README の「タクトスイッチ」を参照)")
        return None
    try:
        switch = Button(CAPTURE_BUTTON_GPIO, pull_up=True, bounce_time=0.05)
    except Exception as e:
        # ピンの制御ライブラリ (lgpio など) が無い・GPIOが使用中などの場合
        print(f"タクトスイッチ: 無効 (GPIO{CAPTURE_BUTTON_GPIO} を開けません: {type(e).__name__}: {e})")
        return None
    switch.when_pressed = on_press
    print(f"タクトスイッチ: GPIO{CAPTURE_BUTTON_GPIO} で待機中")
    return switch


def _show_message(state, lines_ja, lines_en, color):
    """プレビュー画面にメッセージを MESSAGE_SECONDS 秒表示させる。"""
    state["message"] = (lines_ja, lines_en, color, time.monotonic() + MESSAGE_SECONDS)


def _upload_in_background(state, csv_path, timestamp):
    """CSVをGoogle Driveに送る。時間がかかることがあるので別スレッドで行い、結果を画面の表示に書き足す。"""
    lines_ja, lines_en, color, _ = state["message"]
    # 送信が終わるまでは「送信中」と表示し、終わったら結果に置き換える
    _show_message(state, lines_ja + ["Google Driveに送信中..."], lines_en + ["Uploading to Google Drive..."], color)

    def run():
        if save_csv_to_gdrive(csv_path, timestamp):
            _show_message(state, lines_ja + ["Google Driveにも保存しました"],
                          lines_en + ["Also saved to Google Drive"], color)
        else:
            _show_message(state, lines_ja + ["※ Google Driveへの送信に失敗しました"],
                          lines_en + ["Google Drive upload failed"], (0, 165, 255))
    threading.Thread(target=run, daemon=True).start()


def _shoot_and_measure(camera, state):
    """静止画を撮影し、今のしきい値で自動で測定・保存して、結果のメッセージを設定する。"""
    frame = camera.capture_still()
    measured = measure_and_save(frame, "capture.jpg", state["threshold"]) if frame is not None else None
    if measured is None:
        print("撮影した静止画でARマーカーが読めなかったため、保存しませんでした。")
        _show_message(state, ["マーカーが読めませんでした", "保存していません。もう一度撮影してください"],
                      ["Markers not found", "not saved - please shoot again"], (0, 0, 255))
        return

    output_dir, n_objects, csv_path, timestamp = measured
    # 表示は「日付/時刻」だけにする
    saved_as = os.path.relpath(output_dir, os.path.dirname(os.path.dirname(output_dir)))
    _show_message(state, ["撮影しました", f"{saved_as} に保存  ({n_objects}個を測定)"],
                  ["Saved", f"{saved_as}  ({n_objects} objects)"], (0, 220, 0))
    if csv_path and gdrive_enabled():
        _upload_in_background(state, csv_path, timestamp)


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
    camera = open_camera()
    state = {"threshold": DEFAULT_THRESHOLD, "action": None, "message": None, "busy": False}

    def on_button(name):
        state["action"] = name

    def on_switch():
        # 撮影・保存中のスイッチ操作は無視する
        if not state["busy"]:
            on_button("SHOT")

    open_window(WINDOW_NAME, on_button, BUTTONS)
    switch = _open_capture_switch(on_switch)

    try:
        while True:
            frame = camera.read()
            if frame is None:
                print("エラー: カメラから画像を取得できませんでした。")
                break

            view, status, color, can_shoot = analyze_frame(frame, state["threshold"])
            canvas = compose(view, status, color, f"threshold {state['threshold']}", BUTTONS,
                             disabled=() if can_shoot else ("SHOT",))
            message = state["message"]
            if message and time.monotonic() < message[3]:
                cv2.imshow(WINDOW_NAME, draw_banner(canvas.copy(), *message[:3]))
            else:
                cv2.imshow(WINDOW_NAME, canvas)

            key = cv2.waitKey(1) & 0xFF
            action = {ord("-"): "-", ord("+"): "+", ord("="): "+", ord("s"): "SHOT", ord("q"): "QUIT"}.get(key)
            action, state["action"] = action or state["action"], None

            if action == "-":
                state["threshold"] = max(state["threshold"] - THRESHOLD_STEP, 0)
            elif action == "+":
                state["threshold"] = min(state["threshold"] + THRESHOLD_STEP, 255)
            elif action == "SHOT":
                if not can_shoot:
                    print("ARマーカーが読めていないため撮影できません。")
                    continue
                state["busy"] = True
                # 撮影・測定には数秒かかるので、その間も分かるように表示しておく
                cv2.imshow(WINDOW_NAME, draw_banner(canvas, ["撮影中..."], ["Shooting..."], (255, 255, 255)))
                cv2.waitKey(1)
                _shoot_and_measure(camera, state)
                state["busy"] = False
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
