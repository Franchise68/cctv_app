import cv2


class SimpleMotionDetector:
    def __init__(self):
        self.subtractor = cv2.createBackgroundSubtractorMOG2(history=300, varThreshold=25, detectShadows=True)

    def detect(self, frame):
        mask = self.subtractor.apply(frame)
        thresh = cv2.threshold(mask, 200, 255, cv2.THRESH_BINARY)[1]
        cnts, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        motion = any(cv2.contourArea(c) > 800 for c in cnts)
        return motion, thresh
