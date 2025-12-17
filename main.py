import cv2
import mediapipe as mp
from pynput.keyboard import Key, Controller as KeyboardController
from pynput.mouse import Button, Controller as MouseController
#from screeninfo import get_monitors
import time
import warnings

warnings.filterwarnings('ignore', category=UserWarning)

# ustawienia globalne
ACTION_COOLDOWN = 0.5  # minimalny czas między akcjami, żeby uniknąć wieloklików
last_action_time = time.time()

# zmienne dla klikniecia przytrzymania
HOLD_THRESHOLD = 0.5  # zzas w sekundach po którym kliknięcie staje się przytrzymaniem
left_click_held = False
thumb_up_start_time = 0.0

# parametry dla sterowania kursorem twarzą (sterowanie relatywne)
SENSITIVITY = 150  # wieksza czulosc
DEAD_ZONE = 0.01  # mniejsza martwa strefa
SCROLL_SPEED = 5  # ustawienie prędkości przewijania myszy

#  konfiguracja środowiska i kontrolerów
try:
    from screeninfo import get_monitors

    # próba pobrania rzeczywistego rozmiaru ekranu
    monitor = get_monitors()[0]
    screen_width, screen_height = monitor.width, monitor.height
except Exception:
    # jeśli błąd ustawiam domyślne wartości
    screen_width, screen_height = 1920, 1080

TARGET_X = 100
TARGET_Y = 100

mp_drawing = mp.solutions.drawing_utils

# tworzę obiekty kontrolujące klawiaturę i mysz w systemie
keyboard = KeyboardController()
mouse = MouseController()

#  inicjalizacja stabilnych modeli mediapipe

# model dłoni
mp_hands = mp.solutions.hands
hands = mp_hands.Hands(
    static_image_mode=False,
    max_num_hands=2,
    min_detection_confidence=0.7,
    min_tracking_confidence=0.5
)

# model pose do detekcji głowy
mp_pose = mp.solutions.pose
pose = mp_pose.Pose(min_detection_confidence=0.5, min_tracking_confidence=0.5)
drawing_spec_pose = mp_drawing.DrawingSpec(thickness=2, circle_radius=2, color=(255, 0, 0))

#  inicjalizacja kamery
cap = cv2.VideoCapture(0)

print("Kontroler gotowy. Uruchamiam podgląd z kamery...")


# funkcja pomocnicza do kliknięcia klawiszem
def trigger_key(key):
    keyboard.press(key)
    keyboard.release(key)


# funkcja pomocnicza do kliknięcia myszą
def trigger_mouse_click(button):
    mouse.click(button)


#  funkcja sterowania relatywnego - joystick

def process_relative_mouse_control(normalized_x, normalized_y):

    #obliczam relatywny ruch kursora joystick na podstawie przesunięcia punktu.

    # krok 1 - x=0.0 to lewy kraniec, x=1.0 to prawy kraniec.
    center_x = normalized_x
    center_y = normalized_y

    # krok 2 - obliczenie odchylenia od centrum (0.5 to środek kadru)
    delta_x = center_x - 0.5
    delta_y = center_y - 0.5

    move_x = 0
    # logika dla osi x
    if abs(delta_x) > DEAD_ZONE:
        # obciążam ruch o martwą strefę a potem skaluję czułością
        if delta_x > 0:  # ruch w prawo (x > 0.5)
            move_x = (delta_x - DEAD_ZONE) * SENSITIVITY
        else:  # ruch w lewo (x < 0.5)
            move_x = (delta_x + DEAD_ZONE) * SENSITIVITY

    move_y = 0
    # logika dla osi y
    if abs(delta_y) > DEAD_ZONE:
        if delta_y > 0:  # ruch w dół y rośnie
            move_y = (delta_y - DEAD_ZONE) * SENSITIVITY
        else:  # ruch w górę y maleje
            move_y = (delta_y + DEAD_ZONE) * SENSITIVITY

    # wykonuję relatywny ruch myszą
    mouse.move(int(move_x), int(move_y))

    return f"Ruch X: {move_x:.1f}, Y: {move_y:.1f}"


# główna pętla programu
while cap.isOpened():
    success, image = cap.read()
    if not success:
        print("błąd odczytu strumienia kamery.")
        break

    # korekta lustrzanego odbicia
    image = cv2.flip(image, 1)

    # przetwarzanie obrazu
    image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)

    # procesuję dzialajace modele
    hands_results = hands.process(image_rgb)
    pose_results = pose.process(image_rgb.copy())

    image = cv2.cvtColor(image_rgb, cv2.COLOR_RGB2BGR)

    current_time = time.time()
    current_gesture = None
    action_triggered = False

    # zmienne do sledzenia stanu kciuka lewej reki
    left_thumb_visible = False

    #  kontrola kursorem za pomocą głowy model pose
    if pose_results.pose_landmarks:
        try:
            # używam landmark 0 (nose) z pose jako punktu kontrolnego
            center_of_head = pose_results.pose_landmarks.landmark[mp_pose.PoseLandmark.NOSE]

            # wywołuję funkcję mojego joysticka
            current_gesture = process_relative_mouse_control(
                center_of_head.x,
                center_of_head.y
            )

            # rysowanie punktów pose
            mp_drawing.draw_landmarks(
                image,
                pose_results.pose_landmarks,
                mp_pose.POSE_CONNECTIONS,
                landmark_drawing_spec=drawing_spec_pose,
                connection_drawing_spec=drawing_spec_pose
            )
        except IndexError:
            current_gesture = "detekcja pose: błąd punktu"

    #  analiza gestów dłoni - reczna logika

    if hands_results.multi_hand_landmarks:

        for idx, hand_landmarks in enumerate(hands_results.multi_hand_landmarks):

            hand_label = hands_results.multi_handedness[idx].classification[0].label

            # rysowanie punktów
            mp_drawing.draw_landmarks(
                image, hand_landmarks, mp_hands.HAND_CONNECTIONS)

            # pobieram współrzędne potrzebne do mojej logiki
            index_finger_tip = hand_landmarks.landmark[mp_hands.HandLandmark.INDEX_FINGER_TIP]
            index_finger_pip = hand_landmarks.landmark[mp_hands.HandLandmark.INDEX_FINGER_PIP]
            middle_finger_tip = hand_landmarks.landmark[mp_hands.HandLandmark.MIDDLE_FINGER_TIP]
            middle_finger_pip = hand_landmarks.landmark[mp_hands.HandLandmark.MIDDLE_FINGER_PIP]
            thumb_tip = hand_landmarks.landmark[mp_hands.HandLandmark.THUMB_TIP]
            thumb_ip = hand_landmarks.landmark[mp_hands.HandLandmark.THUMB_IP]

            # Ustalenie warunków dla gestów
            index_up = index_finger_tip.y < index_finger_pip.y
            middle_up = middle_finger_tip.y < middle_finger_pip.y
            two_fingers_up = index_up and middle_up

            # warunek dla kciuka Lewej Ręki
            is_left_thumb_up = hand_label == "Left" and thumb_tip.x > thumb_ip.x

            # przetwarzanie gestów wymagających cooldownu klik scrol i klawisze
            if (current_time - last_action_time) > ACTION_COOLDOWN and not action_triggered:

                # gest - prawy kciuk - prawy klik (Pewny klik, nie hold)
                # logika - prawa dłoń, kciuk wyprostowany czubek na lewo od stawu, inne palce opuszczone albo zgięte
                is_right_thumb_up = hand_label == "Right" and thumb_tip.x < thumb_ip.x
                if is_right_thumb_up and not two_fingers_up:
                    trigger_mouse_click(Button.right)
                    current_gesture = "prawa: prawy klik"
                    last_action_time = current_time
                    action_triggered = True

                # gest prawa reka czyli scrool w gore
                elif hand_label == "Right" and two_fingers_up:
                    mouse.scroll(0, SCROLL_SPEED)
                    current_gesture = "prawa: scroll up"
                    last_action_time = current_time
                    action_triggered = True

                # gest lewa reka scrool w dol
                elif hand_label == "Left" and two_fingers_up:
                    mouse.scroll(0, -SCROLL_SPEED)
                    current_gesture = "lewa: scroll down"
                    last_action_time = current_time
                    action_triggered = True

                # gest dla strzalek (lewy i prawy palec wskazujacy)
                elif index_up and not two_fingers_up:
                    if hand_label == "Right":
                        trigger_key(Key.right)
                        current_gesture = "prawa: key_right"
                    elif hand_label == "Left":
                        trigger_key(Key.left)
                        current_gesture = "lewa: key_left"

                    last_action_time = current_time
                    action_triggered = True


            # info o lewym kciuku
            if is_left_thumb_up:
                left_thumb_visible = True

    # gest lewy kciuk - klik i przytrzymanie

    if left_thumb_visible:
        # kciuk widoczny

        if not left_click_held:
            # stan nr 1 - kciuk się pojawił, ale nie jest przytrzymany
            if thumb_up_start_time == 0.0:
                thumb_up_start_time = current_time

            # stan 2 - czas trzymania przekroczył HOLD_THRESHOLD - mamy przytrzymanie
            time_held = current_time - thumb_up_start_time
            if time_held >= HOLD_THRESHOLD:
                mouse.press(Button.left)
                left_click_held = True
                current_gesture = f"lewa: HOLD ({time_held:.1f}s)"

        else:
            # stan 3 - trzymamy przycisk hold i aktualizujemy status
            time_held = current_time - thumb_up_start_time
            current_gesture = f"lewa: HOLD ({time_held:.1f}s)"

    else:
        # nie ma kciuka

        if left_click_held:
            # stan 4 - puszczamy przycisk po HOLD
            mouse.release(Button.left)
            left_click_held = False
            current_gesture = "lewa: RELEASED"

        elif thumb_up_start_time != 0.0:
            # stan 5 - kciuk zniknął zanim osiągnął próg HOLD - klik
            time_visible = current_time - thumb_up_start_time

            if time_visible < HOLD_THRESHOLD:
                # wyslanie klik (press + release)
                mouse.press(Button.left)
                mouse.release(Button.left)
                current_gesture = f"lewa: CLICK ({time_visible:.1f}s)"
                last_action_time = current_time  # resetujemy cooldown

        # w każdym przypadku braku gestu - resetujemy licznik czasu
        thumb_up_start_time = 0.0

    #  wizualizacja i zamykanie

    status_text = f"gest: {current_gesture if current_gesture else 'brak'}. sens: {SENSITIVITY} / dead: {DEAD_ZONE}"
    cv2.putText(image, status_text, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2, cv2.LINE_AA)

    cv2.imshow('kontroler (pose + hands)', image)

    # zakończenie programu klawiszem 'esc'
    if cv2.waitKey(5) & 0xFF == 27:
        break

# sprzątanie
cap.release()
cv2.destroyAllWindows()
print("program zakończony.")