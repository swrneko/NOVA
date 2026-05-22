import sounddevice as sd
import numpy as np
import queue
import threading
import librosa

# Целевые частоты, которые ждет сервер
TARGET_MIC_SAMPLE_RATE = 16000
MIC_CHANNELS = 1
MIC_DTYPE = "float32"

SPK_SAMPLE_RATE = 22050
SPK_CHANNELS = 1
SPK_DTYPE = "int16"

class AudioIO:
    def __init__(self, input_device_index=None, output_device_index=None):
        self.is_recording = False
        self.audio_buffer = []
        
        self.input_device = input_device_index
        self.output_device = output_device_index
        
        # Получаем дефолтную частоту микрофона для выбранного устройства
        # Если None, узнаем дефолт системы
        try:
            device_info = sd.query_devices(self.input_device, 'input')
            self.actual_mic_sample_rate = int(device_info['default_samplerate'])
        except Exception:
            self.actual_mic_sample_rate = 48000 # fallback
        
        # Очередь и поток для воспроизведения звука от сервера
        self.play_queue = queue.Queue()
        self.is_playing = True
        self.stop_signal = False
        self.play_thread = threading.Thread(target=self._play_loop, daemon=True)
        self.play_thread.start()

    @staticmethod
    def get_devices():
        """Возвращает список устройств: (input_devices, output_devices)"""
        devices = sd.query_devices()
        hostapis = sd.query_hostapis()
        
        inputs = []
        outputs = []
        
        for i, dev in enumerate(devices):
            hostapi_name = hostapis[dev['hostapi']]['name']
            name = f"{i}: {dev['name']} ({hostapi_name})"
            if dev['max_input_channels'] > 0:
                inputs.append({"id": i, "name": name})
            if dev['max_output_channels'] > 0:
                outputs.append({"id": i, "name": name})
                
        return inputs, outputs

    def start_recording(self):
        """Начинает захват аудио с микрофона."""
        self.is_recording = True
        self.audio_buffer = []
        
        def callback(indata, frames, time, status):
            if status:
                print(f"Microphone error: {status}")
            if self.is_recording:
                # Копируем данные, чтобы они не перезаписались
                # indata может содержать несколько каналов, берем первый
                self.audio_buffer.append(indata[:, 0].copy() if indata.ndim > 1 else indata.copy())
                
        try:
            self.stream = sd.InputStream(
                device=self.input_device,
                samplerate=self.actual_mic_sample_rate, # Записываем в родной частоте
                channels=MIC_CHANNELS,
                dtype=MIC_DTYPE,
                callback=callback
            )
        except Exception as e:
            print(f"Failed to open selected microphone {self.input_device}: {e}. Falling back to default.")
            try:
                device_info = sd.query_devices(None, 'input')
                self.actual_mic_sample_rate = int(device_info['default_samplerate'])
            except Exception:
                self.actual_mic_sample_rate = 48000
                
            self.stream = sd.InputStream(
                device=None,
                samplerate=self.actual_mic_sample_rate,
                channels=MIC_CHANNELS,
                dtype=MIC_DTYPE,
                callback=callback
            )
            
        self.stream.start()

    def stop_recording(self) -> bytes:
        """Останавливает запись и возвращает сырые байты."""
        self.is_recording = False
        if hasattr(self, 'stream'):
            self.stream.stop()
            self.stream.close()
            
        if not self.audio_buffer:
            return b""
            
        # Объединяем все куски
        audio_data = np.concatenate(self.audio_buffer, axis=0)
        
        # Если родная частота отличается от 16000, делаем ресэмпл
        if self.actual_mic_sample_rate != TARGET_MIC_SAMPLE_RATE:
            audio_data = librosa.resample(
                y=audio_data, 
                orig_sr=self.actual_mic_sample_rate, 
                target_sr=TARGET_MIC_SAMPLE_RATE
            )
            
        return audio_data.tobytes()

    def play_audio_bytes(self, audio_bytes: bytes):
        """Добавляет полученные от сервера байты в очередь воспроизведения."""
        if audio_bytes:
            # Конвертируем байты в numpy массив int16
            audio_np = np.frombuffer(audio_bytes, dtype=np.int16)
            self.play_queue.put(audio_np)

    def abort_playback(self):
        """Очищает очередь воспроизведения и мгновенно останавливает текущий буфер."""
        self.stop_signal = True
        while not self.play_queue.empty():
            try:
                self.play_queue.get_nowait()
            except queue.Empty:
                break

    def _play_loop(self):
        """Фоновый поток, который непрерывно читает очередь и проигрывает звук."""
        device = self.output_device
        try:
            stream = sd.OutputStream(device=device, samplerate=SPK_SAMPLE_RATE, channels=SPK_CHANNELS, dtype=SPK_DTYPE)
        except Exception as e:
            print(f"Failed to open selected output device {device}: {e}. Falling back to default output.")
            try:
                stream = sd.OutputStream(device=None, samplerate=SPK_SAMPLE_RATE, channels=SPK_CHANNELS, dtype=SPK_DTYPE)
            except Exception as e2:
                print(f"Failed to open default output stream: {e2}")
                return

        # Задаем небольшой размер чанка записи на звуковую карту (1024 сэмплов ≈ 46 мс)
        # Это гарантирует, что при установке stop_signal звук прервется мгновенно!
        PLAY_CHUNK_SIZE = 1024

        with stream:
            while self.is_playing:
                try:
                    # Блокируемся, пока не придут новые байты
                    audio_np = self.play_queue.get(timeout=0.5)
                    
                    self.stop_signal = False
                    offset = 0
                    
                    # Записываем массив частями, проверяя флаг отмены на каждой итерации
                    while offset < len(audio_np) and self.is_playing:
                        if self.stop_signal:
                            break
                        
                        chunk = audio_np[offset : offset + PLAY_CHUNK_SIZE]
                        stream.write(chunk)
                        offset += PLAY_CHUNK_SIZE
                        
                except queue.Empty:
                    continue
                except Exception as e:
                    print(f"Playback error: {e}")

    def stop(self):
        """Очистка ресурсов при выходе."""
        self.is_playing = False
        if self.play_thread.is_alive():
            self.play_thread.join(timeout=1.0)
