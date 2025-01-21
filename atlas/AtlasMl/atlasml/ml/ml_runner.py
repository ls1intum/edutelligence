import logging

from atlasml.ml.model import ml_model_handler

def ml_runner():
    print("Running ML model")
    print(ml_model_handler())
    

if __name__ == "__main__":
    ml_runner()