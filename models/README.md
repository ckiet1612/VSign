# Hand tracking model

`hand_landmarker.task` is the MediaPipe Hand Landmarker float16 model published
by Google. It is loaded locally by the browser so webcam frames do not need to
leave the device for the tracking overlay.

Source:
https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task

SHA-256:
`fbc2a30080c3c557093b5ddfc334698132eb341044ccee322ccf8bcf3607cde1`

## Pose tracking model

`pose_landmarker_lite.task` là MediaPipe Pose Landmarker Lite float16, được tải
local cùng Hand Landmarker. SHA-256:
`59929e1d1ee95287735ddd833b19cf4ac46d29bc7afddbbf6753c459690d574a`.

## VSign unified landmark V4.2

`vsign-landmark-v4.onnx` và `vsign-landmark-v4.labels.json` được tạo bằng:

```bash
.venv/bin/python -m ml.scripts.extract_landmarks_v4
.venv/bin/python -m ml.scripts.build_idle_landmarks_v4
.venv/bin/python -m ml.scripts.train_landmarks_v4
```

V4.2 nhận `16 × 183` feature, gồm hand shape, upper-body pose, quan hệ hai tay
và mask che khuất. V2/V3 và school expert được giữ làm artifact so
sánh/fallback đánh giá. Browser mặc định chỉ tải một model V4. Không đổi thứ tự labels nếu không train/export
lại model cùng lúc.
