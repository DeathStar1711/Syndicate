import os
import pandas as pd
from src.ml.trainer import MLTrainer

trainer = MLTrainer()
trainer.prepare_features(["TCS.NS"])
