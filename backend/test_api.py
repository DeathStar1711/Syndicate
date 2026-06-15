import os
import joblib
from src.utils.helpers import get_data_dir

model_dir = os.path.join(get_data_dir(), "models")
meta_path = os.path.join(model_dir, "model_metadata.pkl")
model_path = os.path.join(model_dir, "model_latest.pkl")

model_exists = os.path.exists(model_path)
print("Model exists:", model_exists)

if model_exists and os.path.exists(meta_path):
    try:
        meta = joblib.load(meta_path)
        print("Meta keys:", meta.keys())
    except Exception as e:
        print("Error loading meta:", e)
else:
    print("Files don't exist")
