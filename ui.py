import cv2

from measurement import process_frame
from screen import WINDOW_NAME, compose, open_window


def run_interactive_measurement(gray_image_masked, base_bird_eye_view, mm_per_pixel,
                                 file_name_with_ext, timestamp, initial_threshold, cancel_label="QUIT"):
    """1枚のウィンドウで測定結果のプレビューとしきい値調整を行い、SAVE/キャンセル操作を待つ。

    cancel_label: 保存せずに戻るボタンの名前（カメラから測定する場合は "BACK"）

    戻り値: (saved, output_lines, object_data, bird_eye_view_img)
    """
    buttons = ["-", "+", "SAVE", cancel_label]
    state = {'threshold': initial_threshold, 'action': None}
    latest = {}

    def update_and_process():
        output_lines, object_data, processed_img = process_frame(
            gray_image_masked, base_bird_eye_view, mm_per_pixel,
            state['threshold'], file_name_with_ext, timestamp
        )
        latest['output_lines'] = output_lines
        latest['object_data'] = object_data
        latest['bird_eye_view_img'] = processed_img
        cv2.imshow(WINDOW_NAME, compose(
            processed_img, f"objects {len(object_data)}", (0, 220, 0),
            f"threshold {state['threshold']}", buttons
        ))

    def on_button(name):
        state['action'] = name

    open_window(WINDOW_NAME, on_button, buttons)
    update_and_process()

    print("\nプレビュー画面で操作できます:")
    print("  '-' / '+' ボタン (キー '-' / '+') でしきい値を調整します。")
    print("  SAVE ボタン ('s' キー) で現在の状態で結果を保存します。")
    print(f"  {cancel_label} ボタン ('q' キー) で保存せずに戻ります。")

    saved = False
    while True:
        key = cv2.waitKey(20) & 0xFF
        action = {ord('-'): '-', ord('+'): '+', ord('='): '+', ord('s'): 'SAVE', ord('q'): cancel_label}.get(key)
        action, state['action'] = action or state['action'], None

        if action in ('-', '+'):
            step = -1 if action == '-' else 1
            state['threshold'] = min(max(state['threshold'] + step, 0), 255)
            update_and_process()
        elif action == 'SAVE':
            print("\nSAVEが押されました。ファイルを保存します...")
            saved = True
            break
        elif action == cancel_label:
            print(f"\n{cancel_label}が押されました。ファイルを保存せずに戻ります。")
            break

    return (
        saved,
        latest.get('output_lines', []),
        latest.get('object_data', []),
        latest.get('bird_eye_view_img', base_bird_eye_view),
    )
