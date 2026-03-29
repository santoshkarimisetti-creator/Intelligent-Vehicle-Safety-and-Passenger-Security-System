"""
Test ONNX model integrity and trained state
"""

import numpy as np
import onnxruntime as ort
from pathlib import Path

def check_onnx_model():
    print("\n" + "="*80)
    print("ONNX MODEL INTEGRITY CHECK")
    print("="*80 + "\n")
    
    model_path = Path(__file__).parent / "models" / "emotion_model.onnx"
    
    print(f"📁 Model path: {model_path}")
    print(f"📊 File size: {model_path.stat().st_size / (1024*1024):.2f} MB")
    
    try:
        # Load ONNX model
        session = ort.InferenceSession(str(model_path))
        print(f"✅ Model loaded successfully\n")
        
        # Get model info
        inputs = session.get_inputs()
        outputs = session.get_outputs()
        
        print(f"📋 Model Inputs:")
        for inp in inputs:
            print(f"  Name: {inp.name}")
            print(f"  Shape: {inp.shape}")
            print(f"  Type: {inp.type}\n")
        
        print(f"📋 Model Outputs:")
        for out in outputs:
            print(f"  Name: {out.name}")
            print(f"  Shape: {out.shape}")
            print(f"  Type: {out.type}\n")
        
        # Test with random input
        print("🧪 Testing with RANDOM INPUT (all trained models should vary):\n")
        
        for test_num in range(5):
            # Create random input matching model spec
            random_input = np.random.randn(1, 1, 64, 64).astype(np.float32)
            
            outputs_result = session.run(None, {"Input3": random_input})
            logits = outputs_result[0][0]
            probs = np.exp(logits - np.max(logits)) / np.sum(np.exp(logits - np.max(logits)))
            top_emotion_idx = np.argmax(probs)
            top_emotion_prob = probs[top_emotion_idx]
            
            emotions = ["neutral", "happiness", "surprise", "sadness", "anger", "disgust", "fear", "contempt"]
            emotion = emotions[top_emotion_idx]
            
            print(f"  Test {test_num+1}: {emotion} ({top_emotion_prob:.1%})")
        
        print("\n📊 Analysis:")
        print("  ✅ If outputs vary significantly → Model is properly trained")
        print("  ❌ If outputs are nearly identical → Model is not trained (untrained/corrupted)")
        
    except Exception as e:
        print(f"❌ Error loading model: {e}")

if __name__ == "__main__":
    check_onnx_model()
