"""
Emotion Model Preprocessing Debug - All 5 Steps
Tests:
1. Input visualization
2. Both normalizations
3. Input shape verification
4. Extreme test cases
5. Raw logit distribution
"""

import cv2
import numpy as np
from pathlib import Path
from emotion_engine import get_emotion_engine

def run_debug_tests():
    """Run all 5 debug steps on test images."""
    print("\n" + "="*80)
    print("EMOTION MODEL PREPROCESSING DEBUG - ALL 5 STEPS")
    print("="*80 + "\n")
    
    # Get emotion engine and ENABLE DEBUG
    emotion_engine = get_emotion_engine()
    emotion_engine.debug = True  # Enable debug output
    
    images_dir = Path(__file__).parent / "images"
    
    # Get test images from each category
    test_images = {}
    for category_dir in sorted(images_dir.iterdir()):
        if not category_dir.is_dir():
            continue
        category = category_dir.name
        image_files = sorted([
            f for f in category_dir.iterdir() 
            if f.suffix.lower() in ['.png', '.jpg', '.jpeg']
        ])
        if image_files:
            test_images[category] = str(image_files[0])
    
    if not test_images:
        print("❌ No test images found!")
        return
    
    print(f"📦 Test images selected ({len(test_images)} categories):\n")
    for category, img_path in test_images.items():
        print(f"  {category:8}: {Path(img_path).name}")
    
    # Step 1-5: Test each image with full debug output
    for category, img_path in test_images.items():
        print("\n" + "-"*80)
        print(f"TESTING: {category.upper()} - {Path(img_path).name}")
        print("-"*80)
        
        image_bgr = cv2.imread(str(img_path))
        if image_bgr is None:
            print(f"❌ Failed to load image")
            continue
        
        print(f"\n📸 Step 1: Input Shape Check")
        print(f"  Raw image shape: {image_bgr.shape}")
        
        # Run prediction with full debug output and visualization
        print(f"\n🔍 Steps 2-5: Running with full debug output...\n")
        emotion_label, confidence = emotion_engine.predict(
            image_bgr,
            debug_viz=True  # Enable full debug output
        )
        
        print(f"\n✅ Result: {emotion_label} ({confidence:.1%})")
        print(f"   Expected: {category}")
        print(f"   Match: {'✅ YES' if emotion_label == category else '❌ NO'}")
    
    print("\n" + "="*80)
    print("DEBUG REPORT COMPLETE")
    print("="*80)
    print("\n📋 INTERPRETATION GUIDE:")
    print("""
  Raw logits distribution:
  ✅ If values spread (e.g., [3.2, 0.1, -1.5]): Good, model is discriminating
  ❌ If all similar (e.g., [0.5, 0.4, 0.6]): Bad, broken preprocessing
  
  If still all neutral:
  • Check the Min/Max/Mean values for normalization
  • If Min/Max are both ~0.0, then image is either black or broken
  • If values look right but emotion is wrong, model may need retraining
  
  Next steps:
  1. Review the normalization output (Step 2)
  2. Check if logits have good spread (Step 5)
  3. If logits are flat → preprocessing is broken
  4. If logits have spread but wrong emotion → model/training issue
    """)

if __name__ == "__main__":
    run_debug_tests()
