import threading
import time
from collections import defaultdict, deque
from fer import FER
import cv2
import numpy as np
import requests
import appdirs
import os
import json


class EmotionMonitorService:
    def __init__(self, display_window=False, api_url="http://localhost:8000/emotions", api_key=None):
        if not api_key:
            raise ValueError("API key is required to proceed.")
        
        self.detector = FER(mtcnn=True)
        self.cap = cv2.VideoCapture(0)
        self.running = False
        self.emotion_data = deque()  # Stores (timestamp, emotions)
        self.lock = threading.Lock()
        self.display_window = display_window
        self.last_bbox = None
        self.time_window = 10  # Time window in seconds for averaging
        self.stopped = False
        self.api_url = api_url
        self.api_key = api_key

    def start(self):
        if not self.cap.isOpened():
            print("Error: Could not open webcam.")
            return

        self.running = True
        self.thread = threading.Thread(target=self._monitor_emotions)
        self.thread.start()

    def stop(self):
        self.running = False
        if threading.current_thread() != self.thread:
            self.thread.join()
        self.cap.release()
        cv2.destroyAllWindows()
        self.stopped = True

    def _send_emotion_data(self, timestamp, emotions):
        try:
            headers = {"x-api-key": self.api_key}
            response = requests.post(self.api_url, json={"timestamp": timestamp, "emotions": emotions}, headers=headers)
            if response.status_code != 200:
                print(f"Failed to send data: {response.status_code}, {response.text}")
        except Exception as e:
            print(f"Error sending data to API: {e}")

    def _monitor_emotions(self):
        tracker = cv2.TrackerKCF.create()
        initialized_tracker = False

        while self.running:
            ret, frame = self.cap.read()
            if not ret:
                print("Error: Could not read frame.")
                break

            if not initialized_tracker:
                # Detect the largest face to initialize the tracker
                result = self.detector.detect_emotions(frame)
                if result:
                    largest_face = max(
                        result, key=lambda face: face["box"][2] * face["box"][3]
                    )
                    (x, y, w, h) = largest_face["box"]
                    tracker.init(frame, (x, y, w, h))
                    initialized_tracker = True
            else:
                # Update the tracker
                success, bbox = tracker.update(frame)
                if success:
                    x, y, w, h = map(int, bbox)
                    self.last_bbox = (x, y, w, h)
                    face_frame = frame[y : y + h, x : x + w]

                    # Analyze emotions for the tracked face
                    result = self.detector.detect_emotions(face_frame)
                    if result:
                        emotions = result[0]["emotions"]
                        timestamp = time.time()
                        with self.lock:
                            self.emotion_data.append((timestamp, emotions))
                        # Send the data to the API
                        self._send_emotion_data(timestamp, emotions)

            # Remove old data outside the time window
            current_time = time.time()
            with self.lock:
                while self.emotion_data and self.emotion_data[0][0] < current_time - self.time_window:
                    self.emotion_data.popleft()

            if self.display_window:
                # Display the frame with the tracked face
                if self.last_bbox is not None:
                    (x, y, w, h) = self.last_bbox
                    cv2.rectangle(frame, (x, y), (x + w, y + h), (255, 0, 0), 2)

                # Display emotion averages on the frame
                averages = self.get_averages()
                y_offset = 20
                for emotion, avg in averages.items():
                    text = f"{emotion}: {avg:.2f}"
                    cv2.putText(
                        frame,
                        text,
                        (10, y_offset),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.6,
                        (0, 255, 0),
                        2,
                    )
                    y_offset += 20

                cv2.imshow("Emotion Monitor", frame)

                # if esc key is pressed OR window is closed, break the loop
                if cv2.waitKey(1) & 0xFF == 27:
                    break
                elif cv2.getWindowProperty("Emotion Monitor", cv2.WND_PROP_VISIBLE) < 1:
                    break

            time.sleep(0.1)  # Reduce CPU usage

    def get_averages(self):
        with self.lock:
            emotion_totals = defaultdict(float)
            emotion_counts = defaultdict(int)

            for _, emotions in self.emotion_data:
                for emotion, score in emotions.items():
                    emotion_totals[emotion] += score
                    emotion_counts[emotion] += 1

            return {
                emotion: emotion_totals[emotion] / emotion_counts[emotion]
                if emotion_counts[emotion] > 0
                else 0
                for emotion in emotion_totals
            }


if __name__ == "__main__":
    import argparse
    import tkinter as tk
    from tkinter import simpledialog

    parser = argparse.ArgumentParser(description="Emotion Monitor Service")
    parser.add_argument(
        "--display", action="store_true", help="Display the emotion monitoring window"
    )

    args = parser.parse_args()

    # Prompt the user for an API key
    root = tk.Tk()
    root.withdraw()  # Hide the main tkinter window
    api_key = simpledialog.askstring("API Key Required", "Please enter your API key:")
    if not api_key:
        raise ValueError("API key is required to proceed.")

    service = EmotionMonitorService(display_window=args.display, api_url="http://localhost:8000/emotions", api_key=api_key)
    try:
        service.start()
        print("Emotion monitoring service started. Press Ctrl+C or close window to stop.")
        # Wait for the monitoring thread to finish
        if service.thread:
            service.thread.join()
    except KeyboardInterrupt:
        print("\nStopping service due to KeyboardInterrupt...")
        if service.running:
            service.stop()
        if service.thread and service.thread.is_alive():
            service.thread.join()
    finally:
        if service.running:
            service.stop()

    print("Finished cleaning up; exiting.")
