"""emotion-worker - a sibling reference inference worker to yolo_worker
(examples/plugins/reference-inference), demonstrating that MultiSens's
background-inference architecture is genuinely model-agnostic: swap the
sensor (a live webcam instead of a recorded road replay) and the model
(face detection + FER+ emotion classification instead of YOLOv8n vehicle
detection), and every downstream piece - PredictionConnector, session
lifecycle, evaluator, Evidence Playback - needs zero changes.

Not a driver-monitoring system, not an NCAP/DMS compliance claim, not a
clinical or psychological assessment of emotion - a pretrained model's
classification, demonstrated for architecture purposes only. See the
package README for the full framing discipline.
"""
