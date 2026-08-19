"""multisens-reference-inference-emotion - a sibling reference bridge
plugin to multisens-reference-inference (the YOLOv8n vehicle-detection
one), demonstrating the exact same PredictionConnector architecture
wired to a completely different model and sensor: face detection + FER+
emotion classification against a live webcam instead of vehicle
detection against a recorded road replay.

Not a driver-monitoring system, not an NCAP/DMS compliance claim, not a
clinical or psychological assessment of emotion - see the package
README for the full framing discipline.
"""
