import threading
import time
from collections import defaultdict, deque
import numpy as np
import requests
import appdirs
import os
import json
import subprocess
import sys
import traceback
# Import the GUI function
from get_api_key_gui import get_api_key

# --- Configuration Handling ---
APP_NAME = "chorus client"
APP_AUTHOR = "Alec Jensen, Ryan Farnell, Bennett Rodriguez"

def get_config_path():
    """Gets the path to the configuration file."""
    config_dir = appdirs.user_config_dir(APP_NAME, APP_AUTHOR)
    os.makedirs(config_dir, exist_ok=True)
    return os.path.join(config_dir, "config.json")

def load_config():
    """Loads configuration from the JSON file."""
    config_path = get_config_path()
    if os.path.exists(config_path):
        try:
            with open(config_path, 'r') as f:
                config = json.load(f)
                return config
        except (json.JSONDecodeError, IOError) as e:
            print(f"Warning: Could not load config file at {config_path}: {e}", file=sys.stderr)
    return {}

def save_config(config):
    """Saves configuration to the JSON file."""
    config_path = get_config_path()
    try:
        with open(config_path, 'w') as f:
            json.dump(config, f, indent=4)
        print(f"Configuration saved to {config_path}")
    except IOError as e:
        print(f"Warning: Could not save config file at {config_path}: {e}", file=sys.stderr)

class EmotionMonitorService:
    def __init__(self, display_window=False, api_url="http://localhost:8000/emotions", api_key=None):
        if not api_key:
            raise ValueError("API key is required to proceed.")

        # Import FER and cv2 here
        from fer import FER
        import cv2

        self.detector = FER()
        self.cap = cv2.VideoCapture(0)
        self.running = False
        self.emotion_data = deque()
        self.lock = threading.Lock()
        self.display_window = display_window
        self.last_bbox = None
        self.time_window = 60 # seconds
        self.stopped = False
        self.api_url = api_url
        self.api_key = api_key
        self.thread = None

    def start(self):
        if not self.cap.isOpened():
            print("Error: Could not open webcam.")
            return

        self.running = True
        self.thread = threading.Thread(target=self._monitor_emotions)
        self.thread.daemon = True
        self.thread.start()

    def stop(self):
        # Import cv2 here for destroyAllWindows/waitKey
        import cv2
        print("Stop method called.")
        self.running = False
        if self.thread and self.thread.is_alive() and threading.current_thread() != self.thread:
            print("Waiting for monitoring thread to join...")
            self.thread.join(timeout=2.0)
            if self.thread.is_alive():
                print("Warning: Monitoring thread did not join within timeout.")
        else:
            print("Monitoring thread already stopped or doesn't exist.")

        if self.cap and self.cap.isOpened():
            print("Releasing webcam capture...")
            self.cap.release()
        print("Destroying OpenCV windows...")
        cv2.destroyAllWindows()
        self.stopped = True
        print("Stop method finished.")

    def _send_emotion_data(self, timestamp, emotions):
        try:
            headers = {"x-api-key": self.api_key}
            response = requests.post(self.api_url, json={"timestamp": timestamp, "emotions": emotions}, headers=headers, timeout=5)
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            print(f"Error sending data to API: {e}")
        except Exception as e:
            print(f"Unexpected error sending data: {e}")

    def _monitor_emotions(self):
        # Import cv2 here for tracker and display operations
        import cv2
        tracker = None
        initialized_tracker = False
        frame_skip_counter = 0
        frame_skip_threshold = 5

        while self.running:
            try:
                ret, frame = self.cap.read()
                if not ret or frame is None:
                    print("Error: Could not read frame or empty frame received.")
                    time.sleep(0.5)
                    continue

                process_frame = frame.copy()

                if not initialized_tracker or (tracker is None and frame_skip_counter == 0):
                    result = self.detector.detect_emotions(process_frame)
                    if result:
                        largest_face = max(result, key=lambda face: face["box"][2] * face["box"][3])
                        (x, y, w, h) = largest_face["box"]
                        if w > 0 and h > 0:
                            try:
                                tracker = cv2.TrackerKCF.create()
                                tracker.init(process_frame, (x, y, w, h))
                                initialized_tracker = True
                                self.last_bbox = (x, y, w, h)
                                print("Tracker initialized.")
                            except cv2.error as e:
                                print(f"OpenCV error initializing tracker: {e}")
                                tracker = None
                                initialized_tracker = False
                        else:
                            print("Warning: Detected face with zero dimension.")
                    else:
                        self.last_bbox = None

                elif tracker:
                    success, bbox = tracker.update(process_frame)
                    if success:
                        x, y, w, h = map(int, bbox)
                        if w > 0 and h > 0 and x >= 0 and y >= 0 and x + w <= process_frame.shape[1] and y + h <= process_frame.shape[0]:
                            self.last_bbox = (x, y, w, h)
                            face_frame = process_frame[y : y + h, x : x + w]

                            if face_frame is not None and face_frame.size > 0:
                                emotion_result = self.detector.detect_emotions(face_frame)
                                if emotion_result:
                                    emotions = emotion_result[0]["emotions"]
                                    timestamp = time.time()
                                    with self.lock:
                                        self.emotion_data.append((timestamp, emotions))
                                    self._send_emotion_data(timestamp, emotions)
                            frame_skip_counter = 0
                        else:
                            print("Tracker bbox invalid or out of bounds.")
                            success = False

                    if not success:
                        print("Tracker update failed.")
                        self.last_bbox = None
                        tracker = None
                        initialized_tracker = False
                        frame_skip_counter = (frame_skip_counter + 1) % frame_skip_threshold
                        if frame_skip_counter == 0:
                            print("Attempting face re-detection.")

                current_time = time.time()
                with self.lock:
                    while self.emotion_data and self.emotion_data[0][0] < current_time - self.time_window:
                        self.emotion_data.popleft()

                if self.display_window:
                    display_frame = frame
                    if self.last_bbox:
                        (x, y, w, h) = self.last_bbox
                        cv2.rectangle(display_frame, (x, y), (x + w, y + h), (255, 0, 0), 2)

                    averages = self.get_averages()
                    y_offset = 20
                    for emotion, avg in averages.items():
                        text = f"{emotion}: {avg:.2f}"
                        cv2.putText(display_frame, text, (10, y_offset), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
                        y_offset += 20

                    cv2.imshow("Emotion Monitor", display_frame)

                    key = cv2.waitKey(1) & 0xFF
                    if key == 27:
                        print("ESC key pressed, stopping.")
                        self.running = False
                        break
                    try:
                        if cv2.getWindowProperty("Emotion Monitor", cv2.WND_PROP_VISIBLE) < 1:
                            print("Window closed, stopping.")
                            self.running = False
                            break
                    except cv2.error:
                        print("Window property check failed (likely closed), stopping.")
                        self.running = False
                        break

                time.sleep(0.01)

            except cv2.error as e:
                print(f"OpenCV Error in monitoring loop: {e}")
                time.sleep(0.5)
            except Exception as e:
                print(f"Unexpected error in monitoring loop: {e}")
                traceback.print_exc()
                self.running = False
                break

        print("Exiting monitoring loop.")

    def get_averages(self):
        with self.lock:
            if not self.emotion_data:
                return {}

            try:
                all_emotion_keys = list(self.emotion_data[0][1].keys())
            except (IndexError, AttributeError):
                return {}

            emotion_totals = {key: 0.0 for key in all_emotion_keys}
            emotion_counts = {key: 0 for key in all_emotion_keys}

            num_samples = len(self.emotion_data)
            if num_samples == 0:
                return emotion_totals

            for _, emotions in self.emotion_data:
                for emotion, score in emotions.items():
                    if emotion in emotion_totals:
                        emotion_totals[emotion] += score
                        emotion_counts[emotion] += 1

            averages = {
                emotion: emotion_totals[emotion] / num_samples
                for emotion in emotion_totals
            }
            return averages


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Emotion Monitor Service")
    parser.add_argument(
        "--display", action="store_true", help="Display the emotion monitoring window"
    )
    parser.add_argument(
        "--api-url", default=os.environ.get("EMOTION_API_URL", "http://localhost:8000/emotions"), help="URL for the emotion API endpoint (or use EMOTION_API_URL env var)"
    )
    parser.add_argument(
        "--api-key", help="API key for the emotion API endpoint (overrides saved config and env var)"
    )
    parser.add_argument(
        "--clear-config", action="store_true", help="Clear saved configuration (e.g., API key) and exit."
    )

    args = parser.parse_args()

    config_path = get_config_path()

    if args.clear_config:
        if os.path.exists(config_path):
            try:
                os.remove(config_path)
                print(f"Configuration file {config_path} removed.")
            except OSError as e:
                print(f"Error removing configuration file: {e}", file=sys.stderr)
        else:
            print("No configuration file found to remove.")
        sys.exit(0)

    api_key = None
    config = load_config()

    if args.api_key:
        print("Using API key from command line argument.")
        api_key = args.api_key
    elif os.environ.get("EMOTION_API_KEY"):
        print("Using API key from EMOTION_API_KEY environment variable.")
        api_key = os.environ.get("EMOTION_API_KEY")
    elif "api_key" in config and config["api_key"]:
        print(f"Using API key from config file: {config_path}")
        api_key = config["api_key"]
    else:
        print("API key not found in args, environment, or config file.")
        print("Attempting to get API key via GUI...")
        try:
            # Use the GUI function instead of input()
            api_key = get_api_key()
        except Exception as e:
            print(f"\nCould not launch API key GUI: {e}", file=sys.stderr)
            print("Please enter your API key via the console as a fallback.")
            try:
                api_key = input("Please enter your API key: ")
            except EOFError:
                print("\nInput stream closed. Exiting.", file=sys.stderr)
                sys.exit(1)


        if not api_key:
            print("API key is required but was not provided (GUI closed or empty). Exiting.", file=sys.stderr)
            sys.exit(1)
        else:
            # Save the key obtained from the GUI
            config["api_key"] = api_key
            save_config(config)

    service = None
    try:
        if not api_key:
            print("Could not obtain API key. Exiting.", file=sys.stderr)
            sys.exit(1)

        if (args.api_key or os.environ.get("EMOTION_API_KEY")) and config.get("api_key") != api_key:
            config["api_key"] = api_key
            save_config(config)

        print(f"Initializing service (Display: {args.display}, API URL: {args.api_url})")
        service = EmotionMonitorService(display_window=args.display, api_url=args.api_url, api_key=api_key)
        service.start()
        print("Emotion monitoring service started. Press ESC in window or Ctrl+C in console to stop.")

        while service.thread and service.thread.is_alive():
            service.thread.join(timeout=0.5)

    except ValueError as e:
        print(f"Configuration Error: {e}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nCtrl+C detected. Initiating shutdown...")
    except Exception as e:
        print(f"\nAn unexpected error occurred in the main execution: {e}", file=sys.stderr)
        traceback.print_exc()
    finally:
        print("Main block finished or interrupted. Cleaning up...")
        if service:
            service.stop()
        else:
            print("Service was not initialized, no cleanup needed.")

    print("Finished cleaning up; exiting.")
    sys.exit(0)
