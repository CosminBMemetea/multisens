"""multisens-reference-inference-mediapipe - a third sibling reference
bridge plugin to multisens-reference-inference (YOLOv8n vehicle
detection) and multisens-reference-inference-emotion (FER+ facial
emotion), demonstrating the exact same PredictionConnector architecture
wired to a third, independently-developed model family: MediaPipe face
detection.

Detection only, not classification - see the package README for the
full framing discipline and the real mediapipe==1.0.1 environment bug
this package's worker requirements.txt pins around.
"""
