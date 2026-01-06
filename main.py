import cv2 #laczy sie z kamera i odczytuje klatki
import mediapipe as mp #model twarzy
from pynput.keyboard import Key, Controller as KeyboardController #pozwala na klikanie klawiszy w systemie
from pynput.keyboard import KeyCode #obsluga klawiszy spoza listy
from pynput.mouse import Button, Controller as MouseController #pozwala na poruszanie myszka w systemie
import time #aktualny czas
import warnings #warningi do ignorowania
from screeninfo import get_monitors #sprawdza rozdzielczosc ekranu

'''
aktualny stan projektu - wersja do oddania
twarz a dokladnie nos to sterowanie myszka
otwarcie ust to wspomaganie pisania, taka autokorekta troche
ruch prawej reki w lewo to lewy mouse click
przytrzymanie prawej reki na lewo to przytrzymanie lewego mouse clicka
ruch prawej reki w prawo to prawy mouse click
podniesienie brwi to szybkie dwa lewe kliki
obie rece na zewnatrz to zablokowanie myszki, nie rusza sie kursor - lekko mniejszy ruch niz prawy klik,
a wtedy zablokowane sa brwi, usta i lewa reka - dziala zamykanie i prawa reka
lewa reka w lewo scroll w gore
prawa reka w lewo scroll w dol
program uruchamia klawiature przy mrugnieciu 3 razy
program wylacza klawiature przy mrugnieciu 3 razy
mozna wylaczyc program zamykajac oczy na iles sekund (teraz 5)
'''

warnings.filterwarnings('ignore', category=UserWarning)

#zmienna mowiaca czy lewy mouse click jest przytrzymany - flaga
is_left_held = False

# Ustawienia globalne
ACTION_COOLDOWN = 0.5 #minimalny odstep czasowy miedzy akcjami np kliknieciami
last_action_time = time.time() #zmienna pomocnicza ktora przechowuje znacznik czasu ostatniej wykonanej akcji

# Parametry sterowania głową (myszka)
SENSITIVITY = 300 #czulosc myszki
DEAD_ZONE = 0.01 #martwa strefa czyli jak duzy obszar wokol nosa jest ignorowany

# Dynamiczny środek dla głowy
base_nose_x = 0.5 #wspolrzedne punktu odniesienia czyli srodka ekranu
base_nose_y = 0.5 #program oblicza ruch nosa jako roznice aktualnych wspolrzednych i srodka
NOSE_SMOOTH_FACTOR = 0.01 #wspolczynnik adaptacji decydujacy jak szybko punkt odniesienia podaza za glowa

# blokada myszki
is_mouse_locked = False #aktualny stan blokady myszki
hands_currently_wide = False #flaga ktora blokuje wielokrotne przelaczania blokady
HANDS_WIDE_THRESHOLD = 0.03    # maly ruch do aktywacji
HANDS_RELEASE_THRESHOLD = 0.03 # nizszy prog dla powrotu rak
last_lock_toggle_time = 0      # czas ostatniego przelaczenie
LOCK_TOGGLE_COOLDOWN = 1.0     # sekunda - przerwy między przełączeniami

# Parametry dla detekcji otwarcia ust
MOUTH_OPEN_THRESHOLD = 0.03 #po przekroczeniu tego dystansu warg jest wygrywane otworzenie buzi
mouth_cooldown = 1.5 #czas oczekiwania po otwarciu zeby znowu moc otworzyc

# Parametry dla detekcji kliknięć łokciem
ELBOW_LEFT_CLICK_THRESHOLD = -0.06 # jak mocno trzeba dac reke w lewo zeby byl klik
ELBOW_RIGHT_CLICK_THRESHOLD = 0.06 #jak mocno trzeba dac reke w prawo zeby byl klik
ELBOW_RELEASE_THRESHOLD = -0.04     # prog dla puszczenia przycisku blizej srodka reka

# do przytrzymania lewego klika
HOLD_THRESHOLD_TIME = 1.0# Po jakim czasie (sekundy) klik zamienia się w trzymanie
left_elbow_press_start_time = None #zapisuje moment w ktorym odchylony zostal lokiec
has_clicked_once = False # Flaga pomocnicza, zeby nie bylo klikniecia w kazdej klatce

# podwojny klik brwiami
BROW_JUMP_THRESHOLD = 0.01  # o ile brwi muszą się podnieść ponad stan spoczynkowy
base_brow_dist = 0.0         # kalibrowana odległość spoczynkowa
brow_initialized = False     # flaga kalibracji
BROW_SMOOTH_FACTOR = 0.05   # jak szybko system adaptuje się do nowej mimiki

# Parametry dla detekcji scrollowania lewa reka
LEFT_HAND_SCROLL_UP_THRESHOLD = 0.05     # Lewa ręka w prawo = scroll w górę
LEFT_HAND_SCROLL_DOWN_THRESHOLD = -0.03  # Lewa ręka w lewo = scroll w dół
SCROLL_SPEED = 20  # Prędkość scrollowania

# Dynamiczny środek dla pozycji lewego łokcia
base_left_elbow_offset_x = 0.0 #pozycja spoczynkowa lewego lokcia wzgledm barku
left_elbow_initialized = False #po pokazaniu sie sylwetki ustawiana na true po pobraniu pozycji lokcia

# Dynamiczny środek dla pozycji łokcia
base_elbow_offset_x = 0.0 #punkt odniesienia dla prawego lokcia, do wykrywania gestow
ELBOW_SMOOTH_FACTOR = 0.02 #wspolczynnik pamieci - powoduje ze punkty odniesienia podazaja za cialem

# Parametry dla zamykania oczu (wyjście z programu)
EYES_CLOSED_THRESHOLD = 0.005 #bardzo mocno zamkniete oczy
EYES_CLOSED_DURATION = 5.0 #czas trwania zamkniecia oczu
eyes_closed_start_time = None #znacznik czasu - moment w ktorym zostaly zamkniete oba oczy

# potrojne mrugniecie - parametry
blink_count = 0 #ile bylo mrugniec
last_blink_time = 0 #czas kiedy bylo ostatnie mrugniecie
blink_cooldown = 0.5  # Maksymalny czas między mrugnięciami (sekundy)
is_blinking = False   # Flaga zapobiegająca liczeniu jednej klatki jako wielu mrugnięć

# Inicjalizacja kontrolerów i modelu
keyboard = KeyboardController()
mouse = MouseController()

# Dynamiczne pobieranie rozdzielczości głównego monitora
try:
    primary_monitor = get_monitors()[0]
    screen_width = primary_monitor.width
    screen_height = primary_monitor.height
    print(f"LOG: Wykryto ekran: {screen_width}x{screen_height}")
except Exception as e:
    print(f"LOG: Błąd screeninfo, ustawiam domyślne: {e}")
    screen_width, screen_height = 1728, 1117


#funkcja ktora otwiera lub zamyka klawiature poprzez 2 klikniecia na ekranie
def openORclose_keyboard_via_click():
    # Funkcja uruchamiajaca klawiature ekranowa bo nie dalo sie skrotem
    print("LOG: Próba aktywacji klawiatury przez kliknięcie w pasek menu...")

    original_position = mouse.position

    # Ikona klawiatury na screenie jest blisko prawej strony
    target_x1 = 1180 # jak jest globus, klawiatura, spotify
    target_y1 = 20

    # Przesunięcie i klik
    mouse.position = (target_x1, target_y1)
    time.sleep(0.3)
    mouse.click(Button.left)
    time.sleep(0.3)

    #klikniecie docelowego podgladu klawiatury
    target_x2 = 1180
    target_y2 = 80

    # Przesunięcie i klik
    mouse.position = (target_x2, target_y2)
    time.sleep(0.1)
    mouse.click(Button.left)

    # Czekamy chwilę na animację rozwinięcia i wracamy na środek
    time.sleep(0.5)
    #mouse.position = (screen_width // 2, screen_height // 2)
    mouse.position = original_position
    #print(f"LOG: Kliknięcie wykonane na X:{target_x1}. Kursor wrócił na środek: {mouse.position}")
    print(f"LOG: Kliknięcie wykonane na X:{target_x1}. Kursor wrócił na poprzednia pozycje: {mouse.position}")


# wlaczenie mediapipe Pose (dla głowy i rak)
mp_pose = mp.solutions.pose
pose = mp_pose.Pose(
    min_detection_confidence=0.5,
    min_tracking_confidence=0.5,
    model_complexity=1
)

# facemesh (dla ust i oczu)
mp_face_mesh = mp.solutions.face_mesh
face_mesh = mp_face_mesh.FaceMesh(
    max_num_faces=1,
    refine_landmarks=True,
    min_detection_confidence=0.5,
    min_tracking_confidence=0.5
)

mp_drawing = mp.solutions.drawing_utils

# wlaczenie kamery
cap = cv2.VideoCapture(0)
#opcjonalne zakomentowane wlaczenie klawiatury podczas odpalenia programu
'''
if cap.isOpened():
    openORclose_keyboard_via_click()
'''
#wypisywanie instrukcji w terminalu po odpaleniu
print("Kontroler gestów uruchomiony")
print("Głowa = sterowanie myszką")
print("Usta otwarte = wspomaganie pisania")
print("Prawy ręka w prawo = prawy klik myszy")
print("Prawa ręka w lewo = lewy klik myszy")
print("Przytrzymanie prawej ręki w lewo = przytrzymanie lewego kliku myszy")
print("Obie ręce pokierowane na zewnątrz = zatrzymanie ruszu myszy")
print("Podniesienie brwi = dwa lewe kliki myszy")
print("Lewa ręka w lewo = scroll w dół")
print("Lewa ręka w prawo = scroll w górę")
print("Zamknięte oczy przez 5 sek = wyjście z programu")
print("Mrugnięcie szybko 3 razy = włączenie/wyłączenie klawiatury")
print("ESC = wyjście")

#funkcja klikajaca przycisk po jego kodzie aktualnie zakomentowane
def trigger_key_by_code(code):
    key = KeyCode.from_vk(code)
    keyboard.press(key)
    keyboard.release(key)


# funkcja sterowania myszką głową
def move_mouse_with_head(current_nose_x, current_nose_y, center_x, center_y):
    # Obliczam odchylenie od środka czyli jak daleko jest nos od punktu srodka ekranu
    delta_x = current_nose_x - center_x
    delta_y = current_nose_y - center_y

    # Inicjalizacja ruchu
    move_x = 0
    move_y = 0

    # Logika osi x lewo prawo
    if abs(delta_x) > DEAD_ZONE:
        if delta_x > 0:
            #odjecie dead_zone, zeby myszka nie skakala tylko normalnie jechala - ruch w prawo
            effective_delta = delta_x - DEAD_ZONE
            move_x = effective_delta * SENSITIVITY
        else:
            #dodanie dead_zone zeby bylo bliskie zera ale na minusie - ruch w lewo
            effective_delta = delta_x + DEAD_ZONE
            move_x = effective_delta * SENSITIVITY

    # Logika osi y gora dol
    if abs(delta_y) > DEAD_ZONE:
        #jazda myszki w dol
        if delta_y > 0:
            effective_delta = delta_y - DEAD_ZONE
            move_y = effective_delta * SENSITIVITY
        else:
            #jazda myszki w gore
            effective_delta = delta_y + DEAD_ZONE
            move_y = effective_delta * SENSITIVITY

    # Wykonaj ruch myszą
    if move_x != 0 or move_y != 0:
        mouse.move(int(move_x), int(move_y))
    #dodatkowe wypisanie wektorow przesuniec myszy
    return (move_x, move_y)


# funkcja detekcji otwarcia ust z facemesh
def detect_mouth_open_face_mesh(face_landmarks):
    try:
        # indeksy kluczowych punktow ust w facemesh
        # 13 = górna warga środek
        # 14 = dolna warga środek
        upper_lip = face_landmarks.landmark[13]
        lower_lip = face_landmarks.landmark[14]

        # obliczam pionową odległość między wargami
        vertical_distance = abs(upper_lip.y - lower_lip.y)

        # sprawdzam czy przekroczono prog
        is_mouth_open = vertical_distance > MOUTH_OPEN_THRESHOLD

        #true lub false i dystans do komunikatu
        return (is_mouth_open, vertical_distance)

    except (IndexError, AttributeError):
        return (False, 0.0)


# Funkcja detekcji zamkniętych oczu z facemesh
def detect_eyes_closed(face_landmarks):
    try:
        # Indeksy kluczowych punktów oczu w facemesh
        # Lewe oko: 159 (górna powieka), 145 (dolna powieka)
        # Prawe oko: 386 (górna powieka), 374 (dolna powieka)

        # Lewe oko
        left_eye_top = face_landmarks.landmark[159]
        left_eye_bottom = face_landmarks.landmark[145]
        left_eye_distance = abs(left_eye_top.y - left_eye_bottom.y)

        # Prawe oko
        right_eye_top = face_landmarks.landmark[386]
        right_eye_bottom = face_landmarks.landmark[374]
        right_eye_distance = abs(right_eye_top.y - right_eye_bottom.y)

        # Sprawdzam czy oba oczy są zamknięte
        left_closed = left_eye_distance < EYES_CLOSED_THRESHOLD
        right_closed = right_eye_distance < EYES_CLOSED_THRESHOLD
        both_closed = left_closed and right_closed

        avg_distance = (left_eye_distance + right_eye_distance) / 2

        return (both_closed, avg_distance)

    except (IndexError, AttributeError):
        return (False, 0.0)

# Funkcja detekcji scrollowania lewą ręką
def detect_left_hand_scroll(landmarks, base_offset):
    try:
        # Pobieram współrzędne lewego barku i łokcia (przy lustrzanym odbiciu to RIGHT w kodzie)
        right_shoulder = landmarks[mp_pose.PoseLandmark.RIGHT_SHOULDER]
        right_elbow = landmarks[mp_pose.PoseLandmark.RIGHT_ELBOW]

        # Obliczam względną pozycję łokcia względem barku
        raw_offset = right_elbow.x - right_shoulder.x

        # Obliczam odchylenie od dynamicznego środka
        deviation = raw_offset - base_offset

        # Sprawdzam czy przekroczono progi
        scroll_type = None

        # lokiec na prawo fizycznie lewa ręka = scroll gora
        if deviation > LEFT_HAND_SCROLL_UP_THRESHOLD:
            scroll_type = "up"

        # lokiec na lewo fizycznie lewa ręka = scroll dol
        elif deviation < LEFT_HAND_SCROLL_DOWN_THRESHOLD:
            scroll_type = "down"

        #funkcja zwraca typ aktualnego scrolla i wartosc jak daleko od pozycji spoczynkowej znajduje sie lokiec
        return (scroll_type, deviation)

    except (IndexError, AttributeError):
        return (None, 0.0)


# Funkcja detekcji kliknięć łokciem
def detect_elbow_click(landmarks, base_offset):
    try:
        # Pobieram współrzędne prawego barku i łokcia przy lustrzanym odbiciu kamery, wiec jest to prawa reka
        left_shoulder = landmarks[mp_pose.PoseLandmark.LEFT_SHOULDER]
        left_elbow = landmarks[mp_pose.PoseLandmark.LEFT_ELBOW]

        # Obliczam względną pozycję łokcia względem barku
        raw_offset = left_elbow.x - left_shoulder.x

        # Obliczam odchylenie od dynamicznego środka
        deviation = raw_offset - base_offset

        # Sprawdzam czy przekroczono progi
        click_type = None

        # Łokieć na prawo (fizycznie prawa ręka) = PRAWY KLIK
        if deviation > ELBOW_RIGHT_CLICK_THRESHOLD:
            click_type = "right"

        # Łokieć na lewo (fizycznie prawa ręka) = LEWY KLIK
        elif deviation < ELBOW_LEFT_CLICK_THRESHOLD:
            click_type = "left"

        #zwraca typ klika i wartosc jak daleko od pozycji spoczynkowej znajduje sie lokiec
        return (click_type, deviation)

    except (IndexError, AttributeError):
        return (None, 0.0)

#funkcja wykrywajaca wzniesienie brwi
def detect_brow_jump(face_landmarks, current_base_dist):
    try:
        # 105: środek brwi, 159: góra powieki
        brow_top = face_landmarks.landmark[105]
        #eye_top = face_landmarks.landmark[159]
        eye_top = face_landmarks.landmark[468] #zamiana na srodek oka

        current_dist = abs(brow_top.y - eye_top.y)
        deviation = current_dist - current_base_dist

        # jeśli różnica jest większa niż próg to skok brwi
        is_jump = deviation > BROW_JUMP_THRESHOLD

        #czy podniesione, dystans miedzy okiem i liczba o ile wyzej podniesione od punktu spoczynku
        return (is_jump, current_dist, deviation)
    except (IndexError, AttributeError):
        return (False, 0.0, 0.0)

elbow_initialized = False #bezpiecznik przy odpaleniu programu, po odpaleniu szuka lokcia

#licznik klatek
frame_count = 0

# glowna pętla programu
while cap.isOpened():

    # Odczyt klatki z kamery
    success, image = cap.read()
    if not success:
        print("Błąd odczytu kamery!")
        break

    # odbicie lustrzane
    image = cv2.flip(image, 1)

    # konwersja do rgb bo mediapipe wymaga
    image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)

    # przetwarzanie przez oba modele
    pose_results = pose.process(image_rgb)
    face_results = face_mesh.process(image_rgb)

    # konwersja z powrotem do BGR dla OpenCV
    image = cv2.cvtColor(image_rgb, cv2.COLOR_RGB2BGR)

    # Aktualny czas dla cooldownów
    current_time = time.time()

    # Zmienne do śledzenia statusu
    gesture_text = "Brak" #do komunikatow na ekranie
    elbow_deviation = 0.0
    mouth_distance = 0.0
    eyes_distance = 0.0

    eyes_closed_time_remaining = 0.0 #czas do zamkniecia programu
    # Przetwarzanie wykrytych landmarków z Pose
    if pose_results.pose_landmarks: #jesli wykryto sylwetke
        landmarks = pose_results.pose_landmarks.landmark

        # Inicjalizacja bazowej pozycji lewego łokcia (dla scrollowania), robimy try czy wykryje
        try:
            right_shoulder = landmarks[mp_pose.PoseLandmark.RIGHT_SHOULDER]
            right_elbow = landmarks[mp_pose.PoseLandmark.RIGHT_ELBOW]
            #stabilne policzenie odleglosci miedzy reka a barkiem niewazne gdzie siedze
            raw_left_elbow_offset = right_elbow.x - right_shoulder.x

            if not left_elbow_initialized: #jesli pierwszy raz wykrywa reke
                base_left_elbow_offset_x = raw_left_elbow_offset #zapiuje dystans jako spoczynkowy
                left_elbow_initialized = True
                print("Zkalibrowano pozycję spoczynkową lewego łokcia")

            #blokada dzialania scrollowania przy zablokowanej myszy
            if not is_mouse_locked:
                # Detekcja scrollowania lewą ręką
                scroll_type, left_elbow_deviation = detect_left_hand_scroll(landmarks, base_left_elbow_offset_x)

                # Aktualizacja dynamicznego środka dla lewego łokcia
                if not (elbow_deviation > HANDS_WIDE_THRESHOLD and left_elbow_deviation < -HANDS_WIDE_THRESHOLD):
                    if scroll_type is None:
                        #wygladzanie adaptacyjnego nowego srodka lokcia, 2% nowego polozenia
                        base_left_elbow_offset_x = (base_left_elbow_offset_x * (1.0 - ELBOW_SMOOTH_FACTOR)) + (
                                raw_left_elbow_offset * ELBOW_SMOOTH_FACTOR)

                # Wykonanie scrollowania bez blokowania całego programu cooldownem
                if scroll_type is not None:
                    # mniejsze lokalne opoznienie zeby nie scrollowac za szybko
                    # bez aktualizacji globalnego last_action_time
                    if scroll_type == "up":
                        mouse.scroll(0, 1)  # mniejszy krok ale wykonywany w każdej klatce = płynność
                        gesture_text = "SCROLL W GÓRĘ"
                    elif scroll_type == "down":
                        mouse.scroll(0, -1)
                        gesture_text = "SCROLL W DÓŁ"
            else: #gdy myszka zablokowana
                # obliczamy odchylenie, bo potrzebne do odblokowania, nie scrolujemy
                left_elbow_deviation = raw_left_elbow_offset - base_left_elbow_offset_x
        #zeby nie wylaczalo programu jak cos zniknie
        except (IndexError, AttributeError):
            pass

        try: #znowu dla glowy
            # Sterowanie myszką głową
            nose = landmarks[mp_pose.PoseLandmark.NOSE]

            current_nose_x = nose.x
            current_nose_y = nose.y

            # Aktualizacja dynamicznego środka powolna adaptacja
            base_nose_x = (base_nose_x * (1.0 - NOSE_SMOOTH_FACTOR)) + (current_nose_x * NOSE_SMOOTH_FACTOR)
            base_nose_y = (base_nose_y * (1.0 - NOSE_SMOOTH_FACTOR)) + (current_nose_y * NOSE_SMOOTH_FACTOR)

            # Wykonanie ruchu myszą TYLKO jeśli nie ma blokady
            if not is_mouse_locked:
                move_x, move_y = move_mouse_with_head(
                    current_nose_x,
                    current_nose_y,
                    base_nose_x,
                    base_nose_y
                )
                gesture_text = f"Mysz X:{move_x:.0f} Y:{move_y:.0f}"
            else:
                # Wyświetlanie dużego napisu na środku ekranu, gdy mysz jest zablokowana
                gesture_text = "MYSZ ZABLOKOWANA"
                cv2.putText(
                    image,
                    "MYSZ ZABLOKOWANA",
                    (image.shape[1] // 2 - 250, image.shape[0] // 2),  # Pozycja środkowa
                    cv2.FONT_HERSHEY_SIMPLEX,
                    1.5,  # Rozmiar czcionki
                    (0, 0, 255),  # Kolor czerwony (BGR)
                    4,  # Grubość linii
                    cv2.LINE_AA
                )



            # Detekcja kliknięć łokciem
            left_shoulder = landmarks[mp_pose.PoseLandmark.LEFT_SHOULDER]
            left_elbow = landmarks[mp_pose.PoseLandmark.LEFT_ELBOW]
            raw_elbow_offset = left_elbow.x - left_shoulder.x #obliczenie roznicy miedzy polozeniem lokcia i barku

            # Inicjalizacja bazowej pozycji łokcia
            if not elbow_initialized:
                base_elbow_offset_x = raw_elbow_offset #przypisane raz
                elbow_initialized = True
                print("Zkalibrowano pozycję spoczynkową prawego łokcia")

            # Obliczam odchylenie od dynamicznego środka
            deviation = raw_elbow_offset - base_elbow_offset_x

            # Wykonanie kliknięcia jeśli wykryto gest i minął cooldown
            click_type, elbow_deviation = detect_elbow_click(landmarks, base_elbow_offset_x)

            # blokada myszki
            is_wide_trigger = elbow_deviation > HANDS_WIDE_THRESHOLD and left_elbow_deviation < -HANDS_WIDE_THRESHOLD
            is_fully_released = elbow_deviation < HANDS_RELEASE_THRESHOLD and left_elbow_deviation > -HANDS_RELEASE_THRESHOLD

            if is_wide_trigger:
                #sprawdza czy minął cooldown i czy gest nie jest kontynuacją poprzedniego
                #sprawdza tez czy w poprzedniej klatce nie byly rozlozone rece, zeby nie przelaczac milion razy
                if not hands_currently_wide and (current_time - last_lock_toggle_time) > LOCK_TOGGLE_COOLDOWN:
                    is_mouse_locked = not is_mouse_locked #przelaczenie blokady z true na false i na odwrot
                    last_lock_toggle_time = current_time #reset licznika czasu
                    hands_currently_wide = True #oznaczenie ze rece sa szeroko, zeby nie klikac w petli
                    print(f"LOG: Blokada myszy: {is_mouse_locked}")
                    if is_mouse_locked:
                        # LEKKIE SZTARPNIĘCIE KURSOREM - Sygnał blokady
                        # Przesuwamy o 40 pikseli w lewo, żeby było to wyraźnie czuć
                        mouse.move(-40, 0)
                        print(f"LOG: Mysz ZABLOKOWANA - wykonano skok kontrolny")
                    else:
                        # Przy odblokowaniu możemy wraca mysz w prawo gdzie byla
                        mouse.move(40, 0)
                        print(f"LOG: Mysz ODBLOKOWANA")

            # resett flagi 'wide' tylko gdy ręce wrócą wyraźnie do środka
            if is_fully_released:
                hands_currently_wide = False

            # aktualizuje baze tylko gdy nie ma gestu szerokich rąk
            if not (elbow_deviation > HANDS_WIDE_THRESHOLD and left_elbow_deviation < -HANDS_WIDE_THRESHOLD):
                if click_type is None:
                    #ponownie aktualizacja bazy lokci, 2% nowej i 98 starej
                    base_elbow_offset_x = (base_elbow_offset_x * (1.0 - ELBOW_SMOOTH_FACTOR)) + (
                            raw_elbow_offset * ELBOW_SMOOTH_FACTOR)
            else:
                # mozna jeszcze bardziej spowolnić wygładzanie
                # ale najlepiej całkowicie je wstrzymać podczas trzymania kliku.
                pass

            # Wykonanie kliknięcia jeśli wykryto gest i minął cooldown
            # hold dla lewego klika/albo zwykly klik i prawy klik
            if click_type == "left":
                if left_elbow_press_start_time is None: # nie bylo momentu odchylenia lokcia
                    # Moment pierwszego wychylenia ręki
                    left_elbow_press_start_time = current_time #zaczyna liczyc czas
                    mouse.press(Button.left)
                    is_left_held = True
                    has_clicked_once = False
                    print("LOG: Start nacisku...")

                # jesli trzyma dlugo uznajemy to za hold, teraz wiecej niz 0.8 sekundy
                elif not has_clicked_once and (current_time - left_elbow_press_start_time) > HOLD_THRESHOLD_TIME:
                    gesture_text = "TRYB: PRZECIĄGANIE (HOLD)"

            else:
                # jesli reka byla na lewo i wrocila do srodka
                if is_left_held: #jesli przycisk byl wcisniety
                    press_duration = current_time - left_elbow_press_start_time
                    mouse.release(Button.left) #puszcza przycisk

                    if press_duration < HOLD_THRESHOLD_TIME:
                        print(f"LOG: Krótkie kliknięcie ({press_duration:.2f}s)")
                        gesture_text = "LEWY KLIK"
                    else:
                        print(f"LOG: Koniec przeciągania ({press_duration:.2f}s)")
                        gesture_text = "PUSZCZONO (DRAG END)"


                    # Reset zmiennych
                    is_left_held = False
                    left_elbow_press_start_time = None

            # Prawy klik zostawiamy jako pojedynczy impuls
            if click_type == "right" and (current_time - last_action_time) > ACTION_COOLDOWN:
                mouse.click(Button.right)
                gesture_text = "PRAWY KLIK"
                last_action_time = current_time #reset czasu ostatniego gestu

            # Rysowanie landmarków Pose na obrazzie, w kazdej klatce zeby wykrywalo ruch
            mp_drawing.draw_landmarks(
                image,
                pose_results.pose_landmarks,
                mp_pose.POSE_CONNECTIONS,
                mp_drawing.DrawingSpec(color=(0, 255, 0), thickness=2, circle_radius=2),
                mp_drawing.DrawingSpec(color=(0, 0, 255), thickness=2)
            )

        except (IndexError, AttributeError) as e:
            gesture_text = f"Błąd Pose: {str(e)}" #wyswietlenie informacji o bledzie zamiast wylaczenie


    # Detekcja otwarcia ust i zamkniętych oczu z Face Mesh
    if face_results.multi_face_landmarks: #jesli znaleziono twarz
        for face_landmarks in face_results.multi_face_landmarks:
            eyes_closed, eyes_distance = detect_eyes_closed(face_landmarks) #wywoluje funkcje, zeby sprawdzic czy oczy zamkniete
            if eyes_closed:
                # zamykanie programu poprzez trzymanie zamknietych oczu
                if eyes_closed_start_time is None:
                    eyes_closed_start_time = current_time
                    print("Oczy zamknięte - rozpoczęto odliczanie")

                eyes_closed_duration = current_time - eyes_closed_start_time #liczenie czasu zamkniecia oczu
                eyes_closed_time_remaining = EYES_CLOSED_DURATION - eyes_closed_duration

                if eyes_closed_duration >= EYES_CLOSED_DURATION:
                    print(f"Oczy zamknięte przez {EYES_CLOSED_DURATION:.3f} sekund - zamykanie kontrolera")
                    gesture_text = "ZAMYKANIE PROGRAMU POPRZEZ OCZY"
                    cv2.putText(image, "ZAMYKANIE", (image.shape[1] // 2 - 150, image.shape[0] // 3),
                    cv2.FONT_HERSHEY_SIMPLEX, 2.0, (0, 0, 255), 4, cv2.LINE_AA)
                    cv2.imshow('Kontroler Gestow', image)
                    cv2.waitKey(1000) #czekanie sekundy przed zamknieciem
                    break
            else:
                # gdy oczy znowu otwarte - resetowanie flagi
                is_blinking = False
                # oczy otwarte - resetujemy licznik zamykania
                if eyes_closed_start_time is not None:
                    print("Oczy otwarte - anulowano zamykanie")
                eyes_closed_start_time = None

            if not is_mouse_locked:

                # Sprawdzam czy usta są otwarte - wywolanie funkcji
                is_mouth_open, mouth_distance = detect_mouth_open_face_mesh(face_landmarks)

                # jesli minal cooldown i usta sa otwarte to f5- wspomaganie pisania
                if is_mouth_open and (current_time - last_action_time) > mouth_cooldown:
                    keyboard.press(Key.f5)
                    keyboard.release(Key.f5)
                    gesture_text = "F5 WSPOMAGANIE PISANIA (usta)"
                    last_action_time = current_time #reset do cooldownu

                # Sprawdzam stan oczu - to wczesniej zrobione przed blokada
                #eyes_closed, eyes_distance = detect_eyes_closed(face_landmarks)

                if eyes_closed:
                    # potrojne mrugniecie - odpalenie klawiatury
                    if not is_blinking: #jesli to pcozatek mrugniecia
                        is_blinking = True  # blokada - liczy mrugniecia tylko raz zabye nie liczyc duzy razy w jednej klatce
                        current_time_blink = time.time()

                        # sprawdzam czy to mrugnięcie mieści się w czasie od poprzedniego
                        if current_time_blink - last_blink_time < 0.8:  # 0,8s dla lepszej czulosci
                            blink_count += 1
                        else:
                            blink_count = 1  # jesli przerwa byla za duza to reset licznika

                        last_blink_time = current_time_blink #okreslanie aktualnego czasu mrugniecia
                        print(f"DEBUG: Mrugnięcie {blink_count}/3")

                        if blink_count >= 3:
                            print("LOG: Wykryto 3 mrugnięcia - URUCHAMIAM KLAWIATURĘ")
                            openORclose_keyboard_via_click()
                            blink_count = 0  # Reset po sukcesie

                # podwojny klik brwiami
                is_brow_jump, cur_brow_dist, brow_dev = detect_brow_jump(face_landmarks, base_brow_dist)

                # kalibracja brwi w 1 klatce
                if not brow_initialized:
                    base_brow_dist = cur_brow_dist #bazowa pozycja brwi - jako aktualna
                    brow_initialized = True #kalibrowana pozycja raz na starcie

                # aktualizacja pozycji brwi w spoczynku
                if not is_brow_jump:
                    base_brow_dist = (base_brow_dist * (1.0 - BROW_SMOOTH_FACTOR)) + (
                                cur_brow_dist * BROW_SMOOTH_FACTOR)

                # podwojny klik
                if is_brow_jump and (current_time - last_action_time) > ACTION_COOLDOWN:
                    mouse.click(Button.left, 2)  # dwojka w nawiasie - podwojne klikniecie
                    gesture_text = "DOUBLE CLICK (BRWI)"
                    last_action_time = current_time #reset ostatniego czasu wykonania akcjie
                    print(f"LOG: Double Click! Odchylenie: {brow_dev:.4f}")

            # Rysowanie punktów twarzy
            mp_drawing.draw_landmarks(
                image,
                face_landmarks,
                mp_face_mesh.FACEMESH_CONTOURS, #tylko punkty tworzace kontury
                landmark_drawing_spec=None, #bez kropek
                connection_drawing_spec=mp_drawing.DrawingSpec(color=(0, 255, 255), thickness=1)
            )


    # Wizualizacja na ekranie
    cv2.putText(
        image,
        f"Gest: {gesture_text}",
        (10, 30),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.7,
        (0, 255, 0),
        2,
        cv2.LINE_AA
    )

    # Wartości diagnostyczne
    diagnostic_text = f"Lokiec: {elbow_deviation:.3f} | Usta: {mouth_distance:.3f} | Oczy: {eyes_distance:.3f}"
    cv2.putText(
        image,
        diagnostic_text,
        (10, 60),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.6,
        (255, 255, 0),
        1,
        cv2.LINE_AA
    )

    # Komunikat o zamykaniu oczu (jeśli trwa)
    if eyes_closed_start_time is not None and eyes_closed_time_remaining > 0:
        countdown_text = f"ZAMYKANIE ZA: {eyes_closed_time_remaining:.1f}s"
        cv2.putText(
            image,
            countdown_text,
            (10, 380), #pozycja tekstu
            cv2.FONT_HERSHEY_SIMPLEX, #font
            1.0, #rozmiar czcionki
            (0, 0, 255), #kolor czerwony
            3, #grubosc linii
            cv2.LINE_AA #typ linii
        )


    # dynamiczne wypisywanie instrukcji
    instrukcja_lista = [
        "Kontroler gestow uruchomiony",
        "Glowa = sterowanie myszka",
        "Usta otwarte = wspomaganie pisania",
        "Prawa reka w prawo = prawy klik myszy",
        "Prawa reka w lewo = lewy klik myszy",
        "Przytrzymanie prawej reki w lewo = przytrzymanie lewego kliku myszy",
        "Obie rece pokierowane na zewnatrz = zatrzymanie ruszu myszy",
        "Podniesienie brwi = dwa lewe kliki myszy",
        "Lewa reka w lewo = scroll w dol",
        "Lewa reka w prawo = scroll w gore",
        "Zamkniete oczy przez 5 sek = wyjscie z programu",
        "Mrugniecie szybko 3 razy = wlaczenie/wylaczenie klawiatury",
        "ESC = wyjscie"
    ]

    #zmienne pomagajace wypisac instrukcje na ekran
    x_offset = 20
    y_offset = 100
    odstep_pionowy = 18
    rozmiar_fontu = 0.45

    #nieuzywane ale moze sie przydac
    frame_count += 1

    if frame_count % 1 == 0:
        # list comprehension do wykonania operacji dla każdego elementu listy
        [cv2.putText(
            image,
            tekst_linii,
            (x_offset, y_offset + i * odstep_pionowy),
            cv2.FONT_HERSHEY_SIMPLEX,
            rozmiar_fontu,
            (255, 255, 255),
            1,
            cv2.LINE_8
        ) for i, tekst_linii in enumerate(instrukcja_lista)]
        # Sprawdzenie ESC
        if cv2.waitKey(5) & 0xFF == 27:
            break


    # Wyświetlenie okna
    cv2.imshow('Kontroler Gestow', image)

    # Sprawdzenie czy wciśnięto ESC lub zamkniete oczy przez 5s
    key = cv2.waitKey(5) & 0xFF
    if key == 27 or eyes_closed_time_remaining < 0:
        if is_left_held:
            mouse.release(Button.left)
        print("Zamykanie programu")
        #openORclose_keyboard_via_click()
        break

# Sprzątanie
cap.release()
cv2.destroyAllWindows()
print("Program zakończony pomyślnie")

