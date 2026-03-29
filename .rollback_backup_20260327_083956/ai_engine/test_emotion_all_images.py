"""
Comprehensive emotion model test with all images from images/ folder.
Tests emotion inference on pre-cropped face images from each emotion category.
Processes all images at once across all emotion categories.
"""

import cv2
import numpy as np
from pathlib import Path
from collections import defaultdict
from emotion_engine import get_emotion_engine

def test_all_emotion_images():
    """Test emotion inference on all images in images/ folder (pre-cropped faces)."""
    print("\n" + "="*80)
    print("EMOTION MODEL TEST - CORRECTED PREPROCESSING (NO NORMALIZATION)")
    print("="*80 + "\n")
    
    emotion_engine = get_emotion_engine()
    emotion_engine.debug = False  # Disable debug output for cleaner results
    
    images_dir = Path(__file__).parent / "images"
    
    # Organize results by category
    results = defaultdict(list)
    errors = defaultdict(list)
    stats = {
        "total_images": 0,
        "total_processed": 0,
        "total_correct": 0,
        "total_errors": 0,
    }
    
    # Collect all images with their true labels
    all_images = []
    for category_dir in sorted(images_dir.iterdir()):
        if not category_dir.is_dir():
            continue
        
        category = category_dir.name
        image_files = sorted([
            f for f in category_dir.iterdir() 
            if f.suffix.lower() in ['.png', '.jpg', '.jpeg']
        ])
        
        for img_path in image_files:
            all_images.append((img_path, category))
            stats["total_images"] += 1
    
    print(f"📊 Found {stats['total_images']} images across {len(set(cat for _, cat in all_images))} categories\n")
    print("Processing all images...\n")
    
    # Process all images
    for img_path, true_category in all_images:
        img_name = img_path.name
        
        try:
            # Load image (these are already cropped faces)
            face_image = cv2.imread(str(img_path))
            if face_image is None:
                errors[true_category].append({
                    "image": img_name,
                    "error": "Could not read image file"
                })
                stats["total_errors"] += 1
                print(f"❌ {img_name}: Failed to read")
                continue
            
            # Run emotion inference directly on the pre-cropped face
            # (This is equivalent to the _crop_driver_face + predict pipeline)
            predicted_emotion, confidence = emotion_engine.predict(face_image)
            
            # Map category names to emotion names for validation
            category_to_emotion = {
                "angry": "anger",
                "happy": "happiness",
                "neutral": "neutral",
                "sad": "sadness"
            }
            expected_emotion = category_to_emotion.get(true_category, true_category)
            
            # Store result
            is_correct = predicted_emotion == expected_emotion
            results[true_category].append({
                "image": img_name,
                "predicted_emotion": predicted_emotion,
                "confidence": round(confidence, 3),
                "is_correct": is_correct,
            })
            
            stats["total_processed"] += 1
            if is_correct:
                stats["total_correct"] += 1
            
            # Print result
            status = "✅" if is_correct else "⚠️"
            conf_pct = f"{confidence*100:.1f}%"
            print(f"{status} [{true_category:8}] {img_name:20} → {predicted_emotion:12} ({conf_pct})")
            
        except Exception as e:
            errors[true_category].append({
                "image": img_name,
                "error": str(e)
            })
            stats["total_errors"] += 1
            print(f"❌ {img_name}: Error - {e}")
    
    # Detailed Summary statistics by category
    print("\n" + "="*80)
    print("DETAILED SUMMARY BY CATEGORY")
    print("="*80 + "\n")
    
    for category in sorted(results.keys()):
        category_results = results[category]
        if not category_results:
            continue
        
        correct = sum(1 for r in category_results if r["is_correct"])
        total = len(category_results)
        accuracy = (correct / total) * 100 if total > 0 else 0
        avg_confidence = np.mean([r['confidence'] for r in category_results])
        
        print(f"📁 {category.upper()}:")
        print(f"   Images: {total}")
        print(f"   Accuracy: {correct}/{total} ({accuracy:.1f}%)")
        print(f"   Avg Confidence: {avg_confidence:.1%}")
        
        # Show misclassifications
        misclassified = [r for r in category_results if not r["is_correct"]]
        if misclassified:
            print(f"   ⚠️  Misclassified: {len(misclassified)} images")
            for m in misclassified[:5]:  # Show first 5
                print(f"       {m['image']:20} → {m['predicted_emotion']:12} ({m['confidence']:.1%})")
        print()
    
    # Overall statistics
    print("-" * 80)
    print("📈 OVERALL STATISTICS:")
    print(f"   Total Images: {stats['total_images']}")
    print(f"   Successfully Processed: {stats['total_processed']}")
    print(f"   Errors: {stats['total_errors']}")
    
    if stats['total_processed'] > 0:
        overall_accuracy = (stats['total_correct'] / stats['total_processed']) * 100
        print(f"   Overall Accuracy: {stats['total_correct']}/{stats['total_processed']} ({overall_accuracy:.1f}%)")
    else:
        print("   ⚠️  No images were tested successfully")
    
    print("-" * 80 + "\n")
    
    return stats

if __name__ == "__main__":
    test_all_emotion_images()
