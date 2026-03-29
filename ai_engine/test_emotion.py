import cv2
from pathlib import Path
from emotion_engine import EmotionEngine

engine = EmotionEngine()

base_dir = Path(__file__).resolve().parent
candidates = [
	Path.cwd() / "mine.jpg",
	base_dir / "mine.jpg",
	base_dir / "images" / "mine.jpg",
]

img = None
for p in candidates:
	img = cv2.imread(str(p))
	if img is not None:
		break

if img is None:
	raise RuntimeError("Could not read mine.jpg from current working directory or ai_engine/images")

if hasattr(engine, "predict"):
	emotion, conf = engine.predict(img)
else:
	result = engine.analyze_periodic(
		session_key="temp_test",
		image_bgr=img,
		driver_bbox=None,
		passenger_bboxes=[],
		force=True,
	)
	driver_info = result.get("driver_emotion", {}) or {}
	emotion = str(driver_info.get("driver_emotion", "unknown"))
	conf = float(driver_info.get("confidence", 0.0) or 0.0)

print("Emotion:", emotion)
print("Confidence:", conf)
