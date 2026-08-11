import unittest
from unittest.mock import MagicMock, patch
from jarvis.tools.vision import (
    see_user,
    inspect_visual_ui,
    check_desk_presence,
    detect_gestures,
    detect_hand_landmarks,
    detect_faces,
    track_desk_arrival_departure,
    MediaPipeVisionEngine
)

class TestVision(unittest.TestCase):
    @patch('subprocess.run')
    @patch('cv2.VideoCapture')
    def test_basic_vision(self, mock_cap, mock_subproc):
        mock_instance = MagicMock()
        mock_instance.isOpened.return_value = False
        mock_cap.return_value = mock_instance

        mock_subproc_res = MagicMock()
        mock_subproc_res.returncode = 1
        mock_subproc_res.stderr = b"Mock screen capture"
        mock_subproc.return_value = mock_subproc_res

        res = see_user()
        self.assertIn("Webcam Snapshot Perception", res)

        ui_res = inspect_visual_ui()
        self.assertIn("Visual UI Inspection", ui_res)

        desk_res = check_desk_presence()
        self.assertIn("Desk Presence", desk_res)

    def test_gesture_recognition(self):
        gest_res = detect_gestures()
        self.assertIn("MediaPipe Hand Gesture Recognized", gest_res)
        self.assertIn("thumbs_up", gest_res)

        landmarks = MediaPipeVisionEngine.generate_synthetic_landmarks("open_palm")
        classified = MediaPipeVisionEngine.classify_gesture_from_landmarks(landmarks)
        self.assertIn(classified, ["open_palm", "thumbs_up", "peace", "pointing", "wave", "none"])

    def test_hand_landmarks_21_points(self):
        lm_res = detect_hand_landmarks()
        self.assertIn("MediaPipe Hand Landmarks Extracted", lm_res)
        self.assertIn("21 Points", lm_res)

    def test_face_detection(self):
        face_res = detect_faces()
        self.assertIn("Face Detection Result", face_res)
        self.assertIn("Primary Face Bounding Box", face_res)

    def test_desk_arrival_departure_tracking(self):
        tracker_res = track_desk_arrival_departure()
        self.assertIn("Desk Presence Event Tracker", tracker_res)
        self.assertIn("OCCUPIED", tracker_res)

if __name__ == "__main__":
    unittest.main()
