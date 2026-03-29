#!/usr/bin/env python3
"""Generate actual-vs-predicted emotion table for all test images."""

from pathlib import Path
import sys

import cv2


def main() -> None:
    base_dir = Path(__file__).resolve().parent.parent
    if str(base_dir) not in sys.path:
        sys.path.insert(0, str(base_dir))

    from emotion_engine import get_emotion_engine

    images_dir = base_dir / "images"

    category_dirs = [d for d in images_dir.iterdir() if d.is_dir()]
    category_dirs.sort(key=lambda p: p.name)

    engine = get_emotion_engine()
    engine.debug = False

    rows = []
    total = 0
    correct = 0

    category_to_expected = {
        "angry": "anger",
        "happy": "happiness",
        "neutral": "neutral",
        "sad": "sadness",
    }

    for category_dir in category_dirs:
        actual_category = category_dir.name.lower()
        expected_emotion = category_to_expected.get(actual_category, actual_category)

        image_files = []
        for ext in ("*.png", "*.jpg", "*.jpeg"):
            image_files.extend(category_dir.glob(ext))
        image_files.sort(key=lambda p: p.name)

        for image_path in image_files:
            face_image = cv2.imread(str(image_path))
            if face_image is None:
                rows.append((actual_category, image_path.name, "READ_ERROR", 0.0, "NO"))
                continue

            predicted, confidence = engine.predict(face_image)
            is_correct = predicted == expected_emotion

            total += 1
            if is_correct:
                correct += 1

            rows.append(
                (
                    actual_category,
                    image_path.name,
                    predicted,
                    round(confidence * 100.0, 1),
                    "YES" if is_correct else "NO",
                )
            )

    print("| Actual Category | Image | Predicted Emotion | Confidence % | Correct |")
    print("|---|---|---|---:|---|")
    for actual, image, predicted, conf, ok in rows:
        print(f"| {actual} | {image} | {predicted} | {conf:.1f} | {ok} |")

    accuracy = (correct / total * 100.0) if total else 0.0
    print("")
    print(f"Total processed: {total}")
    print(f"Correct: {correct}")
    print(f"Accuracy: {accuracy:.1f}%")


if __name__ == "__main__":
    main()
