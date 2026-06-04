import cv2
import mediapipe as mp
import numpy as np
import time
import os
import csv
import pygame
import threading
import requests
import json
from datetime import datetime
from collections import deque

# тг бот
TELEGRAM_BOT_TOKEN = "8930435350:AAFwLipzUGsTMrvMokXELaVajRSjHNI_mU4"
CONFIG_FILE = "telegram_users.json"

# уведы
WARNING_LIMIT = 3
WARNING_TIME_WINDOW = 300
TELEGRAM_COOLDOWN = 600

# настройка мониторинга
EAR_CLOSED_THRESHOLD = 0.10
EYE_CLOSED_SECONDS = 2.5

GAZE_LEFT_THRESHOLD = -0.15
GAZE_RIGHT_THRESHOLD = 0.15
GAZE_AWAY_SECONDS = 3.0

MOUTH_OPEN_THRESHOLD = 0.4
MOUTH_OPEN_SECONDS = 1.5

HEAD_TURN_SECONDS = 3.0
HEAD_TURN_THRESHOLD = 0.25

LOG_DIR = 'logs'
LOG_FILE = os.path.join(LOG_DIR, 'events.csv')
WARNING_LOG_FILE = os.path.join(LOG_DIR, 'warnings.csv')

SOUND_EYES_CLOSED = "Закрыл_глаза.mp3"
SOUND_GAZE_AWAY = "Внимание_на_дорогу.mp3"
SOUND_YAWNING = "Перерыв.mp3"
SOUND_HEAD_TURN = "Поворот_головы.mp3"

LEFT_EYE_IDX = [33, 160, 158, 133, 153, 144]
RIGHT_EYE_IDX = [362, 385, 387, 263, 373, 380]
LEFT_IRIS_IDX = [468, 469, 470, 471]
RIGHT_IRIS_IDX = [473, 474, 475, 476]
MOUTH_TOP = 13
MOUTH_BOTTOM = 14

pygame.mixer.init()

# ========== УПРАВЛЕНИЕ ПОЛЬЗОВАТЕЛЯМИ ==========
class UserManager:
    def __init__(self, config_file=CONFIG_FILE):
        self.config_file = config_file
        self.users = {}
        self.load_users()
        
    def load_users(self):
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.users = {str(k): v for k, v in data.get('users', {}).items()}
                    print(f"\n[USERS] Загружено {len(self.users)} пользователей")
            except Exception as e:
                print(f"[USERS] Ошибка загрузки: {e}")
                self.users = {}
        else:
            print("[USERS] Нет сохранённых пользователей")
    
    def save_users(self):
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump({
                    'users': self.users,
                    'last_updated': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                }, f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"[USERS] Ошибка сохранения: {e}")
            return False
    
    def add_user(self, chat_id, first_name="", username="", last_name=""):
        chat_id_str = str(chat_id)
        if chat_id_str in self.users:
            return False
        
        name = f"{first_name} {last_name}".strip()
        if not name:
            name = username if username else f"User_{chat_id_str[-4:]}"
        
        self.users[chat_id_str] = {
            'chat_id': chat_id_str,
            'name': name,
            'username': username,
            'first_name': first_name,
            'last_name': last_name,
            'added_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            'last_active': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        self.save_users()
        print(f"[USERS] Новый пользователь: {name}")
        return True
    
    def get_all_users(self):
        return list(self.users.keys())
    
    def get_users_count(self):
        return len(self.users)

# ========== TELEGRAM НОТИФИКАТОР ==========
class TelegramNotifier:
    def __init__(self, bot_token):
        self.bot_token = bot_token
        self.base_url = f"https://api.telegram.org/bot{bot_token}"
        self.user_manager = UserManager()
        self.last_notification_time = 0
        self.last_update_id = None
        self.bot_username = None
        
        self._get_bot_username()
        self.start_listener()
        
        if self.user_manager.get_users_count() > 0:
            print(f"[TELEGRAM] Бот готов. {self.user_manager.get_users_count()} подписчиков\n")
    
    def _get_bot_username(self):
        try:
            response = requests.get(f"{self.base_url}/getMe", timeout=5)
            if response.status_code == 200:
                data = response.json()
                if data.get('ok'):
                    self.bot_username = data['result'].get('username', 'SafeCarAi_bot')
                    print(f"[TELEGRAM] Бот: @{self.bot_username}")
                    return
        except:
            pass
        self.bot_username = "SafeCarAi_bot"
    
    def start_listener(self):
        thread = threading.Thread(target=self._listen_for_users, daemon=True)
        thread.start()
    
    def _listen_for_users(self):
        while True:
            try:
                url = f"{self.base_url}/getUpdates"
                params = {'timeout': 10, 'allowed_updates': ['message']}
                if self.last_update_id:
                    params['offset'] = self.last_update_id + 1
                
                response = requests.get(url, params=params, timeout=15)
                
                if response.status_code == 200:
                    data = response.json()
                    if data.get('ok') and data['result']:
                        for update in data['result']:
                            if 'message' in update:
                                message = update['message']
                                chat = message.get('chat', {})
                                chat_id = chat.get('id')
                                user = message.get('from', {})
                                
                                if chat_id:
                                    first_name = user.get('first_name', '')
                                    last_name = user.get('last_name', '')
                                    username = user.get('username', '')
                                    
                                    if self.user_manager.add_user(chat_id, first_name, username, last_name):
                                        self._send_welcome_message(chat_id)
                            
                            if 'update_id' in update:
                                self.last_update_id = update['update_id']
            except:
                pass
            time.sleep(2)
    
    def _send_welcome_message(self, chat_id):
        message = (
            "<b>Добро пожаловать в SafeDrive AI Monitor!</b>\n\n"
            "Вы подписались на уведомления о состоянии водителя.\n\n"
            "<b>Что отслеживается:</b>\n"
            "• Закрытие глаз более 2.5 секунд → уведомление при 3+ раз за 5 мин\n"
            "• Отведение взгляда более 3 сек\n"
            "• Поворот головы более 3 сек\n"
            "• Сильная зевота 1.5 сек\n\n"
            "Берегите себя!"
        )
        self._send_message_async(chat_id, message)
    
    def _send_message_async(self, chat_id, message):
        def send():
            try:
                url = f"{self.base_url}/sendMessage"
                payload = {
                    "chat_id": chat_id,
                    "text": message,
                    "parse_mode": "HTML"
                }
                requests.post(url, json=payload, timeout=10)
            except:
                pass
        threading.Thread(target=send, daemon=True).start()
    
    def send_to_all(self, message):
        users = self.user_manager.get_all_users()
        if not users:
            return False
        
        current_time = time.time()
        if current_time - self.last_notification_time < TELEGRAM_COOLDOWN:
            remaining = int(TELEGRAM_COOLDOWN - (current_time - self.last_notification_time))
            print(f"[TELEGRAM] Кулдаун: {remaining} сек")
            return False
        
        print(f"[TELEGRAM] 📤 Отправка {len(users)} пользователям...")
        for chat_id in users:
            self._send_message_async(chat_id, message)
            time.sleep(0.1)
        
        self.last_notification_time = current_time
        print(f"[TELEGRAM] ✅ Уведомление отправлено")
        return True
    
    def send_driver_alert(self, warning_count, warnings_list):
        current_time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        eyes_closed_count = sum(1 for w in warnings_list if w.get('type') == 'eyes_closed')
        
        message = f"🚨 <b>ВНИМАНИЕ! ВОДИТЕЛЬ ЗАСЫПАЕТ!</b> 🚨\n\n"
        message += f"<b>Водитель</b> закрыл глаза <b>{eyes_closed_count}</b> раз(а) за последние {WARNING_TIME_WINDOW//60} минут!\n\n"
        message += f"<b>⚠️ Возможная усталость или засыпание за рулём!</b>\n\n"
        message += f"<b>Время:</b> {current_time_str}\n\n"
        message += f"<i>Пожалуйста, проверьте состояние водителя!</i>"
        
        return self.send_to_all(message)
    
    def get_status(self):
        count = self.user_manager.get_users_count()
        if count > 0:
            return f"OK ({count} subs)"
        else:
            return f"Waiting (@{self.bot_username})"

# ========== ТРЕКЕР ПРЕДУПРЕЖДЕНИЙ ==========
class WarningTracker:
    def __init__(self, limit=3, time_window=300):
        self.limit = limit
        self.time_window = time_window
        self.warnings = deque()
        self.notifier = None
        self.alert_sent_for_current_batch = False
        
    def set_notifier(self, notifier):
        self.notifier = notifier
        
    def add_warning(self, warning_type):
        if warning_type != 'eyes_closed':
            return len(self.warnings)
        
        current_time = time.time()
        
        if not self.warnings or current_time - self.warnings[0][0] > self.time_window:
            self.alert_sent_for_current_batch = False
        
        self.warnings.append((current_time, warning_type))
        
        while self.warnings and current_time - self.warnings[0][0] > self.time_window:
            self.warnings.popleft()
        
        if len(self.warnings) >= self.limit and not self.alert_sent_for_current_batch:
            if self.notifier:
                warnings_data = [{'type': w[1]} for w in self.warnings]
                self.notifier.send_driver_alert(len(self.warnings), warnings_data)
                self.alert_sent_for_current_batch = True
                print(f"[ALERT] ⚠️ {len(self.warnings)} закрытий глаз! Уведомление отправлено")
                
        return len(self.warnings)
    
    def get_stats(self):
        return {
            'count': len(self.warnings),
            'limit': self.limit,
            'window_minutes': self.time_window // 60
        }

# ========== MP3 ПЛЕЕР ==========
class MP3Player:
    def __init__(self, cooldown=4.0):
        self.cooldown = cooldown
        self.last_warning_time = {}
        self.warning_tracker = None
        
    def set_warning_tracker(self, tracker):
        self.warning_tracker = tracker
        
    def play_sound(self, sound_file, warning_type=""):
        now = time.time()
        
        if warning_type in self.last_warning_time:
            if now - self.last_warning_time[warning_type] < self.cooldown:
                return
        
        if not os.path.exists(sound_file):
            print(f'[SOUND ERROR] {sound_file} не найден')
            return
        
        if self.warning_tracker and warning_type:
            total = self.warning_tracker.add_warning(warning_type)
            stats = self.warning_tracker.get_stats()
        
        def play():
            try:
                pygame.mixer.music.load(sound_file)
                pygame.mixer.music.play()
                while pygame.mixer.music.get_busy():
                    time.sleep(0.1)
            except Exception as e:
                print(f'Ошибка воспроизведения: {e}')
        
        threading.Thread(target=play, daemon=True).start()
        
        if warning_type:
            self.last_warning_time[warning_type] = now

# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========
def ensure_logfile():
    if not os.path.exists(LOG_DIR):
        os.makedirs(LOG_DIR, exist_ok=True)
    if not os.path.exists(LOG_FILE):
        with open(LOG_FILE, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['timestamp', 'ear', 'perclos', 'gaze_left', 'gaze_right', 'mouth_open', 'head_turned'])

def log_event(ear, perclos, gaze_left, gaze_right, mouth_open, head_turned):
    ensure_logfile()
    with open(LOG_FILE, 'a', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow([time.time(), f'{ear:.4f}', f'{perclos:.4f}', 
                        int(gaze_left), int(gaze_right), f'{mouth_open:.4f}', int(head_turned)])

def eye_aspect_ratio(eye_points):
    if len(eye_points) < 6:
        return 0.0
    points = np.array(eye_points)
    vert1 = np.linalg.norm(points[1] - points[5])
    vert2 = np.linalg.norm(points[2] - points[4])
    horiz = np.linalg.norm(points[0] - points[3])
    if horiz == 0:
        return 0.0
    return (vert1 + vert2) / (2.0 * horiz)

def get_landmark_point(landmarks, index):
    if index < len(landmarks):
        return landmarks[index]
    return None

def analyze_gaze_direction(landmarks):
    try:
        left_iris_center = np.mean([landmarks[i] for i in LEFT_IRIS_IDX if i < len(landmarks)], axis=0)
        right_iris_center = np.mean([landmarks[i] for i in RIGHT_IRIS_IDX if i < len(landmarks)], axis=0)
        
        left_eye_inner = landmarks[LEFT_EYE_IDX[0]]
        left_eye_outer = landmarks[LEFT_EYE_IDX[3]]
        right_eye_inner = landmarks[RIGHT_EYE_IDX[0]]
        right_eye_outer = landmarks[RIGHT_EYE_IDX[3]]
        
        left_eye_width = left_eye_outer[0] - left_eye_inner[0]
        left_gaze_ratio = (left_iris_center[0] - left_eye_inner[0]) / left_eye_width if left_eye_width != 0 else 0.5
            
        right_eye_width = right_eye_outer[0] - right_eye_inner[0]
        right_gaze_ratio = (right_iris_center[0] - right_eye_inner[0]) / right_eye_width if right_eye_width != 0 else 0.5
        
        avg_gaze_normalized = ((left_gaze_ratio - 0.5) + (right_gaze_ratio - 0.5)) / 2
        
        gaze_left = avg_gaze_normalized < GAZE_LEFT_THRESHOLD
        gaze_right = avg_gaze_normalized > GAZE_RIGHT_THRESHOLD
        gaze_direction = "CENTER"
        if gaze_left:
            gaze_direction = "LEFT"
        elif gaze_right:
            gaze_direction = "RIGHT"
        
        return (gaze_left or gaze_right), gaze_left, gaze_right, avg_gaze_normalized, gaze_direction
    except:
        return False, False, False, 0, "CENTER"

def analyze_head_direction(landmarks, frame_width):
    try:
        left_side = get_landmark_point(landmarks, 234)
        right_side = get_landmark_point(landmarks, 454)
        nose = get_landmark_point(landmarks, 1)
        
        if not all([left_side, right_side, nose]):
            return False, False, 0.0, "CENTER"
        
        face_center = (left_side[0] + right_side[0]) / 2
        face_width = abs(right_side[0] - left_side[0])
        
        if face_width == 0:
            return False, False, 0.0, "CENTER"
            
        turn_ratio = (nose[0] - face_center) / face_width
        head_direction = "CENTER"
        if turn_ratio < -HEAD_TURN_THRESHOLD:
            head_direction = "LEFT"
        elif turn_ratio > HEAD_TURN_THRESHOLD:
            head_direction = "RIGHT"
        
        return turn_ratio < -HEAD_TURN_THRESHOLD, turn_ratio > HEAD_TURN_THRESHOLD, turn_ratio, head_direction
    except:
        return False, False, 0.0, "CENTER"

def analyze_mouth_open(landmarks):
    try:
        top = get_landmark_point(landmarks, MOUTH_TOP)
        bottom = get_landmark_point(landmarks, MOUTH_BOTTOM)
        left_eye_ref = get_landmark_point(landmarks, 33)
        right_eye_ref = get_landmark_point(landmarks, 263)
        
        if top and bottom and left_eye_ref and right_eye_ref:
            mouth_height = np.linalg.norm(np.array(bottom) - np.array(top))
            eye_distance = np.linalg.norm(np.array(right_eye_ref) - np.array(left_eye_ref))
            if eye_distance > 0:
                return mouth_height / eye_distance
    except:
        pass
    return 0.0

# ========== ОСНОВНАЯ ФУНКЦИЯ ==========
def main():
    print("\n!!!! SafeDrive AI Driver Monitor !!!!\n")
    
    notifier = TelegramNotifier(TELEGRAM_BOT_TOKEN)
    
    warning_tracker = WarningTracker(limit=WARNING_LIMIT, time_window=WARNING_TIME_WINDOW)
    warning_tracker.set_notifier(notifier)
    
    mp3_player = MP3Player(cooldown=4.0)
    mp3_player.set_warning_tracker(warning_tracker)
    
    mp_face_mesh = mp.solutions.face_mesh
    face_mesh = mp_face_mesh.FaceMesh(
        static_image_mode=False,
        max_num_faces=1,
        refine_landmarks=True,
        min_detection_confidence=0.5,
        min_tracking_confidence=0.5
    )
    
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print('ERROR: cannot open camera')
        return
    
    # Таймеры для отслеживания длительности состояний
    eye_closed_start = None
    gaze_left_start = None
    gaze_right_start = None
    mouth_open_start = None
    head_turn_start = None
    head_turn_direction = None
    
    ear_buffer = []
    perclos_window = 5.0
    
    print(f"\nЛимит закрытий глаз: {WARNING_LIMIT} за {WARNING_TIME_WINDOW//60} минут")
    print(f"Подписчики: {notifier.user_manager.get_users_count()}\n")
    print("Подписка: напишите @" + (notifier.bot_username or "SafeCarAi_bot") + " в Telegram\n\n")
    
    while True:
        ret, frame = cap.read()
        if not ret:
            break
            
        h, w = frame.shape[:2]
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = face_mesh.process(rgb_frame)
        
        current_time = time.time()
        
        frame_h, frame_w = frame.shape[:2]
        
        ear = 0.0
        perclos = 0.0
        gaze_direction = "CENTER"
        gaze_away = False
        head_direction = "CENTER"
        mouth_ratio = 0.0
        face_detected = results.multi_face_landmarks is not None and len(results.multi_face_landmarks) > 0
        
        if face_detected:
            face_landmarks = results.multi_face_landmarks[0]
            landmarks = [(int(lm.x * w), int(lm.y * h)) for lm in face_landmarks.landmark]
            
            mp.solutions.drawing_utils.draw_landmarks(
                frame, face_landmarks, mp_face_mesh.FACEMESH_TESSELATION,
                landmark_drawing_spec=None,
                connection_drawing_spec=mp.solutions.drawing_styles.get_default_face_mesh_tesselation_style()
            )
            
            try:
                left_eye = [landmarks[i] for i in LEFT_EYE_IDX if i < len(landmarks)]
                right_eye = [landmarks[i] for i in RIGHT_EYE_IDX if i < len(landmarks)]
                if len(left_eye) >= 6 and len(right_eye) >= 6:
                    ear = (eye_aspect_ratio(left_eye) + eye_aspect_ratio(right_eye)) / 2.0
            except:
                ear = 0.0
            
            ear_buffer.append((current_time, ear))
            ear_buffer = [(t, e) for t, e in ear_buffer if current_time - t <= perclos_window]
            perclos = sum(1 for _, e in ear_buffer if e < EAR_CLOSED_THRESHOLD) / len(ear_buffer) if ear_buffer else 0.0
            
            # закрытие глаз
            eyes_closed = ear < EAR_CLOSED_THRESHOLD
            if eyes_closed:
                if eye_closed_start is None:
                    eye_closed_start = current_time
                elif current_time - eye_closed_start >= EYE_CLOSED_SECONDS:
                    mp3_player.play_sound(SOUND_EYES_CLOSED, "eyes_closed")
                    eye_closed_start = current_time
            else:
                eye_closed_start = None
            eyes_closed_duration = current_time - eye_closed_start if eye_closed_start else 0
            
            # анализ взгляда
            gaze_away, gaze_left, gaze_right, gaze_offset, gaze_direction = analyze_gaze_direction(landmarks)
            
            if gaze_left:
                if gaze_left_start is None:
                    gaze_left_start = current_time
                elif current_time - gaze_left_start >= GAZE_AWAY_SECONDS:
                    mp3_player.play_sound(SOUND_GAZE_AWAY, "gaze_left")
                    gaze_left_start = current_time
            else:
                gaze_left_start = None
            
            if gaze_right:
                if gaze_right_start is None:
                    gaze_right_start = current_time
                elif current_time - gaze_right_start >= GAZE_AWAY_SECONDS:
                    mp3_player.play_sound(SOUND_GAZE_AWAY, "gaze_right")
                    gaze_right_start = current_time
            else:
                gaze_right_start = None
            
            gaze_duration = 0
            if gaze_left_start:
                gaze_duration = current_time - gaze_left_start
            elif gaze_right_start:
                gaze_duration = current_time - gaze_right_start
            
            # анализ поворота головы
            head_left, head_right, head_ratio, head_direction = analyze_head_direction(landmarks, w)
            
            if head_left or head_right:
                current_dir = 'left' if head_left else 'right'
                if head_turn_start is None:
                    head_turn_start = current_time
                    head_turn_direction = current_dir
                elif head_turn_direction == current_dir and current_time - head_turn_start >= HEAD_TURN_SECONDS:
                    mp3_player.play_sound(SOUND_HEAD_TURN, f"head_turn_{current_dir}")
                    head_turn_start = current_time
            else:
                head_turn_start = None
            
            head_duration = current_time - head_turn_start if head_turn_start else 0
            
            # анализ зевка
            mouth_ratio = analyze_mouth_open(landmarks)
            mouth_open = mouth_ratio > MOUTH_OPEN_THRESHOLD
            
            if mouth_open:
                if mouth_open_start is None:
                    mouth_open_start = current_time
                elif current_time - mouth_open_start >= MOUTH_OPEN_SECONDS:
                    mp3_player.play_sound(SOUND_YAWNING, "yawning")
                    mouth_open_start = current_time
            else:
                mouth_open_start = None
            
            mouth_duration = current_time - mouth_open_start if mouth_open_start else 0
            
            if int(current_time) % 5 == 0 and int(current_time) > 0:
                log_event(ear, perclos, gaze_left, gaze_right, mouth_ratio, head_left or head_right)
        
        # инфа на экране
        stats = warning_tracker.get_stats()
        tg_status = notifier.get_status()
        

        # Фон для текста (полупрозрачный)
        overlay = frame.copy()
        cv2.rectangle(overlay, (5, 5), (420, 280), (0, 0, 0), -1)
        frame = cv2.addWeighted(overlay, 0.6, frame, 0.4, 0)
        
        y_offset = 25
        line_height = 28
        
        # Заголовок
        cv2.putText(frame, "SAFE DRIVE AI MONITOR", (10, y_offset), 
                   cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
        y_offset += line_height + 5
        
        # Статус лица
        if face_detected:
            cv2.putText(frame, "Face: DETECTED", (10, y_offset), 
                       cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 0), 1)
        else:
            cv2.putText(frame, "Face: NOT DETECTED", (10, y_offset), 
                       cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 255), 1)
        y_offset += line_height
        
        # Разделитель
        cv2.line(frame, (10, y_offset - 5), (410, y_offset - 5), (100, 100, 100), 1)
        
        eyes_color = (0, 0, 255) if eyes_closed and face_detected else (0, 255, 0)
        cv2.putText(frame, "EYES:", (10, y_offset), 
                   cv2.FONT_HERSHEY_SIMPLEX, 0.55, (200, 200, 200), 1)
        cv2.putText(frame, f"EAR: {ear:.3f} | PERCLOS: {perclos:.0%}", (120, y_offset), 
                   cv2.FONT_HERSHEY_SIMPLEX, 0.5, eyes_color, 1)
        y_offset += line_height - 5
        
        if eye_closed_start and face_detected:
            cv2.putText(frame, f"  ⚠ EYES CLOSED: {eyes_closed_duration:.1f}/{EYE_CLOSED_SECONDS}s", (15, y_offset), 
                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)
            y_offset += line_height - 5
        else:
            y_offset -= 5
        
        gaze_color = (0, 0, 255) if gaze_direction != "CENTER" and face_detected else (0, 255, 0)
        cv2.putText(frame, "GAZE:", (10, y_offset), 
                   cv2.FONT_HERSHEY_SIMPLEX, 0.55, (200, 200, 200), 1)
        cv2.putText(frame, f"{gaze_direction} | offset: {gaze_offset:.3f}", (120, y_offset), 
                   cv2.FONT_HERSHEY_SIMPLEX, 0.5, gaze_color, 1)
        y_offset += line_height - 5
        
        if gaze_duration > 0 and face_detected:
            cv2.putText(frame, f"  ⚠ GAZE AWAY: {gaze_duration:.1f}/{GAZE_AWAY_SECONDS}s", (15, y_offset), 
                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 165, 255), 1)
            y_offset += line_height - 5
        else:
            y_offset -= 5
        
        head_color = (0, 0, 255) if head_direction != "CENTER" and face_detected else (0, 255, 0)
        cv2.putText(frame, "HEAD:", (10, y_offset), 
                   cv2.FONT_HERSHEY_SIMPLEX, 0.55, (200, 200, 200), 1)
        cv2.putText(frame, f"{head_direction} | ratio: {head_ratio:.2f}", (120, y_offset), 
                   cv2.FONT_HERSHEY_SIMPLEX, 0.5, head_color, 1)
        y_offset += line_height - 5
        
        if head_duration > 0 and face_detected:
            cv2.putText(frame, f"  ⚠ HEAD TURN: {head_duration:.1f}/{HEAD_TURN_SECONDS}s", (15, y_offset), 
                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 165, 255), 1)
            y_offset += line_height - 5
        else:
            y_offset -= 5
        
        mouth_color = (0, 0, 255) if mouth_open and face_detected else (0, 255, 0)
        cv2.putText(frame, "MOUTH:", (10, y_offset), 
                   cv2.FONT_HERSHEY_SIMPLEX, 0.55, (200, 200, 200), 1)
        cv2.putText(frame, f"open ratio: {mouth_ratio:.3f}", (120, y_offset), 
                   cv2.FONT_HERSHEY_SIMPLEX, 0.5, mouth_color, 1)
        y_offset += line_height - 5
        
        if mouth_duration > 0 and face_detected:
            cv2.putText(frame, f"  ⚠ YAWNING: {mouth_duration:.1f}/{MOUTH_OPEN_SECONDS}s", (15, y_offset), 
                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 165, 255), 1)
            y_offset += line_height - 5
        else:
            y_offset -= 5
        
        cv2.line(frame, (10, y_offset - 3), (410, y_offset - 3), (100, 100, 100), 1)
        
        # Статистика предупреждений для Telegram
        warnings_color = (0, 0, 255) if stats['count'] >= stats['limit'] else (255, 255, 0)
        cv2.putText(frame, f"TELEGRAM WARNINGS: {stats['count']}/{stats['limit']} (last {stats['window_minutes']}min)", 
                   (10, y_offset + 5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, warnings_color, 1)
        y_offset += line_height
        
        cv2.putText(frame, f"Telegram: {tg_status}", 
                   (10, y_offset + 5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0) if notifier.user_manager.get_users_count() > 0 else (0, 165, 255), 1)
        
        # Отображение
        cv2.imshow('SafeDrive AI Monitor - Press ESC to exit', frame)
        if cv2.waitKey(1) & 0xFF == 27:
            break
    
    cap.release()
    cv2.destroyAllWindows()
    print("\n программа завершена")

if __name__ == '__main__':
    main()